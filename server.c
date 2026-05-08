/* server.c – Servidor de mensajería distribuida.
 * Uso: ./server -p <puerto>
 * Variable de entorno opcional: LOG_RPC_IP=<ip> para activar el log RPC.
 */

#define _GNU_SOURCE          /* habilita getifaddrs y extensiones POSIX */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <signal.h>
#include <pthread.h>
#include <arpa/inet.h>
#include <netinet/in.h>
#include <sys/socket.h>
#include <sys/types.h>
#include <ifaddrs.h>
#include <rpc/rpc.h>
#include "log.h"

#define MAX_NAME   256   /* longitud máxima de nombre de usuario / operación */
#define MAX_MSG    256   /* longitud máxima del cuerpo del mensaje           */
#define MAX_FILE   256   /* longitud máxima del nombre de fichero            */
#define MAX_PORT     8   /* longitud máxima del puerto en formato cadena     */
#define BACKLOG     32   /* cola de conexiones pendientes                    */

typedef enum { DISCONNECTED = 0, CONNECTED = 1 } user_state_t;

/* Mensaje pendiente de entrega */
typedef struct message {
    unsigned int    id;
    char            sender[MAX_NAME];
    char            body[MAX_MSG];
    char            filename[MAX_FILE]; /* cadena vacía si no hay adjunto */
    struct message *next;
} message_t;

/* Entrada en la lista de usuarios registrados */
typedef struct user {
    char            name[MAX_NAME];
    user_state_t    state;
    char            ip[INET_ADDRSTRLEN];
    char            port[MAX_PORT];
    unsigned int    last_msg_id;        /* 0 al registrar; desbordamiento: 0→1 */
    message_t      *pending;
    struct user    *next;
} user_t;

static user_t          *g_users       = NULL;
static pthread_mutex_t  g_mutex       = PTHREAD_MUTEX_INITIALIZER;
static int              g_server_fd   = -1;
static CLIENT          *g_rpc_client  = NULL;
static pthread_mutex_t  g_rpc_mutex   = PTHREAD_MUTEX_INITIALIZER;
static char             g_rpc_ip[64]  = "";   /* vacío → RPC desactivado */

/* Envía una entrada de log al servidor ONC-RPC. No-op si LOG_RPC_IP no está definida
 * o el servidor no responde (degradación silenciosa). */
static void call_log_rpc(const char *username, const char *operation)
{
    if (g_rpc_ip[0] == '\0') return;

    pthread_mutex_lock(&g_rpc_mutex);

    if (g_rpc_client == NULL) {
        g_rpc_client = clnt_create(g_rpc_ip, LOG_PROG, LOG_VERS, "tcp");
        if (g_rpc_client == NULL) {
            pthread_mutex_unlock(&g_rpc_mutex);
            return;
        }
    }

    char *u  = (char *)username;
    char *op = (char *)operation;
    int  *res = log_operation_1(u, op, g_rpc_client);
    if (res == NULL) {
        clnt_destroy(g_rpc_client);
        g_rpc_client = NULL;
    }

    pthread_mutex_unlock(&g_rpc_mutex);
}

static void sigint_handler(int sig)
{
    (void)sig;
    printf("\ns> Shutting down server.\n");
    if (g_server_fd >= 0) close(g_server_fd);
    exit(0);
}

/* Rellena buf con la primera IPv4 no-loopback; usa "127.0.0.1" si no encuentra ninguna. */
static void get_local_ip(char *buf, size_t len)
{
    struct ifaddrs *ifaddr, *ifa;
    strncpy(buf, "127.0.0.1", len - 1);
    buf[len - 1] = '\0';
    if (getifaddrs(&ifaddr) != 0) return;
    for (ifa = ifaddr; ifa != NULL; ifa = ifa->ifa_next) {
        if (!ifa->ifa_addr || ifa->ifa_addr->sa_family != AF_INET) continue;
        const char *ip = inet_ntoa(
            ((struct sockaddr_in *)ifa->ifa_addr)->sin_addr);
        if (strcmp(ip, "127.0.0.1") != 0) {
            strncpy(buf, ip, len - 1);
            buf[len - 1] = '\0';
            break;
        }
    }
    freeifaddrs(ifaddr);
}

/* Envía una cadena NUL-terminada por sock. Devuelve 0 en éxito, -1 en error. */
static int send_str(int sock, const char *s)
{
    size_t  len   = strlen(s) + 1;
    size_t  total = 0;
    ssize_t n;
    while (total < len) {
        n = send(sock, s + total, len - total, 0);
        if (n <= 0) return -1;
        total += (size_t)n;
    }
    return 0;
}

