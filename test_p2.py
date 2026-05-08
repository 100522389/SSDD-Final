"""
test_p2.py – Tests de la Parte 2 (Fase 5): SENDATTACH, USERS P2, GETFILE.

Uso:
    python3 test_p2.py [-s <server>] [-p <port>]

Requiere:
    - ./server -p <port> en ejecución (por defecto puerto 8888).
    - /tmp/ssdd_venv activo (importa client.py del mismo directorio).
"""

import sys
import os
import argparse
import socket
import threading
import time
import tempfile

sys.path.insert(0, os.path.dirname(__file__))
from client import client

PASS = 0
FAIL = 0


def setup(server, port):
    client._server = server
    client._port   = port
    client._username = None
    client._listen_sock = None
    client._listen_thread = None
    client._connected_users = {}


def check(desc, condition):
    global PASS, FAIL
    if condition:
        print(f"  PASS: {desc}")
        PASS += 1
    else:
        print(f"  FAIL: {desc}")
        FAIL += 1


def recv_str_sock(s):
    buf = b''
    while True:
        c = s.recv(1)
        if not c or c == b'\0':
            return buf.decode()
        buf += c


def accept_one(srv_sock, timeout=5):
    """Acepta una conexión en srv_sock con timeout. Devuelve (conn, addr) o (None, None)."""
    srv_sock.settimeout(timeout)
    try:
        return srv_sock.accept()
    except Exception:
        return None, None


