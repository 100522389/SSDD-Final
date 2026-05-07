# Hoja de ruta — Servicio Distribuido de envío de mensajes

---

## Componentes

| Componente | Lenguaje | Rol |
| --- | --- | --- |
| `server.c` | C (Linux) | Servidor central de mensajería, TCP, multihilo |
| `client.py` | Python | Interfaz de usuario, multihilo |
| `web_service.py` | Python | Servicio web de normalización de mensajes |
| `rpc_server.c` | C (ONC-RPC) | Servidor de log de operaciones |
| `log.x` | XDR/rpcgen | Definición de interfaz RPC |

---

## Estructura de ficheros

SSDD-Final/
├── server.c              # Servidor principal de mensajería
├── client.py             # Cliente Python
├── web_service.py        # Servicio web (normalización de mensajes)
├── log.x                 # Interfaz RPC (.x para rpcgen)
├── rpc_server.c          # Servidor ONC-RPC (log de operaciones)
├── Makefile              # Compilación de todos los .c
├── autores.txt           # Nombres y NIAs
├── README                # Instrucciones de compilación y despliegue
└── memoria.pdf           # Memoria de la práctica

---

## Fases de implementación

En todas consultar el enunciado: Práctica_P1_25_26.txt y Práctica_P2_25_26.txt

### Preparación

- [x] Utilizar WSL
- [x] Confirmar que `gcc`, `python3`, `rpcgen`, `portmap`/`rpcbind` están disponibles *(WSL no responde; verificar manualmente con `gcc --version` etc.)*
- [x] Estructurar el repositorio
- [x] Redactar esqueleto de `server.c` con `main()`, gestión de señal `SIGINT` y arranque

---

### FASE 1 — Servidor en C (`server.c`) · *[6 puntos]*

#### Estructuras de datos internas (Ejemplos)

```c
// Estado de un usuario
typedef enum { DISCONNECTED, CONNECTED } user_state_t;

// Entrada de la lista de usuarios
typedef struct user {
    char   name[256];
    user_state_t state;
    char   ip[INET_ADDRSTRLEN];
    char   port[8];
    unsigned int last_msg_id;  // último id asignado (inicialmente 0)
    struct message *pending;   // lista enlazada de mensajes pendientes
    struct user *next;
} user_t;

// Mensaje pendiente de entrega
typedef struct message {
    unsigned int id;
    char sender[256];
    char body[256];
    char filename[256];        // vacío si no hay adjunto
    struct message *next;
} message_t;
```

- Proteger la lista de usuarios con un `pthread_mutex_t` global.
- El campo `last_msg_id` es `unsigned int`; al desbordarse vuelve a 0, y el siguiente id asignado es 1.

#### Arranque

```bash
$ ./server -p <port>
s> init server <localIP>:<port>
s>
```

- Obtener la IP local con `gethostname` + `gethostbyname` o `getifaddrs`.
- Escuchar señal `SIGINT` para terminar limpiamente (`sigaction`).
- Por cada conexión aceptada, crear un hilo (`pthread_create`) que ejecute el manejador de la petición.

#### Operaciones

| Operación | Protocolo recibido | Respuesta | Log servidor |
| --- | --- | --- | --- |
| **REGISTER** | `"REGISTER"\0` · `<user>\0` | 1 byte: 0/1/2 | `s> REGISTER <user> OK/FAIL` |
| **UNREGISTER** | `"UNREGISTER"\0` · `<user>\0` | 1 byte: 0/1/2 | `s> UNREGISTER <user> OK/FAIL` |
| **CONNECT** | `"CONNECT"\0` · `<user>\0` · `<port>\0` | 1 byte: 0/1/2/3 | `s> CONNECT <user> OK/FAIL` |
| **DISCONNECT** | `"DISCONNECT"\0` · `<user>\0` | 1 byte: 0/1/2/3 | `s> DISCONNECT <user> OK/FAIL` |
| **SEND** | `"SEND"\0` · `<from>\0` · `<to>\0` · `<msg>\0` | 1 byte + `<id>\0` (si OK) | `s> SEND MESSAGE <id> FROM <s> TO <r>` / `STORED` |
| **USERS** | `"USERS"\0` · `<user>\0` | 1 byte + `<N>\0` + N·`<user>\0` | `s> CONNECTEDUSERS OK/FAIL` |