/* Recibe una cadena NUL-terminada en buf. Devuelve 0 en éxito, -1 en error o desbordamiento. */
static int recv_str(int sock, char *buf, size_t buflen)
{
    size_t  i = 0;
    ssize_t r;
    char    c;
    while (i < buflen) {
        r = recv(sock, &c, 1, 0);
        if (r <= 0) return -1;
        buf[i++] = c;
        if (c == '\0') return 0;
    }
    return -1;  /* desbordamiento de buffer */
}

/* Abre una conexión TCP a ip:port. Devuelve el fd del socket, o -1 en error. */
static int connect_to(const char *ip, const char *port)
{
    struct sockaddr_in addr;
    memset(&addr, 0, sizeof(addr));
    addr.sin_family = AF_INET;
    addr.sin_port   = htons((uint16_t)atoi(port));
    if (inet_pton(AF_INET, ip, &addr.sin_addr) <= 0) return -1;
    int s = socket(AF_INET, SOCK_STREAM, 0);
    if (s < 0) return -1;
    if (connect(s, (struct sockaddr *)&addr, sizeof(addr)) < 0) {
        close(s);
        return -1;
    }
    return s;
}

/* Conecta al hilo de escucha del cliente y entrega un mensaje. Devuelve 0 o -1. */
static int deliver_message(const char *ip, const char *port,
                            const message_t *m)
{
    char id_str[32];
    snprintf(id_str, sizeof(id_str), "%u", m->id);

    int s = connect_to(ip, port);
    if (s < 0) return -1;

    int ok;
    if (m->filename[0] == '\0')
        ok  = send_str(s, "SEND MESSAGE");
    else
        ok  = send_str(s, "SEND MESSAGE ATTACH");

    ok |= send_str(s, m->sender);
    ok |= send_str(s, id_str);
    ok |= send_str(s, m->body);
    if (m->filename[0] != '\0') ok |= send_str(s, m->filename);

    close(s);
    return ok;
}

/* Notifica al remitente la entrega exitosa de un mensaje. */
static int send_delivery_ack(const char *ip, const char *port,
                              unsigned int id, const char *filename)
{
    char id_str[32];
    snprintf(id_str, sizeof(id_str), "%u", id);

    int s = connect_to(ip, port);
    if (s < 0) return -1;

    int ok;
    if (!filename || filename[0] == '\0') {
        ok  = send_str(s, "SEND MESS ACK");
        ok |= send_str(s, id_str);
    } else {
        ok  = send_str(s, "SEND MESS ATTACH ACK");
        ok |= send_str(s, id_str);
        ok |= send_str(s, filename);
    }

    close(s);
    return ok;
}

/* Las funciones siguientes operan sobre g_users y requieren que el llamador mantenga g_mutex. */

/* Busca un usuario por nombre. */
static user_t *find_user(const char *name)
{
    user_t *u = g_users;
    while (u) {
        if (strcmp(u->name, name) == 0) return u;
        u = u->next;
    }
    return NULL;
}

/* Crea y añade un nuevo usuario a la lista. */
static user_t *create_user(const char *name)
{
    user_t *u = (user_t *)calloc(1, sizeof(user_t));
    if (!u) return NULL;
    strncpy(u->name, name, MAX_NAME - 1);
    u->state       = DISCONNECTED;
    u->last_msg_id = 0;
    u->next        = g_users;
    g_users        = u;
    return u;
}

/* Libera una lista enlazada de mensajes. */
static void free_messages(message_t *m)
{
    while (m) {
        message_t *tmp = m->next;
        free(m);
        m = tmp;
    }
}

/* Elimina un usuario y libera sus mensajes pendientes. */
static void remove_user(const char *name)
{
    user_t **pp = &g_users;
    while (*pp) {
        if (strcmp((*pp)->name, name) == 0) {
            user_t *del = *pp;
            *pp = del->next;
            free_messages(del->pending);
            free(del);
            return;
        }
        pp = &(*pp)->next;
    }
}

/* Elimina de la cola del usuario el primer mensaje pendiente con id y sender dados. */
static void remove_pending(user_t *u, unsigned int id, const char *sender)
{
    message_t **pp = &u->pending;
    while (*pp) {
        if ((*pp)->id == id && strcmp((*pp)->sender, sender) == 0) {
            message_t *del = *pp;
            *pp = del->next;
            free(del);
            return;
        }
        pp = &(*pp)->next;
    }
}

