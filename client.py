from enum import Enum
import argparse
import socket
import threading

class client :

    # ******************** TYPES *********************
    # * @brief Return codes for the protocol methods
    class RC(Enum) :
        OK = 0
        ERROR = 1
        USER_ERROR = 2

    # ****************** ATTRIBUTES ******************
    _server = None
    _port   = -1

    # Estado interno del cliente conectado
    _username      = None          # usuario actualmente conectado
    _listen_sock   = None          # socket de escucha del hilo receptor
    _listen_port   = None          # puerto elegido para el hilo receptor
    _listen_thread = None          # hilo receptor de mensajes
    _connected_users = {}          # {username: (ip, port)} – actualizado con USERS (P2)

    # Utilidades de protocolo

    @staticmethod
    def _send_str(sock, s):
        """Envía una cadena NUL-terminada por el socket."""
        sock.sendall((s + '\0').encode())

    @staticmethod
    def _recv_str(sock):
        """Recibe una cadena NUL-terminada del socket."""
        buf = b''
        while True:
            c = sock.recv(1)
            if not c:
                raise ConnectionError("Conexión cerrada por el servidor")
            if c == b'\0':
                return buf.decode()
            buf += c

    @staticmethod
    def _connect_server():
        """Abre una conexión TCP al servidor y la devuelve."""
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.connect((client._server, client._port))
        return s

    @staticmethod
    def _normalize(message):
        """
        Llama al servicio web SOAP para normalizar espacios del mensaje.
        Si el servicio no está disponible, devuelve el mensaje sin cambios.
        """
        try:
            from zeep import Client as ZeepClient
            wsdl = "http://localhost:7789/?wsdl"
            wc = ZeepClient(wsdl)
            return wc.service.normalize(message)
        except Exception:
            return message

    # Hilo de escucha de mensajes entrantes

    @staticmethod
    def _listener_loop():
        """
        Hilo receptor: acepta conexiones en _listen_sock y procesa
        los mensajes enviados por el servidor.
        """
        client._listen_sock.settimeout(1.0)
        while True:
            try:
                conn, _ = client._listen_sock.accept()
            except socket.timeout:
                # Comprobar si el hilo debe terminar
                if client._listen_sock is None:
                    break
                continue
            except Exception:
                break

            try:
                op = client._recv_str(conn)

                if op == "SEND MESSAGE":
                    # Protocolo §8.6: from + id + body
                    sender = client._recv_str(conn)
                    msg_id = client._recv_str(conn)
                    body   = client._recv_str(conn)
                    print(f"\ns> MESSAGE {msg_id} FROM {sender}")
                    print(f"  {body}")
                    print("  END")

                elif op == "SEND MESS ACK":
                    # ACK de entrega de SEND §8.6
                    msg_id = client._recv_str(conn)
                    print(f"\nc> SEND MESSAGE {msg_id} OK")

                elif op == "SEND MESSAGE ATTACH":
                    # Protocolo §2.3: from + id + body + filename
                    sender   = client._recv_str(conn)
                    msg_id   = client._recv_str(conn)
                    body     = client._recv_str(conn)
                    filename = client._recv_str(conn)
                    print(f"\ns> MESSAGE {msg_id} FROM {sender}")
                    print(f"  {body}")
                    print("  END")
                    print(f"  FILE {filename}")

                elif op == "SEND MESS ATTACH ACK":
                    # ACK de entrega de SENDATTACH §2.3
                    msg_id   = client._recv_str(conn)
                    filename = client._recv_str(conn)
                    print(f"\nc> SENDATTACH MESSAGE {msg_id} {filename} OK")

                elif op == "GET FILE":
                    # Solicitud de transferencia de fichero (P2P)
                    _requester = client._recv_str(conn)
                    filename   = client._recv_str(conn)
                    try:
                        with open(filename, 'rb') as f:
                            data = f.read()
                        conn.sendall(data)
                    except Exception:
                        pass  # si no existe o hay error, cierra sin enviar

            except Exception:
                pass
            finally:
                conn.close()

    # Métodos de la interfaz

    # *
    # * @param user - User name to register in the system
    # *
    # * @return OK if successful
    # * @return USER_ERROR if the user is already registered
    # * @return ERROR if another error occurred
    @staticmethod
    def register(user):
        try:
            s = client._connect_server()
            client._send_str(s, "REGISTER")
            client._send_str(s, user)
            code = s.recv(1)[0]
            s.close()
        except Exception:
            print("c> REGISTER FAIL")
            return client.RC.ERROR

        if code == 0:
            print("c> REGISTER OK")
            return client.RC.OK
        elif code == 1:
            print("c> USERNAME IN USE")
            return client.RC.USER_ERROR
        else:
            print("c> REGISTER FAIL")
            return client.RC.ERROR

    # *
    # * @param user - User name to unregister from the system
    # *
    # * @return OK if successful
    # * @return USER_ERROR if the user does not exist
    # * @return ERROR if another error occurred
    @staticmethod
    def unregister(user):
        try:
            s = client._connect_server()
            client._send_str(s, "UNREGISTER")
            client._send_str(s, user)
            code = s.recv(1)[0]
            s.close()
        except Exception:
            print("c> UNREGISTER FAIL")
            return client.RC.ERROR

        if code == 0:
            print("c> UNREGISTER OK")
            return client.RC.OK
        elif code == 1:
            print("c> USER DOES NOT EXIST")
            return client.RC.USER_ERROR
        else:
            print("c> UNREGISTER FAIL")
            return client.RC.ERROR

    # *
    # * @param user - User name to connect to the system
    # *
    # * @return OK if successful
    # * @return USER_ERROR if the user does not exist or if it is already connected
    # * @return ERROR if another error occurred
    @staticmethod
    def connect(user):
        # 1. Crear socket de escucha en un puerto libre
        try:
            listen_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            listen_sock.bind(('', 0))
            listen_port = listen_sock.getsockname()[1]
            listen_sock.listen(32)
        except Exception:
            print("c> CONNECT FAIL")
            return client.RC.ERROR

        # 2. Lanzar hilo receptor ANTES de enviar CONNECT al servidor
        client._listen_sock   = listen_sock
        client._listen_port   = listen_port
        client._listen_thread = threading.Thread(
            target=client._listener_loop, daemon=True)
        client._listen_thread.start()

        # 3. Enviar CONNECT al servidor
        try:
            s = client._connect_server()
            client._send_str(s, "CONNECT")
            client._send_str(s, user)
            client._send_str(s, str(listen_port))
            code = s.recv(1)[0]
            s.close()
        except Exception:
            client._listen_sock.close()
            client._listen_sock = None
            print("c> CONNECT FAIL")
            return client.RC.ERROR

        if code == 0:
            client._username = user
            print("c> CONNECT OK")
            return client.RC.OK
        elif code == 1:
            client._listen_sock.close()
            client._listen_sock = None
            print("c> CONNECT FAIL, USER DOES NOT EXIST")
            return client.RC.USER_ERROR
        elif code == 2:
            client._listen_sock.close()
            client._listen_sock = None
            print("c> USER ALREADY CONNECTED")
            return client.RC.USER_ERROR
        else:
            client._listen_sock.close()
            client._listen_sock = None
            print("c> CONNECT FAIL")
            return client.RC.ERROR

    # *
    # *
    # * @return OK if successful
    # * @return USER_ERROR if the user is not connected
    # * @return ERROR if another error occurred
    @staticmethod
    def users():
        try:
            s = client._connect_server()
            client._send_str(s, "USERS")
            client._send_str(s, client._username if client._username else "")
            code = s.recv(1)[0]
        except Exception:
            print("c> CONNECTED USERS FAIL")
            return client.RC.ERROR

        if code == 0:
            try:
                count_str = client._recv_str(s)
                count     = int(count_str)
                names = []
                for _ in range(count):
                    entry = client._recv_str(s)
                    names.append(entry)
                s.close()
            except Exception:
                print("c> CONNECTED USERS FAIL")
                return client.RC.ERROR

            # P1: solo nombre; P2: "user::ip::port"
            print(f"c> CONNECTED USERS ({count} users connected) OK")
            for entry in names:
                parts = entry.split("::")
                print(f"  {parts[0]}")
                if len(parts) == 3:
                    # Actualizar tabla para GETFILE (P2)
                    client._connected_users[parts[0]] = (parts[1], int(parts[2]))
            return client.RC.OK

        elif code == 1:
            s.close()
            print("c> CONNECTED USERS FAIL, USER IS NOT CONNECTED")
            return client.RC.USER_ERROR
        else:
            s.close()
            print("c> CONNECTED USERS FAIL")
            return client.RC.ERROR

    # *
    # * @param user - User name to disconnect from the system
    # *
    # * @return OK if successful
    # * @return USER_ERROR if the user does not exist
    # * @return ERROR if another error occurred
    @staticmethod
    def disconnect(user):
        try:
            s = client._connect_server()
            client._send_str(s, "DISCONNECT")
            client._send_str(s, user)
            code = s.recv(1)[0]
            s.close()
        except Exception:
            code = 3  # tratamos como error pero igualmente paramos el hilo

        # Detener el hilo receptor independientemente del resultado
        if client._listen_sock is not None:
            try:
                client._listen_sock.close()
            except Exception:
                pass
            client._listen_sock = None
        client._username = None

        if code == 0:
            print("c> DISCONNECT OK")
            return client.RC.OK
        elif code == 1:
            print("c> DISCONNECT FAIL, USER DOES NOT EXIST")
            return client.RC.USER_ERROR
        elif code == 2:
            print("c> DISCONNECT FAIL, USER NOT CONNECTED")
            return client.RC.USER_ERROR
        else:
            print("c> DISCONNECT FAIL")
            return client.RC.ERROR

    # *
    # * @param user    - Receiver user name
    # * @param message - Message to be sent
    # *
    # * @return OK if the server had successfully delivered the message
    # * @return USER_ERROR if the user is not connected (message queued)
    # * @return ERROR the user does not exist or another error occurred
    @staticmethod
    def send(user, message):
        message = client._normalize(message)
        try:
            s = client._connect_server()
            client._send_str(s, "SEND")
            client._send_str(s, client._username if client._username else "")
            client._send_str(s, user)
            client._send_str(s, message[:255])
            code = s.recv(1)[0]
            if code == 0:
                msg_id = client._recv_str(s)
            s.close()
        except Exception:
            print("c> SEND FAIL")
            return client.RC.ERROR

        if code == 0:
            print(f"c> SEND OK - MESSAGE {msg_id}")
            return client.RC.OK
        elif code == 1:
            print("c> SEND FAIL, USER DOES NOT EXIST")
            return client.RC.USER_ERROR
        else:
            print("c> SEND FAIL")
            return client.RC.ERROR

    # *
    # * @param user    - Receiver user name
    # * @param file    - file to be sent
    # * @param message - Message to be sent
    # *
    # * @return OK if the server had successfully delivered the message
    # * @return USER_ERROR if the user is not connected (message queued)
    # * @return ERROR the user does not exist or another error occurred
    @staticmethod
    def sendAttach(user, file, message):
        message = client._normalize(message)
        try:
            s = client._connect_server()
            client._send_str(s, "SENDATTACH")
            client._send_str(s, client._username if client._username else "")
            client._send_str(s, user)
            client._send_str(s, message[:255])
            client._send_str(s, file[:255])
            code = s.recv(1)[0]
            if code == 0:
                msg_id = client._recv_str(s)
            s.close()
        except Exception:
            print("c> SENDATTACH FAIL")
            return client.RC.ERROR

        if code == 0:
            print(f"c> SENDATTACH OK - MESSAGE {msg_id}")
            return client.RC.OK
        elif code == 1:
            print("c> SENDATTACH FAIL, USER DOES NOT EXIST")
            return client.RC.USER_ERROR
        else:
            print("c> SENDATTACH FAIL")
            return client.RC.ERROR

    @staticmethod
    def getFile(username, filename, local_filename):
        """
        GETFILE <userName> <fileName> <localFileName>
        Solicita el fichero <fileName> al cliente <userName> y lo almacena en
        <localFileName>. Requiere conocer la IP y puerto del destinatario
        (obtenida previamente con USERS en formato P2). §2.5
        """
        # Buscar IP:puerto en la tabla local; si no está, refrescar con USERS
        if username not in client._connected_users:
            client.users()

        if username not in client._connected_users:
            print("c> FILE TRANSFER FAILED, user not connected.")
            return client.RC.ERROR

        ip, port = client._connected_users[username]

        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.connect((ip, port))
            client._send_str(s, "GET FILE")
            client._send_str(s, client._username if client._username else "")
            client._send_str(s, filename)

            # Recibir contenido del fichero hasta que el remoto cierre
            data = b''
            while True:
                chunk = s.recv(4096)
                if not chunk:
                    break
                data += chunk
            s.close()

            with open(local_filename, 'wb') as f:
                f.write(data)

            print(f"c> FILE TRANSFER OK")
            return client.RC.OK
        except Exception:
            print("c> FILE TRANSFER FAILED")
            return client.RC.ERROR

    # *
    # **
    # * @brief Command interpreter for the client. It calls the protocol functions.
    @staticmethod
    def shell():

        while (True) :
            try :
                command = input("c> ")
                line = command.split(" ")
                if (len(line) > 0):

                    line[0] = line[0].upper()

                    if (line[0]=="REGISTER") :
                        if (len(line) == 2) :
                            client.register(line[1])
                        else :
                            print("Syntax error. Usage: REGISTER <userName>")

                    elif(line[0]=="UNREGISTER") :
                        if (len(line) == 2) :
                            client.unregister(line[1])
                        else :
                            print("Syntax error. Usage: UNREGISTER <userName>")

                    elif(line[0]=="CONNECT") :
                        if (len(line) == 2) :
                            client.connect(line[1])
                        else :
                            print("Syntax error. Usage: CONNECT <userName>")

                    elif(line[0]=="DISCONNECT") :
                        if (len(line) == 2) :
                            client.disconnect(line[1])
                        else :
                            print("Syntax error. Usage: DISCONNECT <userName>")

                    elif(line[0]=="USERS") :
                        if (len(line) == 1) :
                            client.users()
                        else :
                            print("Syntax error. Usage: CONNECTED_USERS <userName>")

                    elif(line[0]=="SEND") :
                        if (len(line) >= 3) :
                            #  Remove first two words
                            message = ' '.join(line[2:])
                            client.send(line[1], message)
                        else :
                            print("Syntax error. Usage: SEND <userName> <message>")

                    elif(line[0]=="SENDATTACH") :
                        if (len(line) >= 4) :
                            #  Remove first two words
                            message = ' '.join(line[3:])
                            client.sendAttach(line[1], line[2], message)
                        else :
                            print("Syntax error. Usage: SENDATTACH <userName> <filename> <message>")

                    elif(line[0]=="GETFILE") :
                        if (len(line) == 4) :
                            client.getFile(line[1], line[2], line[3])
                        else :
                            print("Syntax error. Usage: GETFILE <userName> <fileName> <localFileName>")

                    elif(line[0]=="QUIT") :
                        if (len(line) == 1) :
                            break
                        else :
                            print("Syntax error. Use: QUIT")
                    else :
                        print("Error: command " + line[0] + " not valid.")
            except Exception as e:
                print("Exception: " + str(e))

    # *
    # * @brief Prints program usage
    @staticmethod
    def usage() :
        print("Usage: python3 client.py -s <server> -p <port>")


    # *
    # * @brief Parses program execution arguments
    @staticmethod
    def  parseArguments(argv) :
        parser = argparse.ArgumentParser()
        parser.add_argument('-s', type=str, required=True, help='Server IP')
        parser.add_argument('-p', type=int, required=True, help='Server Port')
        args = parser.parse_args()

        if (args.s is None):
            parser.error("Usage: python3 client.py -s <server> -p <port>")
            return False

        if ((args.p < 1024) or (args.p > 65535)):
            parser.error("Error: Port must be in the range 1024 <= port <= 65535")
            return False

        client._server = args.s
        client._port   = args.p

        return True


    # ******************** MAIN *********************
    @staticmethod
    def main(argv) :
        if (not client.parseArguments(argv)) :
            client.usage()
            return

        #  Write code here
        client.shell()
        print("+++ FINISHED +++")
    

if __name__=="__main__":
    client.main([])