> **SENDATTACH** (servidor) y **USERS P2** (devolver `user::ip::port`) son extensiones de P2 que se añaden en la FASE 5.

**Lógica de SEND / SENDATTACH:**

1. Incrementar `last_msg_id` (si es 0 tras desbordamiento, forzar a 1).
2. Almacenar mensaje en la cola de pendientes del destinatario.
3. Devolver código 0 + id al remitente.
4. Si el destinatario está conectado: enviar el mensaje al hilo de escucha del destinatario (protocolo §8.6 / §2.3) y, si tiene éxito, enviar ACK al remitente (protocolo §8.6 ACK / §2.3 ACK), luego eliminar el mensaje de la cola.
5. Si el destinatario no está conectado: dejar en cola; se enviarán al hacer CONNECT.

**Lógica de CONNECT:**

- Tras cambiar estado a CONNECTED y responder código 0, enviar todos los mensajes pendientes uno a uno siguiendo el protocolo §8.6.

#### Compilación

```makefile
CC      = gcc
CFLAGS  = -Wall -Wextra -pthread
TARGET  = server

$(TARGET): server.c
$(CC) $(CFLAGS) -o $(TARGET) server.c
```

---

### FASE 2 — Cliente en Python (`client.py`) · *[incluido en los 6 puntos]*

> El esqueleto (`shell`, argumentos `-s`/`-p`) ya está proporcionado. Solo hay que implementar los métodos estáticos.

#### Estado global del cliente

```python
_server      = None     # IP del servidor
_port        = -1       # Puerto del servidor
_username    = None     # Usuario conectado actualmente
_listen_sock = None     # Socket de escucha del hilo receptor
_listen_port = None     # Puerto libre elegido
_listen_thread = None   # Hilo de recepción de mensajes
_connected_users = {}   # {username: (ip, port)} — actualizado con USERS (P2)
```

#### Método `register(user)`

1. Abrir socket TCP → conectar a `(_server, _port)`.
2. Enviar `"REGISTER\0"` + `"<user>\0"`.
3. Recibir 1 byte de respuesta.
4. Imprimir según código: `REGISTER OK` / `USERNAME IN USE` / `REGISTER FAIL`.
5. Cerrar socket.

#### Método `unregister(user)`

- Misma estructura. Mensajes: `UNREGISTER OK` / `USER DOES NOT EXIST` / `UNREGISTER FAIL`.

#### Método `connect(user)`

1. Buscar un puerto libre (bind a `0`, leer el puerto asignado).
2. Crear socket de escucha y lanzar `_listen_thread` (ver §2.7).
3. Enviar `"CONNECT\0"` + `"<user>\0"` + `"<listen_port>\0"`.
4. Recibir 1 byte: 0→`CONNECT OK`, 1→`CONNECT FAIL, USER DOES NOT EXIST`, 2→`USER ALREADY CONNECTED`, otro→`CONNECT FAIL`.
5. Guardar `_username` y `_listen_port`.

#### Método `disconnect(user)`

1. Enviar `"DISCONNECT\0"` + `"<user>\0"`.
2. Recibir 1 byte: 0→`DISCONNECT OK`, 1→`DISCONNECT FAIL, USER DOES NOT EXIST`, 2→`DISCONNECT FAIL, USER NOT CONNECTED`, otro→`DISCONNECT FAIL`.
3. En cualquier caso (incluso con error), parar `_listen_thread` y cerrar `_listen_sock`.

#### Método `send(user, message)`

1. Enviar `"SEND\0"` + `"<self_user>\0"` + `"<user>\0"` + `"<message>\0"`.
2. Recibir 1 byte; si 0, recibir también `<id>\0`.
3. Imprimir: `SEND OK - MESSAGE <id>` / `SEND FAIL, USER DOES NOT EXIST` / `SEND FAIL`.

#### Hilo de escucha (`_listen_thread`)

El hilo hace `accept()` en bucle. Por cada conexión entrante lee la operación:

