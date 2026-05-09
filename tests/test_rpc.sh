#!/bin/bash
#
# test_rpc.sh  –  Tests de la Fase 4: servidor ONC-RPC de log
#
# Verifica que ./server llama a log_operation_1 en ./rpc_server por cada
# operación de los clientes.
#
# Uso:
#   bash test_rpc.sh
#
# Requisitos:
#   - rpcbind activo (sudo rpcbind)
#   - binarios server y rpc_server compilados (make all)
#   - python3 (para usar client.py)

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR" || exit 1
cd ..

PASS=0
FAIL=0
RPC_LOG="/tmp/rpc_test_output.log"
SERVER_LOG="/tmp/msg_server_rpc_test.log"
SERVER_PORT=9090

cleanup() {
    pkill -f "rpc_server" 2>/dev/null
    pkill -f "server -p $SERVER_PORT" 2>/dev/null
    sleep 0.3
}
trap cleanup EXIT

cleanup

# ─── Arrancar rpc_server ──────────────────────────────────────────────────────
./rpc_server > "$RPC_LOG" 2>&1 &
RPC_PID=$!
sleep 1

if ! kill -0 "$RPC_PID" 2>/dev/null; then
    echo "ERROR: rpc_server no arrancó (¿rpcbind activo?)"
    exit 1
fi
echo "rpc_server arrancado (PID=$RPC_PID)"

# ─── Arrancar servidor de mensajería con LOG_RPC_IP=localhost ─────────────────
export LOG_RPC_IP=localhost
./server -p $SERVER_PORT > "$SERVER_LOG" 2>&1 &
SERVER_PID=$!
sleep 1

if ! kill -0 "$SERVER_PID" 2>/dev/null; then
    echo "ERROR: server no arrancó"
    exit 1
fi
echo "server arrancado (PID=$SERVER_PID, puerto=$SERVER_PORT)"

# ─── Ejecutar operaciones con client.py ──────────────────────────────────────
python3 - <<PYEOF
import sys
sys.path.insert(0, '.')
from client import client

client._server = 'localhost'
client._port   = $SERVER_PORT

# Registrar usuarios
client.register('alice')
client.register('bob')

# Conectar alice → _username = 'alice'
# bob permanece desconectado para que los mensajes se encolen
client.connect('alice')

# SEND desde alice a bob  (from=alice queda en el log)
client.send('bob', 'hola bob')

# SENDATTACH desde alice a bob con fichero  → log: alice\tSENDATTACH /tmp/rpc_test_file.txt
# Firma: sendAttach(user, file, message)
client.sendAttach('bob', '/tmp/rpc_test_file.txt', 'adjunto rpc')

# USERS con alice conectada → log: alice\tUSERS
client.users()

# Desconectar alice
client.disconnect('alice')   # _username queda en None

# Conectar bob → _username = 'bob' → log: bob\tCONNECT
client.connect('bob')
client.disconnect('bob')     # log: bob\tDISCONNECT

# Dar de baja
client.unregister('alice')
client.unregister('bob')
PYEOF

sleep 1

# ─── Verificar output del rpc_server ─────────────────────────────────────────
echo ""
echo "=== Output del rpc_server ==="
cat "$RPC_LOG"
echo ""

check_line() {
    local desc="$1"
    local pattern="$2"
    if grep -qF "$pattern" "$RPC_LOG"; then
        echo "  [PASS] $desc"
        PASS=$((PASS+1))
    else
        echo "  [FAIL] $desc  (esperado: '$pattern')"
        FAIL=$((FAIL+1))
    fi
}

echo "=== Verificación de entradas de log ==="
check_line "REGISTER alice"            "alice	REGISTER"
check_line "REGISTER bob"              "bob	REGISTER"
check_line "CONNECT alice"             "alice	CONNECT"
check_line "CONNECT bob"               "bob	CONNECT"
check_line "SEND alice"                "alice	SEND"
check_line "SENDATTACH alice"          "alice	SENDATTACH"
check_line "SENDATTACH filename"       "/tmp/rpc_test_file.txt"
check_line "USERS alice"               "alice	USERS"
check_line "DISCONNECT alice"          "alice	DISCONNECT"
check_line "DISCONNECT bob"            "bob	DISCONNECT"
check_line "UNREGISTER alice"          "alice	UNREGISTER"
check_line "UNREGISTER bob"            "bob	UNREGISTER"

TOTAL=$((PASS+FAIL))
echo ""
echo "=== Resultado: $PASS PASS / $FAIL FAIL (de $TOTAL) ==="
[ "$FAIL" -eq 0 ]