/* Incrementa y devuelve el siguiente id de mensaje; salta el valor 0. */
static unsigned int next_msg_id(user_t *u)
{
    u->last_msg_id++;
    if (u->last_msg_id == 0) u->last_msg_id = 1;
    return u->last_msg_id;
}

/* REGISTER: registra un nuevo usuario si no existe. */
static void handle_register(int sock, const char *username)
{
    unsigned char code;

    pthread_mutex_lock(&g_mutex);
    if (find_user(username)) {
        code = 1;
        printf("s> REGISTER %s FAIL\n", username);
    } else if (!create_user(username)) {
        code = 2;
        printf("s> REGISTER %s FAIL\n", username);
    } else {
        code = 0;
        printf("s> REGISTER %s OK\n", username);
    }
    pthread_mutex_unlock(&g_mutex);

    (void)send(sock, &code, 1, 0);
}

/* UNREGISTER: da de baja a un usuario existente y borra sus mensajes pendientes. */
static void handle_unregister(int sock, const char *username)
{
    unsigned char code;

    pthread_mutex_lock(&g_mutex);
    if (!find_user(username)) {
        code = 1;
        printf("s> UNREGISTER %s FAIL\n", username);
    } else {
        remove_user(username);
        code = 0;
        printf("s> UNREGISTER %s OK\n", username);
    }
    pthread_mutex_unlock(&g_mutex);

    (void)send(sock, &code, 1, 0);
}

/* CONNECT: marca al usuario como conectado y entrega los mensajes pendientes. */
static void handle_connect(int sock, const char *username,
                             const char *listen_port, const char *client_ip)
{
    unsigned char code;
    char          lip[INET_ADDRSTRLEN] = {0};
    char          lport[MAX_PORT]      = {0};

    pthread_mutex_lock(&g_mutex);
    user_t *u = find_user(username);
    if (!u) {
        code = 1;
        printf("s> CONNECT %s FAIL\n", username);
    } else if (u->state == CONNECTED) {
        code = 2;
        printf("s> CONNECT %s FAIL\n", username);
    } else {
        strncpy(u->ip,   client_ip,   INET_ADDRSTRLEN - 1);
        strncpy(u->port, listen_port, MAX_PORT - 1);
        u->state = CONNECTED;
        strncpy(lip,  u->ip,   INET_ADDRSTRLEN - 1);
        strncpy(lport, u->port, MAX_PORT - 1);
        code = 0;
        printf("s> CONNECT %s OK\n", username);
    }
    pthread_mutex_unlock(&g_mutex);

    (void)send(sock, &code, 1, 0);
    if (code != 0) return;

    /* Entrega de mensajes pendientes */
    while (1) {
        pthread_mutex_lock(&g_mutex);
        user_t *uu = find_user(username);
        if (!uu || !uu->pending) {
            pthread_mutex_unlock(&g_mutex);
            break;
        }
        message_t *m   = uu->pending;
        uu->pending    = m->next;
        m->next        = NULL;
        pthread_mutex_unlock(&g_mutex);

        int ok = deliver_message(lip, lport, m);
        if (ok == 0) {
            printf("s> SEND MESSAGE %u FROM %s TO %s\n",
                   m->id, m->sender, username);

            pthread_mutex_lock(&g_mutex);
            user_t *sndr   = find_user(m->sender);
            char s_ip[INET_ADDRSTRLEN] = {0};
            char s_port[MAX_PORT]      = {0};
            int  s_conn = sndr && sndr->state == CONNECTED;
            if (s_conn) {
                strncpy(s_ip,   sndr->ip,   INET_ADDRSTRLEN - 1);
                strncpy(s_port, sndr->port, MAX_PORT - 1);
            }
            pthread_mutex_unlock(&g_mutex);

            if (s_conn)
                (void)send_delivery_ack(s_ip, s_port, m->id, m->filename);
            free(m);
        } else {
            /* Fallo de entrega: devolver mensaje a la cola y marcar desconectado */
            pthread_mutex_lock(&g_mutex);
            user_t *uu2 = find_user(username);
            if (uu2) {
                m->next     = uu2->pending;
                uu2->pending = m;
                uu2->state  = DISCONNECTED;
                memset(uu2->ip,   0, sizeof(uu2->ip));
                memset(uu2->port, 0, sizeof(uu2->port));
            } else {
                free(m);
            }
            pthread_mutex_unlock(&g_mutex);
            break;
        }
    }
}

