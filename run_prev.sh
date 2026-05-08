#!/usr/bin/env bash
# run_prev.sh — Compila, arranca rpc_server + server y ejecuta la suite completa:
#               test_integration_p1.py (20 tests P1/P2) + test_p2.py (24 tests P2)
set -e

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

# Compilar
make all 2>/dev/null

# Limpiar procesos previos
pkill -f "./rpc_server" 2>/dev/null || true
pkill -f "server -p 8888" 2>/dev/null || true
sleep 0.3

# Arrancar rpc_server
./rpc_server > /tmp/rpc_prev.log 2>&1 &
RPC_PID=$!
sleep 0.5

if ! kill -0 "$RPC_PID" 2>/dev/null; then
    echo "ERROR: rpc_server no arrancó"
    exit 1
fi
echo "rpc_server  PID=$RPC_PID"

# Arrancar servidor de mensajería con log RPC
LOG_RPC_IP=localhost ./server -p 8888 > /tmp/srv_prev.log 2>&1 &
SRV_PID=$!
sleep 0.5

if ! kill -0 "$SRV_PID" 2>/dev/null; then
    echo "ERROR: server no arrancó"
    kill "$RPC_PID" 2>/dev/null || true
    exit 1
fi
echo "server      PID=$SRV_PID"

# Tests P1/P2 (regresión)
echo ""
echo "=== test_integration_p1.py ==="
/tmp/ssdd_venv/bin/python3 test_integration_p1.py -s 127.0.0.1 -p 8888
P1_RC=$?

# Tests P2 (SENDATTACH / USERS P2 / GETFILE)
echo ""
echo "=== test_p2.py ==="
/tmp/ssdd_venv/bin/python3 test_p2.py -s localhost -p 8888
P2_RC=$?

# Limpiar
kill "$RPC_PID" "$SRV_PID" 2>/dev/null || true
wait "$RPC_PID" "$SRV_PID" 2>/dev/null || true

# Resumen final
echo ""
echo "=== Log RPC ==="
cat /tmp/rpc_prev.log

if [ "$P1_RC" -eq 0 ] && [ "$P2_RC" -eq 0 ]; then
    echo ""
    echo "=== TODOS LOS TESTS PASARON ==="
    exit 0
else
    echo ""
    echo "=== X (P1=$P1_RC P2=$P2_RC) ==="
    exit 1
fi
