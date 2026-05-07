/*
 * server.c  –  Servidor de mensajería distribuida
 *
 * Uso:  ./server -p <puerto>
 *
 * Compila con:  gcc -std=gnu99 -Wall -Wextra -pthread -o server server.c
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

/* Constantes */

#define MAX_NAME   256   /* longitud máxima de nombre de usuario / operación */
#define MAX_MSG    256   /* longitud máxima del cuerpo del mensaje           */
#define MAX_FILE   256   /* longitud máxima del nombre de fichero            */
#define MAX_PORT     8   /* longitud máxima del puerto en formato cadena     */
#define BACKLOG     32   /* cola de conexiones pendientes                    */

/* Tipos de datos */

/* Estado de un usuario registrado */
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

/* Estado global */

static user_t          *g_users     = NULL;
static pthread_mutex_t  g_mutex     = PTHREAD_MUTEX_INITIALIZER;
static int              g_server_fd = -1;   /* socket de escucha */

/* Manejador de señal SIGINT */

static void sigint_handler(int sig)
{
    (void)sig;
    printf("\ns> Shutting down server.\n");
    if (g_server_fd >= 0) close(g_server_fd);
    exit(0);
}

/* Utilidades de red */

/*
 * get_local_ip – rellena buf con la primera IPv4 no-loopback del sistema.
 * Si no la encuentra usa "127.0.0.1".
 */
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

/*
 * send_str – envía una cadena NUL-terminada (incluyendo '\0') por sock.
 * Devuelve 0 en éxito, -1 en error.
 */
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

/*
 * recv_str – recibe una cadena NUL-terminada en buf (máx buflen bytes).
 * Devuelve 0 en éxito, -1 en error o desbordamiento de buffer.
 */
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

/*
 * connect_to – abre una conexión TCP a ip:port.
 * Devuelve el fd del socket en éxito, -1 en error.
 */
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

/* Entrega de mensajes */

/*
 * deliver_message – conecta al hilo de escucha de un cliente y envía
 * un mensaje según el protocolo §8.6 (sin adjunto) o §2.3 (con adjunto).
 * Devuelve 0 en éxito, -1 en error de red.
 */
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

/*
 * send_delivery_ack – notifica al remitente que su mensaje fue entregado
 * (protocolo §8.6 ACK para SEND, §2.3 ACK para SENDATTACH).
 */
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

/* Operaciones sobre la lista de usuarios. El llamador debe mantener g_mutex. */

/* Busca un usuario por nombre. Requiere g_mutex. */
static user_t *find_user(const char *name)
{
    user_t *u = g_users;
    while (u) {
        if (strcmp(u->name, name) == 0) return u;
        u = u->next;
    }
    return NULL;
}

/* Crea y registra un nuevo usuario. Requiere g_mutex. */
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

/* Elimina un usuario y sus mensajes pendientes. Requiere g_mutex. */
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

/*
 * remove_pending – elimina el primer mensaje pendiente que coincide con
 * id + sender de la cola de un usuario. Requiere g_mutex.
 */
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

/*
 * next_msg_id – incrementa el último id asignado del usuario.
 * En caso de desbordamiento (pasa por 0) asigna 1. Requiere g_mutex.
 */
static unsigned int next_msg_id(user_t *u)
{
    u->last_msg_id++;
    if (u->last_msg_id == 0) u->last_msg_id = 1;
    return u->last_msg_id;
}

/* Manejadores de operaciones */

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

