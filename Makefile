# Makefile – Servicio de mensajería distribuida
# Sistemas Distribuidos – UC3M 2025-2026

CC      = gcc
CFLAGS  = -std=gnu99 -Wall -Wextra -pthread -I/usr/include/tirpc
LDFLAGS = -pthread -ltirpc

SERVER_TARGET  = server
SERVER_SRC     = server.c

RPC_IFACE      = log.x
RPC_TARGET     = rpc_server
RPC_GENERATED  = log_clnt.c log_svc.c log_xdr.c log.h
RPC_SRC        = rpc_server.c log_svc.c log_xdr.c
RPC_CLIENT_SRC = log_clnt.c log_xdr.c

.PHONY: all server rpc clean

all: server rpc

server: $(SERVER_SRC) $(RPC_GENERATED)
	$(CC) $(CFLAGS) -o $(SERVER_TARGET) $(SERVER_SRC) $(RPC_CLIENT_SRC) $(LDFLAGS)

rpc: $(RPC_GENERATED) $(RPC_SRC)
	$(CC) $(CFLAGS) -o $(RPC_TARGET) $(RPC_SRC) $(LDFLAGS)

# Genera los stubs RPC a partir de la interfaz XDR
$(RPC_GENERATED): $(RPC_IFACE)
	rpcgen -N $(RPC_IFACE)

clean:
	rm -f $(SERVER_TARGET) $(RPC_TARGET) $(RPC_GENERATED) *.o

