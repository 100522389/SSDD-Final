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
| `SENDATTACH <destinatario> <fichero> <mensaje>` | Envía un mensaje con fichero adjunto |
| `USERS` | Lista los usuarios conectados |
| `GETFILE <usuario> <fichero> <destino>` | Descarga un fichero de otro cliente (P2P) |
| `QUIT` | Sale del cliente |

Los mensajes dirigidos a un usuario desconectado se almacenan en el servidor y se entregan al reconectarse.

---

## Pruebas

- Completar

---

## Estructura

server.c          # Servidor central de mensajería (C, pthreads)
client.py         # Cliente interactivo (Python)
web_service.py    # Servicio SOAP de normalización (Spyne, puerto 7789)
rpc_server.c      # Servidor de log ONC-RPC
log.x             # Definición de interfaz RPC (rpcgen)
Makefile          # Compilación
run_prev.sh       # Script de suite de tests completa