/* DISCONNECT: marca al usuario como desconectado y borra su IP/puerto.
 * Solo se acepta si la petición proviene de la misma IP con la que el usuario
 * se conectó (requisito del protocolo §8.4). */
static void handle_disconnect(int sock, const char *username,
                               const char *client_ip)
{
    unsigned char code;

    pthread_mutex_lock(&g_mutex);
    user_t *u = find_user(username);
    if (!u) {
        code = 1;
        printf("s> DISCONNECT %s FAIL\n", username);
    } else if (u->state == DISCONNECTED) {
        code = 2;
        printf("s> DISCONNECT %s FAIL\n", username);
    } else if (strcmp(u->ip, client_ip) != 0) {
        /* IP no coincide con la registrada en CONNECT */
        code = 3;
        printf("s> DISCONNECT %s FAIL\n", username);
    } else {
        memset(u->ip,   0, sizeof(u->ip));
        memset(u->port, 0, sizeof(u->port));
        u->state = DISCONNECTED;
        code = 0;
        printf("s> DISCONNECT %s OK\n", username);
    }
    pthread_mutex_unlock(&g_mutex);

    (void)send(sock, &code, 1, 0);
}

/* SEND / SENDATTACH: encola el mensaje y lo entrega si el destinatario está conectado.
 * Para SEND, filename debe ser "". */
static void handle_send(int sock, const char *from, const char *to,
                          const char *msg,  const char *filename)
{
    unsigned char code;
    unsigned int  msg_id = 0;
    char          id_str[32];

    pthread_mutex_lock(&g_mutex);
    user_t *src = find_user(from);
    user_t *dst = find_user(to);

    if (!src || !dst) {
        code = 1;
        pthread_mutex_unlock(&g_mutex);
        (void)send(sock, &code, 1, 0);
        printf("s> SEND MESSAGE 0 FROM %s TO %s FAIL\n", from, to);
        return;
    }

    msg_id = next_msg_id(src);
    message_t *m = (message_t *)calloc(1, sizeof(message_t));
    if (!m) {
        code = 2;
        pthread_mutex_unlock(&g_mutex);
        (void)send(sock, &code, 1, 0);
        return;
    }

    m->id = msg_id;
    strncpy(m->sender,   from,     MAX_NAME - 1);
    strncpy(m->body,     msg,      MAX_MSG  - 1);
    strncpy(m->filename, filename, MAX_FILE - 1);
    m->next = NULL;

    message_t **pp = &dst->pending;
    while (*pp) pp = &(*pp)->next;
    *pp = m;

    int  dst_conn = (dst->state == CONNECTED);
    char dst_ip[INET_ADDRSTRLEN] = {0};
    char dst_port[MAX_PORT]      = {0};
    int  src_conn = (src->state == CONNECTED);
    char src_ip[INET_ADDRSTRLEN] = {0};
    char src_port[MAX_PORT]      = {0};
    if (dst_conn) {
        strncpy(dst_ip,   dst->ip,   INET_ADDRSTRLEN - 1);
        strncpy(dst_port, dst->port, MAX_PORT - 1);
    }
    if (src_conn) {
        strncpy(src_ip,   src->ip,   INET_ADDRSTRLEN - 1);
        strncpy(src_port, src->port, MAX_PORT - 1);
    }
    pthread_mutex_unlock(&g_mutex);

    code = 0;
    snprintf(id_str, sizeof(id_str), "%u", msg_id);
    (void)send(sock, &code, 1, 0);
    (void)send_str(sock, id_str);

    if (dst_conn) {
        /* Construir copia temporal para la entrega */
        message_t tmp;
        memset(&tmp, 0, sizeof(tmp));
        tmp.id = msg_id;
        strncpy(tmp.sender,   from,     MAX_NAME - 1);
        strncpy(tmp.body,     msg,      MAX_MSG  - 1);
        strncpy(tmp.filename, filename, MAX_FILE - 1);

        int ok = deliver_message(dst_ip, dst_port, &tmp);
        if (ok == 0) {
            printf("s> SEND MESSAGE %u FROM %s TO %s\n", msg_id, from, to);
            pthread_mutex_lock(&g_mutex);
            user_t *dst2 = find_user(to);
            if (dst2) remove_pending(dst2, msg_id, from);
            pthread_mutex_unlock(&g_mutex);

            if (src_conn)
                (void)send_delivery_ack(src_ip, src_port, msg_id, filename);
        } else {
            /* Fallo de entrega: marcar destino como desconectado */
            pthread_mutex_lock(&g_mutex);
            user_t *dst2 = find_user(to);
            if (dst2) {
                dst2->state = DISCONNECTED;
                memset(dst2->ip,   0, sizeof(dst2->ip));
                memset(dst2->port, 0, sizeof(dst2->port));
            }
            pthread_mutex_unlock(&g_mutex);
            printf("s> MESSAGE %u FROM %s TO %s STORED\n", msg_id, from, to);
        }
    } else {
        printf("s> MESSAGE %u FROM %s TO %s STORED\n", msg_id, from, to);
    }
}