| Operación recibida | Acción |
| --- | --- |
| `"SEND MESSAGE\0"` | Leer `<from>\0` + `<id>\0` + `<msg>\0`. Imprimir: `s> MESSAGE <id> FROM <from>\n  <msg>\n  END` |
| `"SEND MESS ACK\0"` | Leer `<id>\0`. Imprimir: `c> SEND MESSAGE <id> OK` |
| `"SEND MESSAGE ATTACH\0"` | Leer `<from>\0` + `<id>\0` + `<msg>\0` + `<file>\0`. Imprimir: `s> MESSAGE <id> FROM <from>\n  <msg>\n  END\n  FILE <file>` |
| `"SEND MESS ATTACH ACK\0"` | Leer `<id>\0` + `<file>\0`. Imprimir: `c> SENDATTACH MESSAGE <id> <file> OK` |
| `"GET FILE\0"` | Leer `<requester>\0` + `<filename>\0`. Abrir fichero y enviar contenido por el socket. |

#### Método `users()`

- **P1:** Enviar `"USERS\0"` + `"<user>\0"`. Recibir código; si 0, recibir `<N>\0` + N cadenas `<username>\0`. Imprimir lista.
- **P2:** Las N cadenas tienen formato `<user>::<ip>::<port>\0`. Parsear y almacenar en `_connected_users`.

---

### FASE 3 — Servicio Web (Python) · *[1 punto]*

Archivo: `web_service.py`

- **Servidor SOAP**: **Spyne** expone el servicio; **Zeep** lo consume desde `client.py`.
- Operación SOAP: `normalize(message: str) → str` — elimina espacios múltiples (`re.sub(r' +', ' ', message).strip()`).
- Transporte: SOAP sobre HTTP (Spyne con `WsgiApplication` + `wsgiref` o similar).
- Se despliega en `localhost:7789` (misma máquina que el cliente, puerto libre a elegir).
- El cliente llama a `normalize` **antes** de enviar el mensaje al servidor, en `send` y `sendAttach`.

**Servidor (`web_service.py`) — esquema con Spyne:**

```python
from spyne import Application, rpc, ServiceBase, Unicode
from spyne.protocol.soap import Soap11
from spyne.server.wsgi import WsgiApplication
from wsgiref.simple_server import make_server
import re

class NormalizeService(ServiceBase):
    @rpc(Unicode, _returns=Unicode)
    def normalize(ctx, message):
        return re.sub(r' +', ' ', message).strip()

application = Application(
    [NormalizeService],
    tns='ssdd.normalize',
    in_protocol=Soap11(validator='lxml'),
    out_protocol=Soap11()
)

if __name__ == '__main__':
    wsgi_app = WsgiApplication(application)
    server = make_server('0.0.0.0', 7789, wsgi_app)
    server.serve_forever()
```

**Integración en `client.py` — esquema:**

```python
from zeep import Client as ZeepClient

_wsdl = "http://localhost:7789/?wsdl"

def normalize(message):
    try:
        client = ZeepClient(_wsdl)
        return client.service.normalize(message)
    except Exception:
        return message  # fallback si el servicio no está disponible
```

---

### FASE 4 — Servicio RPC (C, ONC-RPC) · *[1 punto]*

#### Interfaz `log.x`

```c
/* log.x — Interfaz del servicio de log RPC */
program LOG_PROG {
    version LOG_VERS {
        int log_operation(string username<256>, string operation<256>) = 1;
    } = 1;
} = 0x20000001;
```

Generar stubs: `rpcgen -a log.x`

#### Servidor RPC (`rpc_server.c`)

- Implementar `log_operation_1_svc`: imprimir `<username>\t<operation>` por stdout.
- Para SENDATTACH, `operation` incluye el nombre del fichero: `"SENDATTACH /tmp/file.txt"`.

#### Integración en `server.c`

- Leer variable de entorno `LOG_RPC_IP` para localizar el servidor RPC.
- Llamar a `log_operation` tras recibir cada operación de un cliente.
- El servidor C es cliente del servicio RPC.

**Ejecución:**

```bash
export LOG_RPC_IP=<ip_servidor_rpc>
./server -p 8888
```

---

### FASE 5 — Transferencia de ficheros P2P (`SENDATTACH` + `GETFILE`) · *[2 puntos]*

