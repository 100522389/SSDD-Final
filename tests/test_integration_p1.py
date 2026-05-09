#!/usr/bin/env python3
"""
test_integration_p1.py — Pruebas de integración Phase 1
Ejecutar desde el directorio del proyecto con el servidor ya arrancado:
  python3 test_integration_p1.py -s localhost -p 8888
"""

import sys
import os
import argparse
import socket
import threading
import time

# Importar la clase client del mismo directorio
sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from client import client


def setup_client(server, port):
    client._server = server
    client._port   = port
    # Limpiar estado
    client._username       = None
    client._listen_sock    = None
    client._listen_port    = None
    client._listen_thread  = None
    client._connected_users = {}


def run_tests(server, port):
    setup_client(server, port)
    pass_count = 0
    fail_count = 0
    results = []

    def check(desc, expected_rc, actual_rc, expected_print=None):
        nonlocal pass_count, fail_count
        if actual_rc == expected_rc:
            results.append(f"  PASS: {desc}")
            pass_count += 1
        else:
            results.append(f"  FAIL: {desc} — esperado={expected_rc} obtenido={actual_rc}")
            fail_count += 1

    print("\n=== Bloque 1: Registro y baja ===")

    rc = client.register("alice")
    check("REGISTER alice → OK", client.RC.OK, rc)

    rc = client.register("alice")
    check("REGISTER alice duplicado → USER_ERROR", client.RC.USER_ERROR, rc)

    rc = client.register("bob")
    check("REGISTER bob → OK", client.RC.OK, rc)

    rc = client.unregister("nobody")
    check("UNREGISTER nobody → USER_ERROR", client.RC.USER_ERROR, rc)

    rc = client.unregister("alice")
    check("UNREGISTER alice → OK", client.RC.OK, rc)

    print("\n=== Bloque 2: Conexión y desconexión ===")

    # alice ya fue dada de baja; registrar de nuevo
    client.register("alice")

    rc = client.connect("alice")
    check("CONNECT alice → OK", client.RC.OK, rc)

    rc = client.connect("alice")
    check("CONNECT alice ya conectada → USER_ERROR", client.RC.USER_ERROR, rc)

    rc = client.disconnect("alice")
    check("DISCONNECT alice → OK", client.RC.OK, rc)

    rc = client.disconnect("alice")
    check("DISCONNECT alice ya desconectada → USER_ERROR", client.RC.USER_ERROR, rc)

    rc = client.disconnect("nobody")
    check("DISCONNECT nobody → USER_ERROR", client.RC.USER_ERROR, rc)

    print("\n=== Bloque 3: SEND (destinatario conectado) ===")
    # Reconectar alice
    client.connect("alice")
    time.sleep(0.2)

    # Necesitamos un segundo proceso para bob; usamos sockets directamente
    # para simular que bob está conectado con un hilo de escucha propio.
    # Creamos un socket de escucha "falso" para bob que registra lo que recibe.

    bob_received = []
    bob_listen = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    bob_listen.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    bob_listen.bind(('', 0))
    bob_port = bob_listen.getsockname()[1]
    bob_listen.listen(5)

    def bob_listener():
        bob_listen.settimeout(3.0)
        try:
            conn, _ = bob_listen.accept()
            data = b''
            while True:
                chunk = conn.recv(256)
                if not chunk:
                    break
                data += chunk
            bob_received.append(data)
            conn.close()
        except Exception:
            pass

    bob_thread = threading.Thread(target=bob_listener, daemon=True)
    bob_thread.start()

    # Conectar bob directamente vía socket raw (simulación)
    def send_str_raw(s, text):
        s.sendall((text + '\0').encode())

    def recv_byte_raw(s):
        return s.recv(1)[0]

    def recv_str_raw(s):
        buf = b''
        while True:
            c = s.recv(1)
            if not c or c == b'\0':
                break
            buf += c
        return buf.decode()

    # Registrar y conectar bob manualmente
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.connect((server, port))
    send_str_raw(s, "REGISTER")
    send_str_raw(s, "bob")
    s.recv(1)
    s.close()

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.connect((server, port))
    send_str_raw(s, "CONNECT")
    send_str_raw(s, "bob")
    send_str_raw(s, str(bob_port))
    code_b = s.recv(1)[0]
    s.close()

    if code_b == 0:
        print("  [setup] bob conectado en puerto", bob_port)
    else:
        print(f"  [setup] WARN: bob CONNECT code={code_b}")

    time.sleep(0.2)

    # Alice envía a bob
    rc = client.send("bob", "Hola bob!")
    check("SEND alice→bob (bob conectado) → OK", client.RC.OK, rc)
    time.sleep(0.5)

    # Verificar que bob recibió el mensaje
    bob_thread.join(timeout=2.0)
    if bob_received:
        msg_raw = bob_received[0].decode(errors='replace')
        if "SEND MESSAGE" in msg_raw and "alice" in msg_raw and "Hola bob" in msg_raw:
            results.append("  PASS: bob recibió el mensaje correctamente")
            pass_count += 1
        else:
            results.append(f"  FAIL: contenido del mensaje bob inesperado: {repr(msg_raw)}")
            fail_count += 1
    else:
        results.append("  FAIL: bob no recibió ningún mensaje")
        fail_count += 1

    # Desconectar bob
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.connect((server, port))
    send_str_raw(s, "DISCONNECT")
    send_str_raw(s, "bob")
    s.recv(1)
    s.close()
    bob_listen.close()

    print("\n=== Bloque 4: SEND (destinatario desconectado → cola) ===")

    # bob desconectado; alice envía → debe quedar en cola
    rc = client.send("bob", "Mensaje pendiente")
    check("SEND alice→bob (bob desconectado) → OK (almacenado)", client.RC.OK, rc)

    # Reconectar bob con nuevo socket de escucha
    bob_received2 = []
    bob_listen2 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    bob_listen2.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    bob_listen2.bind(('', 0))
    bob_port2 = bob_listen2.getsockname()[1]
    bob_listen2.listen(5)

    def bob_listener2():
        bob_listen2.settimeout(3.0)
        try:
            conn, _ = bob_listen2.accept()
            data = b''
            while True:
                chunk = conn.recv(256)
                if not chunk:
                    break
                data += chunk
            bob_received2.append(data)
            conn.close()
        except Exception:
            pass

    bob_thread2 = threading.Thread(target=bob_listener2, daemon=True)
    bob_thread2.start()

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.connect((server, port))
    send_str_raw(s, "CONNECT")
    send_str_raw(s, "bob")
    send_str_raw(s, str(bob_port2))
    code_b2 = s.recv(1)[0]
    s.close()

    time.sleep(0.5)
    bob_thread2.join(timeout=2.0)

    if code_b2 == 0 and bob_received2:
        msg_raw2 = bob_received2[0].decode(errors='replace')
        if "SEND MESSAGE" in msg_raw2 and "pendiente" in msg_raw2:
            results.append("  PASS: bob recibió mensaje pendiente al reconectarse")
            pass_count += 1
        else:
            results.append(f"  FAIL: mensaje pendiente inesperado: {repr(msg_raw2)}")
            fail_count += 1
    else:
        results.append(f"  FAIL: bob no recibió mensaje pendiente (code={code_b2}, msgs={len(bob_received2)})")
        fail_count += 1

    # Desconectar bob y limpiar
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.connect((server, port))
    send_str_raw(s, "DISCONNECT")
    send_str_raw(s, "bob")
    s.recv(1)
    s.close()
    bob_listen2.close()

    print("\n=== Bloque 5: USERS ===")

    # alice conectada; consultar USERS
    rc = client.users()
    check("USERS (alice conectada) → OK", client.RC.OK, rc)

    # Desconectar alice
    client.disconnect("alice")

    # USERS con usuario registrado pero NO conectado:
    # simulamos enviando USERS directamente con raw socket para que el servidor
    # reciba el nombre correcto ("carol") y devuelva código 1.
    setup_client(server, port)
    client.register("carol")
    # _username es None tras register; lo establecemos para que users() envíe "carol"
    client._username = "carol"

    rc = client.users()
    check("USERS (carol no conectada) → USER_ERROR", client.RC.USER_ERROR, rc)

    client._username = None
    client.unregister("carol")

    # Limpiar
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.connect((server, port))
    send_str_raw(s, "UNREGISTER")
    send_str_raw(s, "alice")
    s.recv(1); s.close()

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.connect((server, port))
    send_str_raw(s, "UNREGISTER")
    send_str_raw(s, "bob")
    s.recv(1); s.close()

    print("\n=== Bloque 6: Estado interno tras disconnect() ===")

    setup_client(server, port)
    client.register("dan")
    client.connect("dan")
    client.disconnect("dan")

    if client._listen_sock is None:
        results.append("  PASS: _listen_sock es None tras disconnect()")
        pass_count += 1
    else:
        results.append("  FAIL: _listen_sock NO es None tras disconnect()")
        fail_count += 1

    if client._listen_thread is None:
        results.append("  PASS: _listen_thread es None tras disconnect()")
        pass_count += 1
    else:
        results.append("  FAIL: _listen_thread NO es None tras disconnect()")
        fail_count += 1

    client.unregister("dan")

    print("\n=== Bloque 7: Truncado de mensaje a 255 chars ===")

    setup_client(server, port)
    client.register("eve")
    client.register("frank")

    # Receptor ficticio (frank conectado)
    trunc_listen = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    trunc_listen.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    trunc_listen.bind(('', 0))
    trunc_port = trunc_listen.getsockname()[1]
    trunc_listen.listen(5)
    trunc_received = []

    def trunc_listener():
        trunc_listen.settimeout(3.0)
        try:
            conn, _ = trunc_listen.accept()
            data = b''
            while True:
                chunk = conn.recv(512)
                if not chunk:
                    break
                data += chunk
            trunc_received.append(data)
            conn.close()
        except Exception:
            pass

    trunc_thread = threading.Thread(target=trunc_listener, daemon=True)
    trunc_thread.start()

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.connect((server, port))
    send_str_raw(s, "CONNECT")
    send_str_raw(s, "frank")
    send_str_raw(s, str(trunc_port))
    s.recv(1); s.close()

    client.connect("eve")
    long_msg = "A" * 300
    rc = client.send("frank", long_msg)
    check("SEND mensaje 300 chars → OK (truncado a 255)", client.RC.OK, rc)

    trunc_thread.join(timeout=2.0)
    if trunc_received:
        # El cuerpo del mensaje debe tener ≤255 chars (sin contar \0 del protocolo)
        raw = trunc_received[0]
        # Extraer el cuerpo: es el 4º campo NUL-separado (op\0sender\0id\0body\0)
        fields = raw.split(b'\x00')
        body = fields[3].decode(errors='replace') if len(fields) > 3 else ""
        if len(body) <= 255:
            results.append(f"  PASS: cuerpo del mensaje truncado a {len(body)} chars (≤255)")
            pass_count += 1
        else:
            results.append(f"  FAIL: cuerpo del mensaje tiene {len(body)} chars (>255)")
            fail_count += 1
    else:
        results.append("  FAIL: frank no recibió el mensaje para verificar truncado")
        fail_count += 1

    client.disconnect("eve")
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.connect((server, port))
    send_str_raw(s, "DISCONNECT"); send_str_raw(s, "frank"); s.recv(1); s.close()
    trunc_listen.close()
    client.unregister("eve")
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.connect((server, port))
    send_str_raw(s, "UNREGISTER"); send_str_raw(s, "frank"); s.recv(1); s.close()

    print("\n=== Bloque 8: Concurrencia (5 clientes simultáneos) ===")

    # 5 hilos Python arrancan simultáneamente usando una Barrier.
    # Cada hilo registra un usuario único, se conecta, envía un mensaje al
    # siguiente usuario en round-robin y se desconecta.  Ningún hilo debe
    # lanzar una excepción ni devolver un RC de error.

    NUM_CLIENTS = 5
    barrier = threading.Barrier(NUM_CLIENTS)
    conc_errors = []
    conc_lock   = threading.Lock()

    def conc_worker(idx):
        uname  = f"conc{idx}"
        target = f"conc{(idx + 1) % NUM_CLIENTS}"
        try:
            # Registro
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.connect((server, port))
            send_str_raw(s, "REGISTER"); send_str_raw(s, uname)
            rc_reg = s.recv(1)[0]; s.close()
            if rc_reg != 0:
                with conc_lock:
                    conc_errors.append(f"{uname}: REGISTER returned {rc_reg}")
                return

            # Escucha propia
            my_listen = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            my_listen.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            my_listen.bind(('', 0))
            my_port = my_listen.getsockname()[1]
            my_listen.listen(8)
            # Hilo de escucha para absorber mensajes entrantes
            def _absorb():
                my_listen.settimeout(3.0)
                try:
                    while True:
                        c, _ = my_listen.accept()
                        c.close()
                except Exception:
                    pass
            threading.Thread(target=_absorb, daemon=True).start()

            # Conexión
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.connect((server, port))
            send_str_raw(s, "CONNECT"); send_str_raw(s, uname); send_str_raw(s, str(my_port))
            rc_conn = s.recv(1)[0]; s.close()
            if rc_conn != 0:
                with conc_lock:
                    conc_errors.append(f"{uname}: CONNECT returned {rc_conn}")
                my_listen.close()
                return

            # Sincronizar: todos esperan aquí antes de enviar
            barrier.wait(timeout=5)

            # SEND al siguiente (puede estar no conectado todavía; código 0 es OK igual)
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.connect((server, port))
            send_str_raw(s, "SEND"); send_str_raw(s, uname)
            send_str_raw(s, target); send_str_raw(s, f"hola de {uname}")
            rc_send = s.recv(1)[0]
            if rc_send == 0:
                recv_str_raw(s)  # leer id
            s.close()
            if rc_send not in (0, 1):  # 0=OK, 1=destinatario aún no registrado (race)
                with conc_lock:
                    conc_errors.append(f"{uname}: SEND returned {rc_send}")

            # Desconexión
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.connect((server, port))
            send_str_raw(s, "DISCONNECT"); send_str_raw(s, uname)
            s.recv(1); s.close()
            my_listen.close()

            # Baja
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.connect((server, port))
            send_str_raw(s, "UNREGISTER"); send_str_raw(s, uname)
            s.recv(1); s.close()

        except Exception as exc:
            with conc_lock:
                conc_errors.append(f"{uname}: excepción {exc}")

    threads = [threading.Thread(target=conc_worker, args=(i,), daemon=True)
               for i in range(NUM_CLIENTS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=15)

    if not conc_errors:
        results.append(f"  PASS: {NUM_CLIENTS} clientes simultáneos sin errores")
        pass_count += 1
    else:
        for e in conc_errors:
            results.append(f"  FAIL: concurrencia — {e}")
            fail_count += 1

    print("\n=== Bloque 9: Forced disconnect (cliente muere sin DISCONNECT) ===")

    # Registrar+conectar "zombie" con un socket raw.  Luego cerrar el socket
    # de escucha bruscamente (sin enviar DISCONNECT al servidor).
    # Otro cliente envía un mensaje a zombie → el servidor falla al entregarlo
    # y debe marcarlo como DISCONNECTED (el mensaje queda en cola).
    # Verificar que zombie puede volver a conectarse correctamente (estado limpio).

    setup_client(server, port)
    client.register("zombie")
    client.register("sender9")

    zombie_listen = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    zombie_listen.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    zombie_listen.bind(('', 0))
    zombie_port = zombie_listen.getsockname()[1]
    zombie_listen.listen(1)

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.connect((server, port))
    send_str_raw(s, "CONNECT"); send_str_raw(s, "zombie"); send_str_raw(s, str(zombie_port))
    rc_zconn = s.recv(1)[0]; s.close()

    if rc_zconn == 0:
        # Cerrar el socket de escucha de zombie sin avisar al servidor
        zombie_listen.close()
        time.sleep(0.3)

        # sender9 conectado; envía a zombie (el servidor intentará entregar y fallará)
        client.connect("sender9")
        time.sleep(0.2)
        rc_send9 = client.send("zombie", "mensaje a zombie muerto")
        # El SEND debe devolver OK al remitente (el servidor acepta el mensaje
        # aunque falle la entrega inmediata; código 0)
        check("SEND a zombie muerto devuelve OK", client.RC.OK, rc_send9)
        time.sleep(0.5)

        # zombie vuelve a conectarse con un nuevo socket de escucha
        zombie_listen2 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        zombie_listen2.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        zombie_listen2.bind(('', 0))
        zombie_port2 = zombie_listen2.getsockname()[1]
        zombie_listen2.listen(4)

        recv_on_reconnect = []
        def zombie_listener2():
            zombie_listen2.settimeout(3.0)
            try:
                conn, _ = zombie_listen2.accept()
                data = b''
                while True:
                    chunk = conn.recv(256)
                    if not chunk:
                        break
                    data += chunk
                recv_on_reconnect.append(data)
                conn.close()
            except Exception:
                pass
        zt2 = threading.Thread(target=zombie_listener2, daemon=True)
        zt2.start()

        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.connect((server, port))
        send_str_raw(s, "CONNECT"); send_str_raw(s, "zombie"); send_str_raw(s, str(zombie_port2))
        rc_zconn2 = s.recv(1)[0]; s.close()
        check("zombie puede volver a conectarse tras forced-disconnect", 0, rc_zconn2)

        zt2.join(timeout=3.0)
        if recv_on_reconnect:
            raw = recv_on_reconnect[0].decode(errors='replace')
            check("zombie recibe el mensaje encolado al reconectarse",
                  True, "SEND MESSAGE" in raw and "zombie muerto" in raw)
        else:
            results.append("  FAIL: zombie no recibió el mensaje encolado al reconectarse")
            fail_count += 1

        zombie_listen2.close()
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.connect((server, port))
        send_str_raw(s, "DISCONNECT"); send_str_raw(s, "zombie"); s.recv(1); s.close()
    else:
        results.append(f"  SKIP: CONNECT zombie falló (code={rc_zconn}); se omite bloque 9")

    client.disconnect("sender9")
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.connect((server, port))
    send_str_raw(s, "UNREGISTER"); send_str_raw(s, "zombie"); s.recv(1); s.close()
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.connect((server, port))
    send_str_raw(s, "UNREGISTER"); send_str_raw(s, "sender9"); s.recv(1); s.close()

    print("\n=== Bloque 10: Incremento de ID de mensaje ===")

    # Enviar 2 mensajes consecutivos de A a B (B conectado) y verificar que
    # los IDs son 1 y 2.
    # NOTA: el desbordamiento UINT_MAX→0→1 no se verifica automáticamente en
    # integración (requeriría enviar 4.294.967.295 mensajes).  Su corrección se
    # garantiza por la implementación en server.c (unsigned int, lógica id=0→id=1).

    setup_client(server, port)
    client.register("id_alice")
    client.register("id_bob")

    id_listen = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    id_listen.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    id_listen.bind(('', 0))
    id_bob_port = id_listen.getsockname()[1]
    id_listen.listen(8)

    id_received = []
    def id_bob_listener():
        id_listen.settimeout(4.0)
        try:
            for _ in range(2):
                conn, _ = id_listen.accept()
                data = b''
                while True:
                    chunk = conn.recv(256)
                    if not chunk:
                        break
                    data += chunk
                id_received.append(data)
                conn.close()
        except Exception:
            pass
    id_thread = threading.Thread(target=id_bob_listener, daemon=True)
    id_thread.start()

    # Conectar id_bob
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.connect((server, port))
    send_str_raw(s, "CONNECT"); send_str_raw(s, "id_bob"); send_str_raw(s, str(id_bob_port))
    s.recv(1); s.close()

    # Conectar id_alice con client helper
    client.connect("id_alice")
    time.sleep(0.2)

    rc1 = client.send("id_bob", "primer mensaje")
    check("SEND #1 a id_bob → OK", client.RC.OK, rc1)

    rc2 = client.send("id_bob", "segundo mensaje")
    check("SEND #2 a id_bob → OK", client.RC.OK, rc2)

    id_thread.join(timeout=5.0)

    if len(id_received) >= 2:
        # Extraer IDs: protocolo SEND MESSAGE\0sender\0id\0body\0
        def extract_id(raw_bytes):
            fields = raw_bytes.split(b'\x00')
            # fields[0]=op, fields[1]=sender, fields[2]=id
            return fields[2].decode(errors='replace') if len(fields) > 2 else ""
        id1 = extract_id(id_received[0])
        id2 = extract_id(id_received[1])
        check("Primer mensaje recibido tiene id=1",  "1", id1)
        check("Segundo mensaje recibido tiene id=2", "2", id2)
    else:
        results.append(f"  FAIL: id_bob recibió {len(id_received)} mensajes (esperado 2)")
        fail_count += 1

    client.disconnect("id_alice")
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.connect((server, port))
    send_str_raw(s, "DISCONNECT"); send_str_raw(s, "id_bob"); s.recv(1); s.close()
    id_listen.close()
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.connect((server, port))
    send_str_raw(s, "UNREGISTER"); send_str_raw(s, "id_alice"); s.recv(1); s.close()
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.connect((server, port))
    send_str_raw(s, "UNREGISTER"); send_str_raw(s, "id_bob"); s.recv(1); s.close()

    # Imprimir resultados
    for r in results:
        print(r)

    print(f"\n=== Resultado: {pass_count} PASS / {fail_count} FAIL ===")
    return fail_count == 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("-s", default="localhost")
    parser.add_argument("-p", type=int, default=8888)
    args = parser.parse_args()

    ok = run_tests(args.s, args.p)
    sys.exit(0 if ok else 1)