def make_listen_sock():
    """Crea un socket TCP de escucha en un puerto libre. Devuelve (sock, port)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(('', 0))
    port = s.getsockname()[1]
    s.listen(16)
    return s, port


def send_str_sock(s, text):
    s.sendall((text + '\0').encode())


# ── BLOQUE 1: SENDATTACH a usuario conectado ──────────────────────────────────

def test_sendattach_connected(server, port):
    print("\n=== Bloque 1: SENDATTACH a usuario conectado ===")
    setup(server, port)

    client.register('sa_alice')
    client.register('sa_bob')

    # Escucha manual para sa_alice (remitente) y sa_bob (destinatario)
    alice_sock, alice_port = make_listen_sock()
    bob_sock,   bob_port   = make_listen_sock()

    alice_msgs = []
    bob_msgs   = []

    def alice_listener():
        conn, _ = accept_one(alice_sock)
        if conn:
            op = recv_str_sock(conn)
            alice_msgs.append(op)
            if op == "SEND MESS ATTACH ACK":
                alice_msgs.append(recv_str_sock(conn))  # id
                alice_msgs.append(recv_str_sock(conn))  # filename
            conn.close()

    def bob_listener():
        conn, _ = accept_one(bob_sock)
        if conn:
            op = recv_str_sock(conn)
            bob_msgs.append(op)
            if op == "SEND MESSAGE ATTACH":
                bob_msgs.append(recv_str_sock(conn))  # sender
                bob_msgs.append(recv_str_sock(conn))  # id
                bob_msgs.append(recv_str_sock(conn))  # body
                bob_msgs.append(recv_str_sock(conn))  # filename
            conn.close()

    # Conectar alice
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.connect((server, port))
    send_str_sock(s, "CONNECT")
    send_str_sock(s, "sa_alice")
    send_str_sock(s, str(alice_port))
    rc = s.recv(1)[0]
    s.close()
    check("CONNECT sa_alice", rc == 0)

    # Conectar bob
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.connect((server, port))
    send_str_sock(s, "CONNECT")
    send_str_sock(s, "sa_bob")
    send_str_sock(s, str(bob_port))
    rc = s.recv(1)[0]
    s.close()
    check("CONNECT sa_bob", rc == 0)

    # Arrancar hilos de escucha antes de enviar
    t_alice = threading.Thread(target=alice_listener, daemon=True)
    t_bob   = threading.Thread(target=bob_listener,   daemon=True)
    t_alice.start()
    t_bob.start()

    # SENDATTACH desde sa_alice a sa_bob
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.connect((server, port))
    send_str_sock(s, "SENDATTACH")
    send_str_sock(s, "sa_alice")
    send_str_sock(s, "sa_bob")
    send_str_sock(s, "hola con fichero")
    send_str_sock(s, "/tmp/test_file.txt")
    code = s.recv(1)[0]
    msg_id = recv_str_sock(s) if code == 0 else None
    s.close()

    check("SENDATTACH código 0", code == 0)
    check("SENDATTACH devuelve id", msg_id is not None and msg_id != "")

    t_bob.join(timeout=5)
    t_alice.join(timeout=5)

    check("bob recibe SEND MESSAGE ATTACH",   bob_msgs and bob_msgs[0] == "SEND MESSAGE ATTACH")
    check("bob recibe sender correcto",        len(bob_msgs) > 1 and bob_msgs[1] == "sa_alice")
    check("bob recibe filename correcto",      len(bob_msgs) > 4 and bob_msgs[4] == "/tmp/test_file.txt")
    check("alice recibe SEND MESS ATTACH ACK", alice_msgs and alice_msgs[0] == "SEND MESS ATTACH ACK")
    check("alice recibe filename en ACK",      len(alice_msgs) > 2 and alice_msgs[2] == "/tmp/test_file.txt")

    alice_sock.close()
    bob_sock.close()
    client.disconnect('sa_alice')
    client.disconnect('sa_bob')
    client.unregister('sa_alice')
    client.unregister('sa_bob')


# ── BLOQUE 2: SENDATTACH a usuario desconectado (cola) ───────────────────────

def test_sendattach_queued(server, port):
    print("\n=== Bloque 2: SENDATTACH a usuario desconectado (cola) ===")
    setup(server, port)

    client.register('sq_alice')
    client.register('sq_bob')

    alice_sock, alice_port = make_listen_sock()
    bob_sock,   bob_port   = make_listen_sock()

    alice_msgs = []
    bob_msgs   = []

    def alice_listener():
        conn, _ = accept_one(alice_sock, timeout=6)
        if conn:
            op = recv_str_sock(conn)
            alice_msgs.append(op)
            if op == "SEND MESS ATTACH ACK":
                alice_msgs.append(recv_str_sock(conn))
                alice_msgs.append(recv_str_sock(conn))
            conn.close()

    def bob_listener():
        conn, _ = accept_one(bob_sock, timeout=6)
        if conn:
            op = recv_str_sock(conn)
            bob_msgs.append(op)
            if op == "SEND MESSAGE ATTACH":
                bob_msgs.append(recv_str_sock(conn))  # sender
                bob_msgs.append(recv_str_sock(conn))  # id
                bob_msgs.append(recv_str_sock(conn))  # body
                bob_msgs.append(recv_str_sock(conn))  # filename
            conn.close()

    # Conectar alice (remitente)
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.connect((server, port))
    send_str_sock(s, "CONNECT")
    send_str_sock(s, "sq_alice")
    send_str_sock(s, str(alice_port))
    s.recv(1)
    s.close()

    # sq_bob NO está conectado → SENDATTACH encola
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.connect((server, port))
    send_str_sock(s, "SENDATTACH")
    send_str_sock(s, "sq_alice")
    send_str_sock(s, "sq_bob")
    send_str_sock(s, "mensaje encolado")
    send_str_sock(s, "/tmp/queued_file.txt")
    code = s.recv(1)[0]
    msg_id = recv_str_sock(s) if code == 0 else None
    s.close()

    check("SENDATTACH a desconectado devuelve código 0", code == 0)

    # Arrancar hilos antes de conectar bob
    t_alice = threading.Thread(target=alice_listener, daemon=True)
    t_bob   = threading.Thread(target=bob_listener,   daemon=True)
    t_alice.start()
    t_bob.start()

    # Conectar bob → servidor entrega el mensaje pendiente
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.connect((server, port))
    send_str_sock(s, "CONNECT")
    send_str_sock(s, "sq_bob")
    send_str_sock(s, str(bob_port))
    rc = s.recv(1)[0]
    s.close()
    check("CONNECT sq_bob", rc == 0)

    t_bob.join(timeout=6)
    t_alice.join(timeout=6)

    check("bob recibe SEND MESSAGE ATTACH al conectarse",
          bob_msgs and bob_msgs[0] == "SEND MESSAGE ATTACH")
    check("bob recibe filename correcto",
          len(bob_msgs) > 4 and bob_msgs[4] == "/tmp/queued_file.txt")
    check("alice recibe ACK al entregar el encolado",
          alice_msgs and alice_msgs[0] == "SEND MESS ATTACH ACK")

    alice_sock.close()
    bob_sock.close()
    client.disconnect('sq_alice')
    client.disconnect('sq_bob')
    client.unregister('sq_alice')
    client.unregister('sq_bob')


# ── BLOQUE 3: USERS P2 — formato user::ip::port ───────────────────────────────

def test_users_p2(server, port):
    print("\n=== Bloque 3: USERS P2 (user::ip::port) ===")
    setup(server, port)

    client.register('up_alice')
    client.register('up_bob')

    alice_sock, alice_port = make_listen_sock()
    bob_sock,   bob_port   = make_listen_sock()

    # Conectar ambos directamente (sin usar client.connect para controlar puertos)
    for username, lport in [("up_alice", alice_port), ("up_bob", bob_port)]:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.connect((server, port))
        send_str_sock(s, "CONNECT")
        send_str_sock(s, username)
        send_str_sock(s, str(lport))
        s.recv(1)
        s.close()

    # Pedir USERS como up_alice
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.connect((server, port))
    send_str_sock(s, "USERS")
    send_str_sock(s, "up_alice")
    code = s.recv(1)[0]

    entries = []
    if code == 0:
        count = int(recv_str_sock(s))
        for _ in range(count):
            entries.append(recv_str_sock(s))
    s.close()

    check("USERS código 0", code == 0)
    check("USERS devuelve al menos 2 usuarios", len(entries) >= 2)

    # Verificar que todas las entradas tienen formato user::ip::port
    all_formatted = all(len(e.split("::")) == 3 for e in entries)
    check("Todas las entradas tienen formato user::ip::port", all_formatted)

    # Verificar que up_bob aparece con su puerto correcto
    bob_entry = next((e for e in entries if e.startswith("up_bob::")), None)
    check("up_bob aparece en USERS P2", bob_entry is not None)
    if bob_entry:
        parts = bob_entry.split("::")
        check("Puerto de up_bob es correcto", int(parts[2]) == bob_port)

    # Verificar que client.users() actualiza _connected_users
    client._username = "up_alice"
    client._listen_sock = alice_sock
    client.users()
    check("_connected_users contiene up_bob", "up_bob" in client._connected_users)
    if "up_bob" in client._connected_users:
        _, stored_port = client._connected_users["up_bob"]
        check("Puerto almacenado de up_bob es correcto", stored_port == bob_port)

    alice_sock.close()
    bob_sock.close()

    # Desconectar y dar de baja
    for username in ["up_alice", "up_bob"]:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.connect((server, port))
        send_str_sock(s, "DISCONNECT")
        send_str_sock(s, username)
        s.recv(1)
        s.close()
    client.unregister('up_alice')
    client.unregister('up_bob')
    client._username = None
    client._listen_sock = None


# ── BLOQUE 4: GETFILE — transferencia P2P ─────────────────────────────────────

def test_getfile(server, port):
    print("\n=== Bloque 4: GETFILE (transferencia P2P) ===")
    setup(server, port)

    client.register('gf_alice')
    client.register('gf_bob')

    # Crear fichero temporal que bob "posee"
    src_fd, src_path = tempfile.mkstemp(prefix="ssdd_test_")
    expected_content = b"contenido de prueba SSDD 12345\nlinea 2\n"
    os.write(src_fd, expected_content)
    os.close(src_fd)

    dst_fd, dst_path = tempfile.mkstemp(prefix="ssdd_recv_")
    os.close(dst_fd)

    # Conectar bob con client.connect (gestiona _listen_sock y _listener_loop)
    client.connect('gf_bob')
    bob_port = client._listen_port
    bob_ip   = server  # mismo host en tests locales

    # Alimentar _connected_users manualmente (simula haber hecho USERS P2)
    # (bob es quien tiene el fichero)
    client._connected_users['gf_bob'] = (bob_ip, bob_port)

    # Conectar alice
    alice_sock, alice_port = make_listen_sock()
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.connect((server, port))
    send_str_sock(s, "CONNECT")
    send_str_sock(s, "gf_alice")
    send_str_sock(s, str(alice_port))
    s.recv(1)
    s.close()
    client._username = "gf_alice"

    # Ejecutar GETFILE: alice pide a bob el fichero src_path → guardarlo en dst_path
    rc = client.getFile('gf_bob', src_path, dst_path)
    check("GETFILE devuelve OK", rc == client.RC.OK)

    try:
        with open(dst_path, 'rb') as f:
            received = f.read()
        check("Contenido del fichero recibido es correcto", received == expected_content)
    except Exception:
        check("Contenido del fichero recibido es correcto", False)

    # Limpieza
    os.unlink(src_path)
    try:
        os.unlink(dst_path)
    except Exception:
        pass

    alice_sock.close()
    client.disconnect('gf_bob')
    client.disconnect('gf_alice')
    client.unregister('gf_alice')
    client.unregister('gf_bob')
    client._username = None
    client._listen_sock = None


# ── BLOQUE 5: GETFILE — usuario no conectado ──────────────────────────────────

def test_getfile_not_connected(server, port):
    print("\n=== Bloque 5: GETFILE con usuario no conectado ===")
    setup(server, port)

    client.register('gfn_alice')

    alice_sock, alice_port = make_listen_sock()
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.connect((server, port))
    send_str_sock(s, "CONNECT")
    send_str_sock(s, "gfn_alice")
    send_str_sock(s, str(alice_port))
    s.recv(1)
    s.close()
    client._username = "gfn_alice"

    # Pedir fichero a usuario que no está conectado ni en _connected_users
    # (USERS devolverá la lista real del servidor, que tampoco lo tendrá)
    rc = client.getFile('nobody_user', '/tmp/no_such_file.txt', '/tmp/output.txt')
    check("GETFILE con usuario no conectado devuelve ERROR", rc == client.RC.ERROR)

    alice_sock.close()
    client.disconnect('gfn_alice')
    client.unregister('gfn_alice')
    client._username = None
    client._listen_sock = None


# ── Main ──────────────────────────────────────────────────────────────────────

def run_tests(server, port):
    test_sendattach_connected(server, port)
    test_sendattach_queued(server, port)
    test_users_p2(server, port)
    test_getfile(server, port)
    test_getfile_not_connected(server, port)

    print(f"\n=== Resultado: {PASS} PASS / {FAIL} FAIL ===")
    return FAIL == 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("-s", default="localhost")
    parser.add_argument("-p", type=int, default=8888)
    args = parser.parse_args()
    ok = run_tests(args.s, args.p)
    sys.exit(0 if ok else 1)