> El servidor no interviene en la transferencia del contenido del fichero, pero sí actúa como intermediario para notificar la llegada del mensaje con fichero adjunto. Esta fase extiende tanto el **servidor** como el **cliente**.

#### Extensiones (`server.c`)

Añadir soporte para dos nuevas operaciones en el hilo manejador:

| Operación | Protocolo recibido | Respuesta | Log servidor |
| --- | --- | --- | --- |
| **SENDATTACH** | `"SENDATTACH"\0` · `<from>\0` · `<to>\0` · `<msg>\0` · `<file>\0` | 1 byte + `<id>\0` (si OK) | `s> SEND MESSAGE <id> FROM <s> TO <r>` / `STORED` |
| **USERS P2** | igual que USERS P1 | 1 byte + `<N>\0` + N·`<user>::<ip>::<port>\0` | `s> CONNECTEDUSERS OK/FAIL` |

- La lógica de SENDATTACH es idéntica a SEND, añadiendo el campo `filename` al mensaje almacenado.
- Al notificar al destinatario conectado, usar el protocolo `"SEND MESSAGE ATTACH\0"` (§2.3 del enunciado P2).
- Al notificar al remitente, usar `"SEND MESS ATTACH ACK\0"` + `id\0` + `file\0`.
- Modificar USERS para devolver `<user>::<ip>::<port>\0` por cada usuario conectado.

#### Flujo completo

Cliente A                    Servidor                    Cliente B
    │  SENDATTACH B msg file  │                               │
    │────────────────────────►│                               │
    │◄──────── 0 + id ────────│                               │
    │                         │── SEND MESSAGE ATTACH ───────►│
    │                         │   (from=A, id, msg, file)     │
    │◄─── SEND MESS ATTACH ACK│                               │
    │     (id, file)          │                               │
    │                         │                               │
    │          (más tarde, B quiere recuperar el fichero)     │
    │◄─────────────────── GET FILE ──────────────────────────►│
    │          (B abre conexión directa a A)                  │

#### Método `sendAttach(user, message, file)` en `client.py`

- Igual que `send` pero con paso adicional de enviar `<filename>\0`.
- Normalizar `message` con el servicio web antes de enviarlo.

#### Comando `GETFILE <userName> <fileName> <localFileName>`

1. Buscar `(ip, port)` de `<userName>` en `_connected_users`; si no está, hacer USERS primero.
2. Si sigue sin estar: imprimir `c> FILE TRANSFER FAILED, user not connected.`
3. Si está: conectar al hilo de escucha de ese usuario, enviar `"GET FILE\0"` + `"<self_user>\0"` + `"<fileName>\0"`, recibir contenido y escribirlo en `<localFileName>`.

---

### FASE 6 — Implementación y estructuración de las pruebas

> Las pruebas se organizan por componente y se ejecutan de forma incremental, verificando cada fase antes de avanzar a la siguiente. No se necesita framework de testing automatizado; las pruebas son manuales con terminales y comandos concretos.

---

#### Infraestructura de prueba

**Escenario mínimo (1 máquina / WSL):**

- Terminal 1: servidor (`./server -p 8888`)
- Terminal 2: cliente A (`python3 client.py -s localhost -p 8888`)
- Terminal 3: cliente B (`python3 client.py -s localhost -p 8888`)

**Escenario completo (Docker, obligatorio para la entrega):**

```bash
# Red Docker compartida
docker network create ssdd-net

# Contenedor servidor + RPC
docker run -it --name srv --network ssdd-net ssdd-image bash
# dentro: export LOG_RPC_IP=<ip_rpc>; ./server -p 8888

# Contenedor cliente A
docker run -it --name cliA --network ssdd-net ssdd-image bash
# dentro: python3 web_service.py &; python3 client.py -s srv -p 8888

# Contenedor cliente B (igual que A)
docker run -it --name cliB --network ssdd-net ssdd-image bash
```

---

#### Pruebas del servidor P1 (FASE 1) — con `netcat`

Antes de tener el cliente Python listo, verificar el protocolo directamente con `nc`:

