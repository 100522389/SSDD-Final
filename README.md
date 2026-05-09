# Servicio distribuido de envío de mensajes

Sistema de mensajería distribuida con servidor central en C, cliente en Python, servicio SOAP de normalización y servidor de log ONC-RPC.

---

## Requisitos

- **WSL / Linux** con `gcc`, `make`, `rpcgen`, `rpcbind`
- **libtirpc-dev**: `sudo apt install libtirpc-dev`
- **Python 3.10+** con entorno virtual en `/tmp/ssdd_venv`

  ```bash
  python3 -m venv /tmp/ssdd_venv
  /tmp/ssdd_venv/bin/pip install -r requirements.txt
  ```

---

## Compilación

```bash
make all        # genera stubs RPC (rpcgen), compila server y rpc_server
make clean      # elimina binarios y ficheros generados
```

Los binarios resultantes son `server` y `rpc_server`.

---

## Despliegue

Arrancar los 3 procesos en el siguiente orden:

### 1. Servidor de log ONC-RPC

```bash
./rpc_server
```

Requiere que `rpcbind` esté activo:

```bash
sudo service rpcbind start   # o: sudo rpcbind
```

### 2. Servidor de mensajería

```bash
LOG_RPC_IP=<ip_rpc_server> ./server -p <puerto>
```

| Variable / argumento | Descripción |
| --- | --- |
| `-p <puerto>` | Puerto TCP en el que escucha (obligatorio) |
| `LOG_RPC_IP=<ip>` | IP del `rpc_server` para enviar logs. Si se omite, el log RPC queda desactivado |

Ejemplo local:

```bash
LOG_RPC_IP=localhost ./server -p 8888
```

### 3. Servicio web de normalización - SOAP

```bash
/tmp/ssdd_venv/bin/python3 web_service.py
```

Escucha en el puerto **7789**. El servidor de mensajería lo usa internamente para normalizar los mensajes.

---

## Uso — Cliente interactivo

```bash
/tmp/ssdd_venv/bin/python3 client.py
```

Comandos disponibles en el prompt `c>`:

| Comando | Descripción |
| --- | --- |
| `REGISTER <usuario>` | Registra un nuevo usuario |
| `UNREGISTER <usuario>` | Elimina el registro del usuario |
| `CONNECT <usuario>` | Conecta el usuario y activa la recepción de mensajes |
| `DISCONNECT <usuario>` | Desconecta el usuario |
| `SEND <destinatario> <mensaje>` | Envía un mensaje de texto |
| `SENDATTACH <destinatario> <mensaje> <fichero>` | Envía un mensaje con fichero adjunto |
| `USERS` | Lista los usuarios conectados |
| `GETFILE <usuario> <fichero> <destino>` | Descarga un fichero de otro cliente (P2P) |
| `QUIT` | Sale del cliente |

Los mensajes dirigidos a un usuario desconectado se almacenan en el servidor y se entregan al reconectarse.

---

## Pruebas

Las pruebas automatizadas se encuentran en el directorio `tests/`. Se puede ejecutar la suite completa con Docker o directamente en Linux.

### Docker

```bash
docker compose up --build
```

El contenedor `cli` ejecuta automáticamente:

- `test_integration_p1.py` — pruebas de integración Parte 1 (REGISTER, UNREGISTER, CONNECT, DISCONNECT, SEND, USERS, mensajes pendientes)
- `test_p2.py` — pruebas de la Parte 2 (SENDATTACH conectado y en cola, USERS con IP:puerto, GETFILE P2P)
- `test_web_service.py` — prueba unitaria de normalización

### Linux con servidor ya arrancado

```bash
# Terminal 1: servidor RPC
sudo rpcbind
./rpc_server

# Terminal 2: servidor de mensajería
LOG_RPC_IP=localhost ./server -p 8888

# Terminal 3: servicio web
python3 web_service.py

# Terminal 4: tests
python3 tests/test_integration_p1.py -s localhost -p 8888
python3 tests/test_p2.py            -s localhost -p 8888
python3 tests/test_web_service.py
```

### Casos de prueba

| Test | Qué verifica |
| --- | --- |
| REGISTER duplicado | Devuelve código 1 (usuario ya existe) |
| UNREGISTER usuario inexistente | Devuelve código 1 |
| CONNECT usuario inexistente | Devuelve código 1 |
| CONNECT ya conectado | Devuelve código 2 |
| DISCONNECT no conectado | Devuelve código 2 |
| SEND a usuario conectado | Entrega inmediata + ACK al remitente |
| SEND a usuario desconectado | Mensaje encolado + entrega al reconectarse |
| SENDATTACH a usuario conectado | Entrega con filename + ACK con filename |
| SENDATTACH a usuario desconectado | Encolado con filename + entrega al reconectarse |
| USERS formato P2 | Devuelve `user::IP::port` por cada conectado |
| GETFILE P2P | Transferencia correcta de contenido de fichero |
| Servicio web normalize | Elimina espacios múltiples |

---

## Estructura

server.c          # Servidor central de mensajería (C, pthreads)
client.py         # Cliente interactivo (Python)
web_service.py    # Servicio SOAP de normalización (Spyne, puerto 7789)
rpc_server.c      # Servidor de log ONC-RPC
log.x             # Definición de interfaz RPC (rpcgen)
Makefile          # Compilación
run_prev.sh       # Script de suite de tests completa
