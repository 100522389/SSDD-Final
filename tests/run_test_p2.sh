#!/usr/bin/env bash
# Ejecuta test_p2.py con el servidor y rpc_server activos.
set -e
PROJ="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJ"

make -C .. all 2>/dev/null

../rpc_server &
RPC_PID=$!
sleep 0.3

LOG_RPC_IP=localhost ../server -p 8888 &
SRV_PID=$!
sleep 0.5

source /tmp/ssdd_venv/bin/activate
python3 test_p2.py -s localhost -p 8888
RC=$?

kill "$SRV_PID" "$RPC_PID" 2>/dev/null || true
wait "$SRV_PID" "$RPC_PID" 2>/dev/null || true

exit $RC
