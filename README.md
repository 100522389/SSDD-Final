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

Escucha en el puerto **7789**. El **cliente Python** lo usa para normalizar los mensajes antes de enviarlos.

---

## Uso — Cliente interactivo

```bash
/tmp/ssdd_venv/bin/python3 client.py -s <servidor> -p <puerto>
```

Ejemplo local:

```bash
/tmp/ssdd_venv/bin/python3 client.py -s localhost -p 8888
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

Las pruebas automatizadas se encuentran en el directorio `tests/` y cubren **+90 casos de prueba** distribuidos en cinco suites. El script `tests/run_prev.sh` compila el proyecto, arranca y para todos los procesos necesarios, y ejecuta las cinco suites en secuencia.

| Suite | Fichero | Casos |
| --- | --- | --- |
| Integración Parte 1 | `test_integration_p1.py` | 28 |
| Integración Parte 2 | `test_p2.py` | 25 |
| Servicio web SOAP | `test_web_service.py` | 19 |
| Protocolo con netcat | `test_phase1.sh` | 11 |
| Servidor RPC de log | `test_rpc.sh` | 11 |

### Linux / WSL (recomendado)

```bash
bash tests/run_prev.sh
```

El script acepta 2 flags opcionales:

| Flag | Efecto |
| --- | --- |
| `--no-rpc` | Omite la suite `test_rpc.sh` (útil si `rpcbind` no está disponible) |
| `--no-web` | Omite las pruebas de integración del servicio web |

### Docker

```bash
docker compose up --build
```

El contenedor `cli` ejecuta `tests/run_docker_tests.sh`, que cubre las suites de integración P1, P2 y servicio web contra los contenedores `srv` y `rpc`.

### Descripción de las suites

**Integración - Parte 1** (`test_integration_p1.py`): valida los comandos — REGISTER, UNREGISTER, CONNECT, DISCONNECT, SEND y USERS — incluyendo códigos ante operaciones inválidas y la entrega de mensajes encolados.

**Integración - Parte 2** (`test_p2.py`): valida SENDATTACH con usuario conectado y con usuario desconectado (entrega diferida), el formato extendido de USERS (`usuario::IP::puerto`), GETFILE para transferencia P2P de ficheros, y el código de error de SENDATTACH ante usuario no registrado.

**Servicio web** (`test_web_service.py`): operación `normalize` del servicio web; incluye tanto pruebas unitarias de la función de normalización como pruebas de integración contra el servidor SOAP en ejecución.

**Protocolo con netcat** (`test_phase1.sh`): envía tramas binarias directamente mediante `nc` para verificar el manejo del protocolo a nivel de bytes — longitud de campos, operaciones, códigos de retorno y cierre de conexión.

**Servidor RPC de log** (`test_rpc.sh`): arranca `rpcbind` y `rpc_server`, ejecuta una secuencia de operaciones mediante el cliente Python y comprueba que el servidor RPC registra cada operación en el formato correcto (`usuario\tOPERACIÓN`), incluyendo REGISTER, CONNECT, SEND, SENDATTACH con nombre de fichero, USERS y DISCONNECT.

---

## Estructura

server.c          # Servidor central de mensajería (C, pthreads)
client.py         # Cliente interactivo (Python)
web_service.py    # Servicio SOAP de normalización (Spyne, puerto 7789)
rpc_server.c      # Servidor de log ONC-RPC
log.x             # Definición de interfaz RPC (rpcgen)
Makefile          # Compilación
run_prev.sh       # Script de suite de tests completa