```bash
# REGISTER "alice"
printf "REGISTER\0alice\0" | nc localhost 8888 | xxd
# Esperado: byte 0x00

# REGISTER "alice" de nuevo (duplicado)
printf "REGISTER\0alice\0" | nc localhost 8888 | xxd
# Esperado: byte 0x01

# UNREGISTER usuario inexistente
printf "UNREGISTER\0nobody\0" | nc localhost 8888 | xxd
# Esperado: byte 0x01
```

| # | Comando nc | Byte esperado | Log servidor esperado |
| --- | --- | --- | --- |
| 1 | REGISTER alice | `0x00` | `s> REGISTER alice OK` |
| 2 | REGISTER alice (2ª vez) | `0x01` | `s> REGISTER alice FAIL` |
| 3 | UNREGISTER alice | `0x00` | `s> UNREGISTER alice OK` |
| 4 | UNREGISTER nobody | `0x01` | `s> UNREGISTER nobody FAIL` |
| 5 | CONNECT sin registro previo | `0x01` | `s> CONNECT x FAIL` |

---

#### Pruebas de integración P1 — cliente + servidor

Ejecutar con dos terminales de cliente (A y B) apuntando al mismo servidor.

**Bloque — Registro y baja:**

[A] REGISTER alice        → c> REGISTER OK
[A] REGISTER alice        → c> USERNAME IN USE
[A] UNREGISTER bob        → c> USER DOES NOT EXIST
[A] UNREGISTER alice      → c> UNREGISTER OK

**Bloque — Conexión y desconexión:**

[A] REGISTER alice
[A] CONNECT alice         → c> CONNECT OK      | s> CONNECT alice OK
[A] CONNECT alice         → c> USER ALREADY CONNECTED
[A] DISCONNECT alice      → c> DISCONNECT OK   | s> DISCONNECT alice OK
[A] DISCONNECT alice      → c> DISCONNECT FAIL, USER NOT CONNECTED
[B] DISCONNECT bob        → c> DISCONNECT FAIL, USER DOES NOT EXIST

**Bloque — USERS:**

[A] REGISTER alice ; CONNECT alice
[B] REGISTER bob  ; CONNECT bob
[A] USERS  → c> CONNECTED USERS (2 users connected) OK\n  alice\n  bob
[A] DISCONNECT alice
[A] USERS  → c> CONNECTED USERS FAIL, USER IS NOT CONNECTED

**Bloque — SEND entre usuarios conectados:**

[A] REGISTER alice ; CONNECT alice
[B] REGISTER bob  ; CONNECT bob
[B] SEND alice hola
    → [B] c> SEND OK - MESSAGE 1
    → [A] s> MESSAGE 1 FROM bob\n  hola\n  END
    → [B] c> SEND MESSAGE 1 OK

**Bloque — SEND a usuario desconectado (mensajes encolados):**

[A] REGISTER alice   (sin CONNECT)
[B] REGISTER bob ; CONNECT bob
[B] SEND alice mensaje_pendiente
    → [B] c> SEND OK - MESSAGE 1   (almacenado en servidor)
[A] CONNECT alice
    → [A] s> MESSAGE 1 FROM bob\n  mensaje_pendiente\n  END   (entregado al conectarse)
    → [B] c> SEND MESSAGE 1 OK     (ACK al remitente)

**Bloque — SEND a usuario no registrado:**

[B] CONNECT bob
[B] SEND fantasma hola  → c> SEND FAIL, USER DOES NOT EXIST

**Bloque G — Servidor caído:**

Detener el servidor (Ctrl+C)

[A] REGISTER alice  → c> REGISTER FAIL

#### Pruebas del servicio web

```bash
# Arrancar el servicio SOAP
python3 web_service.py &

# Verificar que el WSDL es accesible
curl http://localhost:7789/?wsdl | grep normalize
# Esperado: aparece la operación "normalize" en el WSDL
```

```python
# Prueba directa con Zeep (script rápido)
from zeep import Client
c = Client("http://localhost:7789/?wsdl")
print(c.service.normalize("hola   mundo  como  estas"))
# Esperado: "hola mundo como estas"
print(c.service.normalize("  sin  trim  "))
# Esperado: "sin trim"
```

**Prueba integrada** — usar SEND con espacios múltiples y verificar que el receptor ve el mensaje normalizado (sin espacios repetidos).