/* USERS: devuelve la lista de usuarios conectados. */
static void handle_users(int sock, const char *username)
{
    unsigned char code;
    char        **names = NULL;
    int           count = 0, cap = 0;

    pthread_mutex_lock(&g_mutex);
    user_t *req = find_user(username);

    if (!req) {
        code = 2;
        printf("s> CONNECTEDUSERS FAIL\n");
        pthread_mutex_unlock(&g_mutex);
        (void)send(sock, &code, 1, 0);
        return;
    }
    if (req->state != CONNECTED) {
        code = 1;
        printf("s> CONNECTEDUSERS FAIL\n");
        pthread_mutex_unlock(&g_mutex);
        (void)send(sock, &code, 1, 0);
        return;
    }

    code = 0;
    user_t *u = g_users;
    while (u) {
        if (u->state == CONNECTED) {
            if (count >= cap) {
                int newcap = (cap == 0) ? 16 : cap * 2;
                char **tmp = (char **)realloc(names,
                                              (size_t)newcap * sizeof(char *));
                if (!tmp) { code = 2; break; }
                names = tmp;
                cap   = newcap;
            }
            if (asprintf(&names[count], "%s::%s::%s",
                         u->name, u->ip, u->port) < 0) {
                names[count] = NULL;
            }
            if (!names[count]) { code = 2; break; }
            count++;
        }
        u = u->next;
    }

    if (code == 0)
        printf("s> CONNECTEDUSERS OK\n");
    else
        printf("s> CONNECTEDUSERS FAIL\n");

    pthread_mutex_unlock(&g_mutex);

    (void)send(sock, &code, 1, 0);

    if (code != 0) {
        for (int i = 0; i < count; i++) free(names[i]);
        free(names);
        return;
    }

    char count_str[32];
    snprintf(count_str, sizeof(count_str), "%d", count);
    (void)send_str(sock, count_str);

    for (int i = 0; i < count; i++) {
        (void)send_str(sock, names[i]);
        free(names[i]);
    }
    free(names);
}