/*
 * handle_connect – conecta al usuario, guarda su IP:puerto de escucha y
 * entrega todos los mensajes pendientes uno a uno (protocolo §7.4 / §8.6).
 */
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

    /* Entrega de mensajes pendientes: tomar uno a uno con el mutex */
    while (1) {
        pthread_mutex_lock(&g_mutex);
        user_t *uu = find_user(username);
        if (!uu || !uu->pending) {
            pthread_mutex_unlock(&g_mutex);
            break;
        }
        /* Extraer el primer mensaje de la cola */
        message_t *m   = uu->pending;
        uu->pending    = m->next;
        m->next        = NULL;
        pthread_mutex_unlock(&g_mutex);

        int ok = deliver_message(lip, lport, m);
        if (ok == 0) {
            printf("s> SEND MESSAGE %u FROM %s TO %s\n",
                   m->id, m->sender, username);

            /* ACK al remitente original si sigue conectado */
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
            /* Error de entrega: devolver mensaje a la cola y desconectar */
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

/* DISCONNECT: desconecta al usuario (borra IP/puerto, cambia estado). */
static void handle_disconnect(int sock, const char *username)
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

/*
 * handle_send – gestiona SEND y SENDATTACH.
 * Para SEND, filename debe ser "".
 * Protocolo: §8.5 (cliente→servidor) y §8.6 (entrega).
 */
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

    /* Añadir al final de la cola de pendientes del destinatario */
    message_t **pp = &dst->pending;
    while (*pp) pp = &(*pp)->next;
    *pp = m;

    /* Capturar estado de conexión antes de liberar el mutex */
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

    /* Responder al remitente: código 0 + identificador */
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

            /* Eliminar de pendientes (ya entregado) */
            pthread_mutex_lock(&g_mutex);
            user_t *dst2 = find_user(to);
            if (dst2) remove_pending(dst2, msg_id, from);
            pthread_mutex_unlock(&g_mutex);

            /* ACK al remitente */
            if (src_conn)
                (void)send_delivery_ack(src_ip, src_port, msg_id, filename);
        } else {
            /* Error de entrega: marcar destino como desconectado */
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

/*
 * handle_users – devuelve la lista de usuarios conectados (protocolo §8.7).
 * Construye un snapshot con el mutex y envía los datos sin mantener el lock.
 */
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

    /* Construir snapshot dinámico de usuarios conectados */
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
            names[count] = strdup(u->name);
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

    /* Enviar número de usuarios y sus nombres */
    char count_str[32];
    snprintf(count_str, sizeof(count_str), "%d", count);
    (void)send_str(sock, count_str);

    for (int i = 0; i < count; i++) {
        (void)send_str(sock, names[i]);
        free(names[i]);
    }
    free(names);
}

/* Hilo por conexión */

/*
 * handle_client – lee la operación del socket y despacha al manejador
 * correspondiente. Se ejecuta en un hilo independiente por cada conexión.
 */
static void *handle_client(void *arg)
{
    int sock = *(int *)arg;
    free(arg);

    /* Obtener IP del cliente a partir del socket */
    struct sockaddr_in addr;
    socklen_t          addrlen = sizeof(addr);
    char               client_ip[INET_ADDRSTRLEN] = "0.0.0.0";
    if (getpeername(sock, (struct sockaddr *)&addr, &addrlen) == 0)
        inet_ntop(AF_INET, &addr.sin_addr, client_ip, sizeof(client_ip));

    /* Leer cadena de operación */
    char op[MAX_NAME];
    if (recv_str(sock, op, sizeof(op)) != 0) {
        close(sock);
        return NULL;
    }

    /* Despachar según la operación */
    if (strcmp(op, "REGISTER") == 0) {
        char user[MAX_NAME];
        if (recv_str(sock, user, sizeof(user)) == 0)
            handle_register(sock, user);

    } else if (strcmp(op, "UNREGISTER") == 0) {
        char user[MAX_NAME];
        if (recv_str(sock, user, sizeof(user)) == 0)
            handle_unregister(sock, user);

    } else if (strcmp(op, "CONNECT") == 0) {
        char user[MAX_NAME], lport[MAX_PORT];
        if (recv_str(sock, user,  sizeof(user))  == 0 &&
            recv_str(sock, lport, sizeof(lport)) == 0)
            handle_connect(sock, user, lport, client_ip);

    } else if (strcmp(op, "DISCONNECT") == 0) {
        char user[MAX_NAME];
        if (recv_str(sock, user, sizeof(user)) == 0)
            handle_disconnect(sock, user);

    } else if (strcmp(op, "SEND") == 0) {
        char from[MAX_NAME], to[MAX_NAME], msg[MAX_MSG];
        if (recv_str(sock, from, sizeof(from)) == 0 &&
            recv_str(sock, to,   sizeof(to))   == 0 &&
            recv_str(sock, msg,  sizeof(msg))  == 0)
            handle_send(sock, from, to, msg, "");

    } else if (strcmp(op, "SENDATTACH") == 0) {
        char from[MAX_NAME], to[MAX_NAME], msg[MAX_MSG], file[MAX_FILE];
        if (recv_str(sock, from, sizeof(from)) == 0 &&
            recv_str(sock, to,   sizeof(to))   == 0 &&
            recv_str(sock, msg,  sizeof(msg))  == 0 &&
            recv_str(sock, file, sizeof(file)) == 0)
            handle_send(sock, from, to, msg, file);

    } else if (strcmp(op, "USERS") == 0) {
        char user[MAX_NAME];
        if (recv_str(sock, user, sizeof(user)) == 0)
            handle_users(sock, user);
    }

    close(sock);
    return NULL;
}

int main(int argc, char *argv[])
{
    int port = -1;

    /* Parseo de -p <puerto> */
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

    /* Instalar manejador SIGINT */
    struct sigaction sa;
    memset(&sa, 0, sizeof(sa));
    sa.sa_handler = sigint_handler;
    sigemptyset(&sa.sa_mask);
    sigaction(SIGINT, &sa, NULL);

    /* Crear socket TCP de escucha */
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

    /* Mensaje de arranque */
    char local_ip[INET_ADDRSTRLEN];
    get_local_ip(local_ip, sizeof(local_ip));
    printf("s> init server %s:%d\n", local_ip, port);
    printf("s> ");
    fflush(stdout);

    /* Bucle de aceptación – un hilo por conexión */
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

    /* Inalcanzable – la limpieza se hace en sigint_handler */
    return 0;
}