---

#### Pruebas del servicio RPC

```bash
# Terminal 1: iniciar servidor RPC
./rpc_server

# Terminal 2: iniciar servidor de mensajería apuntando al RPC
export LOG_RPC_IP=localhost
./server -p 8888

# Terminal 3: cliente
python3 client.py -s localhost -p 8888
```

| Operación cliente | Salida esperada en servidor RPC |
| --- | --- |
| `REGISTER alice` | `alice    REGISTER` |
| `CONNECT alice` | `alice    CONNECT` |
| `SEND bob hola` | `alice    SEND` |
| `SENDATTACH bob hola /tmp/f.txt` | `alice    SENDATTACH /tmp/f.txt` |
| `DISCONNECT alice` | `alice    DISCONNECT` |
| `UNREGISTER alice` | `alice    UNREGISTER` |

**Prueba negativa:** arrancar `./server` sin `LOG_RPC_IP` definida — el servidor debe fallar con un mensaje claro o ignorar el RPC según la implementación elegida.

---

#### Pruebas de transferencia de ficheros

**Preparación:**

```bash
# Crear fichero de prueba en el lado del remitente
echo "contenido del fichero de prueba" > /tmp/datos.txt
```

**Flujo completo SENDATTACH + GETFILE:**

[A] REGISTER alice ; CONNECT alice
[B] REGISTER bob  ; CONNECT bob
[B] USERS    → bob ve alice::IP_A::PUERTO_A

[B] SENDATTACH alice mensaje_adjunto /tmp/datos.txt
    → [B] c> SENDATTACH OK - MESSAGE 1
    → [A] s> MESSAGE 1 FROM bob\n  mensaje_adjunto\n  END\n  FILE /tmp/datos.txt
    → [B] c> SENDATTACH MESSAGE 1 /tmp/datos.txt OK

[A] GETFILE bob /tmp/datos.txt /tmp/recibido.txt
    → [A] (silencioso o confirmación)
    → diff /tmp/datos.txt /tmp/recibido.txt   # sin diferencias

**Casos de error GETFILE:**

[A] GETFILE fantasma /tmp/f.txt /tmp/local.txt
    → c> FILE TRANSFER FAILED, user not connected.

Desconectar B y luego intentar GETFILE
[B] DISCONNECT bob
[A] GETFILE bob /tmp/datos.txt /tmp/local.txt
    → c> FILE TRANSFER FAILED, user not connected.

---

#### Pruebas de concurrencia y casos límite

**Concurrencia — múltiples clientes simultáneos:**

```bash
# Lanzar 5 clientes en paralelo y registrar al mismo tiempo
for i in 1 2 3 4 5; do
  python3 client.py -s localhost -p 8888 &
done
# Cada uno hace REGISTER userN; CONNECT userN; SEND a otro usuario
# Verificar
```

**Desbordamiento de id de mensaje:**

```python
# Script Python que simula el desbordamiento modificando last_msg_id
# directamente en el servidor (o enviando 2^32 - 1 mensajes en bucle en test)
# Verificar que el id tras 4294967295 vuelve a 1 (no 0)
```

**Límite de longitud de mensaje (255 caracteres útiles):**

[A→B] SEND bob <cadena de exactamente 255 chars>   → entregado correctamente
[A→B] SEND bob <cadena de 256+ chars>              → comportamiento definido (truncar o error)

**Desconexión forzada (cliente muere sin DISCONNECT):**

Matar el proceso cliente A (kill -9) estando conectado
Luego B intenta SEND a A → mensaje almacenado en servidor (estado marcado DISCONNECTED)
Verificar que el servidor detecta el error al intentar enviar y marca al cliente desconectado

**Reinicio del servidor con clientes activos:**

Mientras hay clientes conectados, Ctrl+C en el servidor
Volver a arrancar el servidor
Los clientes que intenten operar deben recibir FAIL (no hang indefinido)

---

#### Checklist de pruebas por fase

