# Makefile – Servicio de mensajería distribuida
# Sistemas Distribuidos – UC3M 2025-2026
#
# Uso:
#   make          → compila server y rpc_server
#   make server   → compila solo el servidor de mensajería
#   make rpc      → genera stubs RPC y compila rpc_server
#   make clean    → elimina binarios y ficheros generados

CC      = gcc
CFLAGS  = -std=gnu99 -Wall -Wextra -pthread
LDFLAGS = -pthread

# Servidor de mensajería (Parte 1)
SERVER_TARGET = server
SERVER_SRC    = server.c

# Servidor RPC de log (Parte 2)
RPC_IFACE     = log.x
RPC_TARGET    = rpc_server
# rpcgen genera: log_clnt.c  log_svc.c  log_xdr.c  log.h
RPC_GENERATED = log_clnt.c log_svc.c log_xdr.c log.h
RPC_SRC       = rpc_server.c log_svc.c log_xdr.c

# Reglas

.PHONY: all server rpc clean

all: server rpc

server: $(SERVER_SRC)
	$(CC) $(CFLAGS) -o $(SERVER_TARGET) $(SERVER_SRC) $(LDFLAGS)

rpc: $(RPC_GENERATED) $(RPC_SRC)
	$(CC) $(CFLAGS) -o $(RPC_TARGET) $(RPC_SRC)

# Generar stubs RPC a partir de la interfaz .x
$(RPC_GENERATED): $(RPC_IFACE)
	rpcgen -a $(RPC_IFACE)

clean:
	rm -f $(SERVER_TARGET) $(RPC_TARGET) $(RPC_GENERATED)
