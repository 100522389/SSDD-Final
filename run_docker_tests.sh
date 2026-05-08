#!/bin/bash
# run_docker_tests.sh — ejecuta todos los tests Python en el contenedor cli.
# Se conecta al servidor en ${SERVER_HOST}:${SERVER_PORT}.

SERVER="${SERVER_HOST:-srv}"
PORT="${SERVER_PORT:-8888}"

# Esperar a que el servidor de mensajería esté listo
echo "Esperando al servidor ${SERVER}:${PORT}..."
for i in $(seq 1 60); do
    nc -z "$SERVER" "$PORT" 2>/dev/null && break
    sleep 0.5
done
echo "Servidor listo."

# Arrancar el servicio web en background
python3 /app/web_service.py >/tmp/ws_docker.log 2>&1 &
WS_PID=$!
echo "Web service arrancado (PID=$WS_PID)"

# Esperar a que el servicio web esté disponible
for i in $(seq 1 20); do
    python3 -c \
        "import urllib.request; urllib.request.urlopen('http://localhost:7789/?wsdl', timeout=1)" \
        2>/dev/null && break
    sleep 0.5
done

# Ejecutar tests
PASS=0
FAIL=0
declare -a results

run_test() {
    local name="$1"; shift
    echo ""
    echo "=========================================="
    echo " $name"
    echo "=========================================="
    if "$@"; then
        results+=("  PASS: $name")
        PASS=$((PASS+1))
    else
        results+=("  FAIL: $name")
        FAIL=$((FAIL+1))
    fi
}

run_test "test_integration_p1.py" \
    python3 /app/test_integration_p1.py -s "$SERVER" -p "$PORT"

run_test "test_p2.py" \
    python3 /app/test_p2.py -s "$SERVER" -p "$PORT"

run_test "test_web_service.py" \
    python3 /app/test_web_service.py

# Detener el servicio web
kill $WS_PID 2>/dev/null || true

# Resumen
echo ""
echo "=========================================="
echo " RESUMEN FINAL (Docker)"
echo "=========================================="
for r in "${results[@]}"; do
    echo "$r"
done
echo ""
echo " Total: $PASS PASS / $FAIL FAIL"
echo "=========================================="
[ $FAIL -eq 0 ]