| Fase | Prueba superada | Observaciones |
| --- | --- | --- |
| F1 — Servidor P1 | [ ] nc REGISTER/UNREGISTER/CONNECT/DISCONNECT/SEND/USERS | Protocolo exacto |
| F2 — Cliente P1 | [ ] Bloques A–G de integración | Mensajes de consola exactos |
| F3 — Web service | [ ] curl normalize + integrado en send | Espacios múltiples eliminados |
| F4 — RPC | [ ] Log imprime todas las operaciones | Incluye SENDATTACH con filename |
| F5 — Ficheros | [ ] SENDATTACH + GETFILE + diff sin diferencias | P2P sin pasar por servidor |
| F5 — Ficheros error | [ ] FILE TRANSFER FAILED cuando usuario desconectado | — |
| F6 — Concurrencia | [ ] 5 clientes simultáneos sin crash ni pérdida de mensajes | — |
| F6 — Límites | [ ] id desbordamiento → vuelve a 1 | — |
| F6 — Caída cliente | [ ] Servidor marca DISCONNECTED al fallar envío | — |
| Docker | [ ] Todo funciona con IPs distintas en contenedores | Obligatorio para entrega |

---

## Protocolo de comunicación — Resumen

### Cliente → Servidor

| Operación | Secuencia de envío |
| --- | --- |
| REGISTER | `"REGISTER\0"` · `user\0` |
| UNREGISTER | `"UNREGISTER\0"` · `user\0` |
| CONNECT | `"CONNECT\0"` · `user\0` · `port\0` |
| DISCONNECT | `"DISCONNECT\0"` · `user\0` |
| SEND | `"SEND\0"` · `from\0` · `to\0` · `msg\0` |
| SENDATTACH | `"SENDATTACH\0"` · `from\0` · `to\0` · `msg\0` · `file\0` |
| USERS | `"USERS\0"` · `user\0` |

### Servidor → Cliente (hilo de escucha)

| Operación | Secuencia de envío |
| --- | --- |
| Entregar mensaje | `"SEND MESSAGE\0"` · `from\0` · `id\0` · `msg\0` |
| ACK de entrega | `"SEND MESS ACK\0"` · `id\0` |
| Entregar mensaje+fichero | `"SEND MESSAGE ATTACH\0"` · `from\0` · `id\0` · `msg\0` · `file\0` |
| ACK de entrega+fichero | `"SEND MESS ATTACH ACK\0"` · `id\0` · `file\0` |

### P2P entre clientes

| Operación | Iniciador | Secuencia |
| --- | --- | --- |
| GET FILE | Receptor del mensaje | `"GET FILE\0"` · `requester\0` · `filename\0` → recibe contenido del fichero |

---

## Gestión de concurrencia

### En `server.c`

- Un hilo por conexión entrante (`pthread_create` en el bucle `accept`).
- Mutex global `pthread_mutex_t users_mutex` protege lecturas/escrituras a la lista de usuarios.
- Al enviar mensajes pendientes en CONNECT: hacer dentro del mutex solo el acceso a datos, soltar el mutex antes de abrir el socket de envío para evitar deadlocks.

### En `client.py`

- Hilo principal: comandos del usuario y ejecuta operaciones hacia el servidor.
- `_listen_thread` (daemon): acepta conexiones del servidor y muestra mensajes recibidos.
- Usar `threading.Event` para detener el hilo de escucha en DISCONNECT/QUIT.

---

## Checklist

- [ ] `server.c` compila sin warnings (`gcc -Wall -Wextra -pthread`)
- [ ] `client.py` implementa todas las operaciones de P1
- [ ] Protocolo P1 exactamente respetado (cadenas `\0`, 1 byte de código)
- [ ] `sendAttach` y `GETFILE` funcionan (P2 — ficheros)
- [ ] `web_service.py` desplegado y llamado desde `client.py` (P2 — web)
- [ ] `log.x`, `rpc_server.c` compilados y servidor C los invoca vía `LOG_RPC_IP` (P2 — RPC)
- [ ] `Makefile` compila todo
- [ ] `README` con compilación y despliegue
- [ ] `autores.txt` con nombres y NIAs
- [ ] `memoria.pdf` (máx. 15 páginas)
- [ ] Todo funciona en contenedores Docker con IPs distintas /Guernika, prueba mabual
- [ ] Código comentado, de forma profesional, sin excederse

---