/* Hilo por conexión: lee la operación del socket y despacha al manejador correspondiente. */
static void *handle_client(void *arg)
{
    int sock = *(int *)arg;
    free(arg);

    struct sockaddr_in addr;
    socklen_t          addrlen = sizeof(addr);
    char               client_ip[INET_ADDRSTRLEN] = "0.0.0.0";
    if (getpeername(sock, (struct sockaddr *)&addr, &addrlen) == 0)
        inet_ntop(AF_INET, &addr.sin_addr, client_ip, sizeof(client_ip));

    char op[MAX_NAME];
    if (recv_str(sock, op, sizeof(op)) != 0) {
        close(sock);
        return NULL;
    }

    if (strcmp(op, "REGISTER") == 0) {
        char user[MAX_NAME];
        if (recv_str(sock, user, sizeof(user)) == 0) {
            call_log_rpc(user, "REGISTER");
            handle_register(sock, user);
        }

    } else if (strcmp(op, "UNREGISTER") == 0) {
        char user[MAX_NAME];
        if (recv_str(sock, user, sizeof(user)) == 0) {
            call_log_rpc(user, "UNREGISTER");
            handle_unregister(sock, user);
        }

    } else if (strcmp(op, "CONNECT") == 0) {
        char user[MAX_NAME], lport[MAX_PORT];
        if (recv_str(sock, user,  sizeof(user))  == 0 &&
            recv_str(sock, lport, sizeof(lport)) == 0) {
            call_log_rpc(user, "CONNECT");
            handle_connect(sock, user, lport, client_ip);
        }

    } else if (strcmp(op, "DISCONNECT") == 0) {
        char user[MAX_NAME];
        if (recv_str(sock, user, sizeof(user)) == 0) {
            call_log_rpc(user, "DISCONNECT");
            handle_disconnect(sock, user, client_ip);
        }

    } else if (strcmp(op, "SEND") == 0) {
        char from[MAX_NAME], to[MAX_NAME], msg[MAX_MSG];
        if (recv_str(sock, from, sizeof(from)) == 0 &&
            recv_str(sock, to,   sizeof(to))   == 0 &&
            recv_str(sock, msg,  sizeof(msg))  == 0) {
            call_log_rpc(from, "SEND");
            handle_send(sock, from, to, msg, "");
        }

    } else if (strcmp(op, "SENDATTACH") == 0) {
        char from[MAX_NAME], to[MAX_NAME], msg[MAX_MSG], file[MAX_FILE];
        if (recv_str(sock, from, sizeof(from)) == 0 &&
            recv_str(sock, to,   sizeof(to))   == 0 &&
            recv_str(sock, msg,  sizeof(msg))  == 0 &&
            recv_str(sock, file, sizeof(file)) == 0) {
            char log_op[MAX_NAME + MAX_FILE];
            snprintf(log_op, sizeof(log_op), "SENDATTACH %s", file);
            call_log_rpc(from, log_op);
            handle_send(sock, from, to, msg, file);
        }

    } else if (strcmp(op, "USERS") == 0) {
        char user[MAX_NAME];
        if (recv_str(sock, user, sizeof(user)) == 0) {
            call_log_rpc(user, "USERS");
            handle_users(sock, user);
        }
    }

    close(sock);
    return NULL;
}

int main(int argc, char *argv[])
{
    int port = -1;

    setvbuf(stdout, NULL, _IOLBF, 0);

    const char *log_ip = getenv("LOG_RPC_IP");
    if (log_ip && log_ip[0] != '\0') {
        strncpy(g_rpc_ip, log_ip, sizeof(g_rpc_ip) - 1);
        g_rpc_ip[sizeof(g_rpc_ip) - 1] = '\0';
    }

    for (int i = 1; i < argc - 1; i++) {
        if (strcmp(argv[i], "-p") == 0) {
            port = atoi(argv[i + 1]);
            break;
        }
    }
    if (port <= 0 || port > 65535) {
        fprintf(stderr, "Uso: %s -p <puerto>\n", argv[0]);
        return 1;
    }

    struct sigaction sa;
    memset(&sa, 0, sizeof(sa));
    sa.sa_handler = sigint_handler;
    sigemptyset(&sa.sa_mask);
    sigaction(SIGINT, &sa, NULL);

    g_server_fd = socket(AF_INET, SOCK_STREAM, 0);
    if (g_server_fd < 0) { perror("socket"); return 1; }

    int opt = 1;
    (void)setsockopt(g_server_fd, SOL_SOCKET, SO_REUSEADDR, &opt, sizeof(opt));

    struct sockaddr_in srv;
    memset(&srv, 0, sizeof(srv));
    srv.sin_family      = AF_INET;
    srv.sin_addr.s_addr = INADDR_ANY;
    srv.sin_port        = htons((uint16_t)port);

    if (bind(g_server_fd, (struct sockaddr *)&srv, sizeof(srv)) < 0) {
        perror("bind"); return 1;
    }
    if (listen(g_server_fd, BACKLOG) < 0) {
        perror("listen"); return 1;
    }

    char local_ip[INET_ADDRSTRLEN];
    get_local_ip(local_ip, sizeof(local_ip));
    printf("s> init server %s:%d\n", local_ip, port);
    printf("s> ");
    fflush(stdout);

    while (1) {
        struct sockaddr_in cli;
        socklen_t          cli_len = sizeof(cli);
        int cli_fd = accept(g_server_fd, (struct sockaddr *)&cli, &cli_len);
        if (cli_fd < 0) continue;

        int *fd_ptr = (int *)malloc(sizeof(int));
        if (!fd_ptr) { close(cli_fd); continue; }
        *fd_ptr = cli_fd;

        pthread_t tid;
        if (pthread_create(&tid, NULL, handle_client, fd_ptr) != 0) {
            perror("pthread_create");
            free(fd_ptr);
            close(cli_fd);
        } else {
            pthread_detach(tid);
        }
    }

    return 0;
}
