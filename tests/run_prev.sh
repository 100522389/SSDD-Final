#!/usr/bin/env bash
# run_prev.sh — Suite completa de pruebas
#
# Pasos:
#   1. Compila todos los binarios (make all).
#   2. test_phase1.sh   — protocolo P1 con netcat (requiere nc).
#   3. test_integration_p1.py — integración P1 (bloques 1-10).
#   4. test_p2.py       — integración P2 (SENDATTACH, USERS P2, GETFILE).
#   5. test_web_service.py unit — tests unitarios del servicio web (sin servidor SOAP).
#   6. test_web_service.py integración — arranca web_service.py, tests SOAP, lo para.
#   7. test_rpc.sh      — verifica log RPC (SKIP si rpcbind no está disponible).
#
# Uso:
#   bash run_prev.sh [--no-rpc] [--no-web]
#
# Variables de entorno opcionales:
#   PYTHON      — intérprete Python a usar (por defecto: python3 o el venv)
#   SERVER_PORT — puerto del servidor de mensajería (por defecto: 8888)

set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

# Intérprete Python
if [ -x /tmp/ssdd_venv/bin/python3 ]; then
    PYTHON=/tmp/ssdd_venv/bin/python3
else
    PYTHON=${PYTHON:-python3}
fi

SERVER_PORT=${SERVER_PORT:-8888}

# Flags opcionales
SKIP_RPC=0
SKIP_WEB=0
for arg in "$@"; do
    case "$arg" in
        --no-rpc) SKIP_RPC=1 ;;
        --no-web) SKIP_WEB=1 ;;
    esac
done

# Limpieza al salir
cleanup() {
    pkill -f "./rpc_server"        2>/dev/null || true
    pkill -f "server -p $SERVER_PORT" 2>/dev/null || true
    pkill -f "web_service.py"      2>/dev/null || true
    sleep 0.3
}
trap cleanup EXIT

cleanup

# Contadores globales
PHASE1_RC=0
INTEG_P1_RC=0
P2_RC=0
WEB_UNIT_RC=0
WEB_INTEG_RC=0
RPC_RC=0

# 1. Compilar
echo "=== Compilando ==="
make -C ..
echo ""

# 2. test_phase1.sh (netcat, protocolo P1)
echo "=== test_phase1.sh ==="
if command -v nc >/dev/null 2>&1; then
    bash test_phase1.sh || PHASE1_RC=$?
else
    echo "  SKIP — nc (netcat) no disponible"
fi
echo ""

# Arrancar rpc_server
RPC_PID=""
if [ "$SKIP_RPC" -eq 0 ] && command -v rpcbind >/dev/null 2>&1; then
    rpcbind 2>/dev/null || true
    sleep 0.3
    ../rpc_server > /tmp/rpc_prev.log 2>&1 &
    RPC_PID=$!
    sleep 0.8
    if ! kill -0 "$RPC_PID" 2>/dev/null; then
        echo "WARN: rpc_server no arrancó — se omiten tests RPC"
        RPC_PID=""
        SKIP_RPC=1
    else
        echo "rpc_server  PID=$RPC_PID"
    fi
else
    [ "$SKIP_RPC" -eq 0 ] && echo "WARN: rpcbind no disponible — se omiten tests RPC"
    SKIP_RPC=1
fi

# Arrancar servidor de mensajería
if [ -n "$RPC_PID" ]; then
    LOG_RPC_IP=localhost ../server -p "$SERVER_PORT" > /tmp/srv_prev.log 2>&1 &
else
    ../server -p "$SERVER_PORT" > /tmp/srv_prev.log 2>&1 &
fi
SRV_PID=$!
sleep 0.6

if ! kill -0 "$SRV_PID" 2>/dev/null; then
    echo "ERROR: server no arrancó — abortando"
    exit 1
fi
echo "server      PID=$SRV_PID (puerto=$SERVER_PORT)"
echo ""

# 3. test_integration_p1.py
echo "=== test_integration_p1.py ==="
"$PYTHON" test_integration_p1.py -s 127.0.0.1 -p "$SERVER_PORT" || INTEG_P1_RC=$?
echo ""

# 4. test_p2.py
echo "=== test_p2.py ==="
"$PYTHON" test_p2.py -s localhost -p "$SERVER_PORT" || P2_RC=$?
echo ""

# Detener servidor (ya no se necesita para los tests siguientes)
kill "$SRV_PID" 2>/dev/null || true
wait "$SRV_PID" 2>/dev/null || true
[ -n "$RPC_PID" ] && { kill "$RPC_PID" 2>/dev/null || true; wait "$RPC_PID" 2>/dev/null || true; }

# 5. test_web_service.py — unitarios (sin servidor SOAP)
if [ "$SKIP_WEB" -eq 0 ]; then
    echo "=== test_web_service.py (unit) ==="
    "$PYTHON" test_web_service.py unit || WEB_UNIT_RC=$?
    echo ""

    # 6. test_web_service.py — integración SOAP
    echo "=== test_web_service.py (integración SOAP) ==="
    "$PYTHON" ../web_service.py > /tmp/ws_prev.log 2>&1 &
    WS_PID=$!
    sleep 1.0
    if kill -0 "$WS_PID" 2>/dev/null; then
        "$PYTHON" test_web_service.py || WEB_INTEG_RC=$?
        kill "$WS_PID" 2>/dev/null || true
        wait "$WS_PID" 2>/dev/null || true
    else
        echo "  SKIP — web_service.py no arrancó"
    fi
    echo ""
else
    echo "  SKIP — tests web omitidos (--no-web)"
    echo ""
fi

# 7. test_rpc.sh
if [ "$SKIP_RPC" -eq 0 ]; then
    echo "=== test_rpc.sh ==="
    bash test_rpc.sh || RPC_RC=$?
    echo ""
else
    echo "  SKIP — tests RPC omitidos (rpcbind no disponible o --no-rpc)"
    echo ""
fi

# Resumen final
echo "================================================================="
echo " RESUMEN DE RESULTADOS"
echo "================================================================="
print_rc() {
    local label="$1" rc="$2" skip="$3"
    if [ "$skip" -eq 1 ]; then
        printf "  %-35s  SKIP\n" "$label"
    elif [ "$rc" -eq 0 ]; then
        printf "  %-35s  PASS\n" "$label"
    else
        printf "  %-35s  FAIL (rc=%d)\n" "$label" "$rc"
    fi
}

NC_SKIP=0; command -v nc >/dev/null 2>&1 || NC_SKIP=1
print_rc "test_phase1.sh (netcat)"           "$PHASE1_RC"    "$NC_SKIP"
print_rc "test_integration_p1.py"            "$INTEG_P1_RC"  0
print_rc "test_p2.py"                        "$P2_RC"        0
print_rc "test_web_service.py unit"          "$WEB_UNIT_RC"  "$SKIP_WEB"
print_rc "test_web_service.py integración"   "$WEB_INTEG_RC" "$SKIP_WEB"
print_rc "test_rpc.sh"                       "$RPC_RC"       "$SKIP_RPC"
echo "-----------------------------------------------------------------"

TOTAL_FAIL=$(( PHASE1_RC + INTEG_P1_RC + P2_RC + WEB_UNIT_RC + WEB_INTEG_RC + RPC_RC ))
if [ "$TOTAL_FAIL" -eq 0 ]; then
    echo " TODOS LOS TESTS PASARON (o SKIP)"
    exit 0
else
    echo " HAY FALLOS — revisar salida anterior"
    exit 1
fi
