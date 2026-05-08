#!/usr/bin/env bash
# test_phase1.sh — Pruebas del protocolo P1 con netcat

set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

# Arrancar servidor
./server -p 8888 > /tmp/srv.log 2>&1 &
SRV_PID=$!
sleep 0.5

pass=0
fail=0

check() {
    local desc="$1" expected="$2"
    local actual
    actual=$(eval "$3" 2>/dev/null | xxd -p | tr -d '\n')
    if [ "$actual" = "$expected" ]; then
        echo "  PASS: $desc"
        pass=$((pass+1))
    else
        echo "  FAIL: $desc — esperado=$expected obtenido=$actual"
        fail=$((fail+1))
    fi
}

echo ""
echo "=== Pruebas netcat — Protocolo P1 ==="

# 1. REGISTER alice → 0x00
check "REGISTER alice (OK)" "00" \
  "printf 'REGISTER\x00alice\x00' | nc -q1 localhost 8888"

# 2. REGISTER alice duplicado → 0x01
check "REGISTER alice duplicado (USERNAME IN USE)" "01" \
  "printf 'REGISTER\x00alice\x00' | nc -q1 localhost 8888"

# 3. REGISTER bob → 0x00
check "REGISTER bob (OK)" "00" \
  "printf 'REGISTER\x00bob\x00' | nc -q1 localhost 8888"

# 4. UNREGISTER nobody → 0x01
check "UNREGISTER nobody (USER DOES NOT EXIST)" "01" \
  "printf 'UNREGISTER\x00nobody\x00' | nc -q1 localhost 8888"

# 5. UNREGISTER alice → 0x00
check "UNREGISTER alice (OK)" "00" \
  "printf 'UNREGISTER\x00alice\x00' | nc -q1 localhost 8888"

# 6. CONNECT ghost (no registrado) → 0x01
check "CONNECT usuario no registrado (FAIL)" "01" \
  "printf 'CONNECT\x00ghost\x009999\x00' | nc -q1 localhost 8888"

# 7. CONNECT bob (registrado, desconectado) → 0x00
#    Primero abrir un puerto de escucha ficticio para el cliente
PORT=15001
nc -l -p $PORT > /dev/null 2>&1 &
NC_PID=$!
sleep 0.2
check "CONNECT bob (OK)" "00" \
  "printf 'CONNECT\x00bob\x00${PORT}\x00' | nc -q1 localhost 8888"

# 8. CONNECT bob de nuevo → 0x02
check "CONNECT bob ya conectado (USER ALREADY CONNECTED)" "02" \
  "printf 'CONNECT\x00bob\x00${PORT}\x00' | nc -q1 localhost 8888"

# 9. DISCONNECT bob → 0x00
check "DISCONNECT bob (OK)" "00" \
  "printf 'DISCONNECT\x00bob\x00' | nc -q1 localhost 8888"

# 10. DISCONNECT bob (ya desconectado) → 0x02
check "DISCONNECT bob ya desconectado (FAIL USER NOT CONNECTED)" "02" \
  "printf 'DISCONNECT\x00bob\x00' | nc -q1 localhost 8888"

# 11. DISCONNECT nobody → 0x01
check "DISCONNECT nobody (USER DOES NOT EXIST)" "01" \
  "printf 'DISCONNECT\x00nobody\x00' | nc -q1 localhost 8888"

kill $NC_PID 2>/dev/null || true

echo ""
echo "=== Log del servidor ==="
cat /tmp/srv.log

kill $SRV_PID 2>/dev/null || true

echo ""
echo "=== Resultado: $pass PASS / $fail FAIL ==="
[ $fail -eq 0 ]
