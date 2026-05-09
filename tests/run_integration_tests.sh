#!/usr/bin/env bash
# run_integration_tests.sh — Arranca el servidor y ejecuta las pruebas de integración P1

set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

# Matar instancias previas
pkill -f "server -p 8888" 2>/dev/null || true
sleep 0.3

# Arrancar servidor
../server -p 8888 > /tmp/srv_integration.log 2>&1 &
SRV_PID=$!
sleep 0.5

echo "Servidor arrancado (PID=$SRV_PID)"

# Ejecutar pruebas de integración
python3 test_integration_p1.py -s 127.0.0.1 -p 8888
TEST_RC=$?

echo ""
echo "=== Log del servidor ==="
cat /tmp/srv_integration.log

kill $SRV_PID 2>/dev/null || true

exit $TEST_RC
