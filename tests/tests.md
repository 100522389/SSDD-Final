# Batería de pruebas

La batería de pruebas cubre las tres áreas del proyecto: el servicio de mensajería básico (Parte 1), las extensiones de transferencia de ficheros y comunicación P2P (Parte 2) y el servicio web SOAP de normalización de mensajes. Todas las pruebas están automatizadas y se ejecutan tanto en un entorno Docker reproducible como directamente en WSL mediante el script `run_prev.sh`.

---

## Pruebas de integración — Parte 1

Fichero: tests/test_integration_p1.py

El cliente Python envía operaciones al servidor C y se verifica tanto el código de retorno como el comportamiento observable: mensajes entregados, contenido de los payloads y estado interno del cliente.

**Registro y baja**

| # | Descripción | Operación enviada | Resultado esperado |
|---|---|---|---|
| 1 | Registro de usuario nuevo | REGISTER alice | RC = OK |
| 2 | Registro de usuario ya existente | REGISTER alice (2.ª vez) | RC = USER_ERROR |
| 3 | Registro de un segundo usuario nuevo | REGISTER bob | RC = OK |
| 4 | Baja de usuario inexistente | UNREGISTER nobody | RC = USER_ERROR |
| 5 | Baja de usuario registrado | UNREGISTER alice | RC = OK |

**Conexión y desconexión**

| # | Descripción | Operación enviada | Resultado esperado |
|---|---|---|---|
| 6 | Conexión de usuario registrado | CONNECT alice | RC = OK |
| 7 | Conexión de usuario ya conectado | CONNECT alice (2.ª vez) | RC = USER_ERROR |
| 8 | Desconexión de usuario conectado | DISCONNECT alice | RC = OK |
| 9 | Desconexión de usuario ya desconectado | DISCONNECT alice (2.ª vez) | RC = USER_ERROR |
| 10 | Desconexión de usuario inexistente | DISCONNECT nobody | RC = USER_ERROR |

**Envío de mensajes**

| # | Descripción | Condición verificada | Resultado esperado |
|---|---|---|---|
| 11 | Envío a usuario conectado | RC de client.send | RC = OK |
| 12 | Entrega inmediata al destinatario | Payload en el socket del receptor | Contiene operación, remitente y cuerpo |
| 13 | Envío a destinatario desconectado | RC de client.send con bob desconectado | RC = OK (almacenado en cola) |
| 14 | Entrega del mensaje pendiente al reconectarse | Payload recibido al ejecutar CONNECT bob | bob recibe el mensaje encolado |

**Consulta de usuarios**

| # | Descripción | Condición verificada | Resultado esperado |
|---|---|---|---|
| 15 | Consulta con usuario conectado | RC de client.users() | RC = OK |
| 16 | Consulta con usuario no conectado | RC de client.users() con carol sin conectar | RC = USER_ERROR |

**Estado interno del cliente**

| # | Descripción | Condición verificada | Resultado esperado |
|---|---|---|---|
| 17 | Limpieza del socket de escucha tras desconexión | Atributo _listen_sock tras DISCONNECT | None |
| 18 | Limpieza del hilo de escucha tras desconexión | Atributo _listen_thread tras DISCONNECT | None |

**Truncado de mensaje**

| # | Descripción | Condición verificada | Resultado esperado |
|---|---|---|---|
| 19 | SEND con mensaje de 300 caracteres | RC de client.send | RC = OK |
| 20 | Cuerpo recibido por el destinatario | Longitud del campo body en el payload | Igual o menor que 255 caracteres |

**Concurrencia**

Cinco hilos Python arrancan simultáneamente con una barrera de sincronización. Cada hilo registra un usuario único, se conecta, envía un mensaje al siguiente en sentido circular y se desconecta.

| # | Descripción | Condición verificada | Resultado esperado |
|---|---|---|---|
| 21 | 5 clientes concurrentes sin errores | Lista de errores vacía tras unir los 5 hilos | Sin fallos en ninguna operación |

**Forced disconnect**

Se simula un cliente que cierra abruptamente su socket sin notificar al servidor. Otro usuario envía un mensaje a ese cliente y se verifica que el servidor encola el mensaje y permite la reconexión.

| # | Descripción | Condición verificada | Resultado esperado |
|---|---|---|---|
| 22 | SEND a cliente con socket cerrado | RC de client.send | RC = OK (mensaje aceptado) |
| 23 | Cliente puede reconectarse tras cierre abrupto | Código de CONNECT con nuevo socket | 0 (OK) |
| 24 | Cliente recibe el mensaje encolado al reconectarse | Payload en el nuevo socket | Contiene la operación y el cuerpo original |

**Identificadores de mensaje**

| # | Descripción | Condición verificada | Resultado esperado |
|---|---|---|---|
| 25 | Primer envío devuelve id = 1 | Campo id en el ACK del remitente | "1" |
| 26 | Segundo envío devuelve id = 2 | Campo id en el ACK del remitente | "2" |
| 27 | Receptor recibe el primer mensaje con id = 1 | Campo id en el push del servidor | "1" |
| 28 | Receptor recibe el segundo mensaje con id = 2 | Campo id en el push del servidor | "2" |

---

## Pruebas de integración — Parte 2

Fichero: tests/test_p2.py

Verifican las extensiones de la Parte 2: SENDATTACH (envío con nombre de fichero adjunto), USERS enriquecido (usuario::IP::puerto) y GETFILE (transferencia P2P). Se usan sockets crudos para controlar los puertos de escucha y verificar el payload campo a campo.

**SENDATTACH a usuario conectado**

| # | Descripción | Condición verificada | Resultado esperado |
|---|---|---|---|
| 1 | Conexión del remitente | Código de respuesta CONNECT | 0 (OK) |
| 2 | Conexión del destinatario | Código de respuesta CONNECT | 0 (OK) |
| 3 | SENDATTACH devuelve código de éxito | Primer byte de la respuesta | 0 (OK) |
| 4 | SENDATTACH devuelve identificador de mensaje | Campo id en la respuesta | Cadena no vacía |
| 5 | El destinatario recibe la operación correcta | Primer campo del push al destinatario | SEND MESSAGE ATTACH |
| 6 | El destinatario recibe el remitente correcto | Segundo campo del push | sa_alice |
| 7 | El destinatario recibe el nombre de fichero | Quinto campo del push | /tmp/test_file.txt |
| 8 | El remitente recibe el ACK correcto | Primer campo del push al remitente | SEND MESS ATTACH ACK |
| 9 | El ACK incluye el nombre de fichero | Tercer campo del push al remitente | /tmp/test_file.txt |

**SENDATTACH a usuario desconectado**

| # | Descripción | Condición verificada | Resultado esperado |
|---|---|---|---|
| 10 | SENDATTACH a usuario no conectado | Primer byte de la respuesta | 0 (OK, mensaje encolado) |
| 11 | El destinatario puede conectarse | Código de respuesta CONNECT | 0 (OK) |
| 12 | El destinatario recibe el mensaje encolado | Primer campo del push | SEND MESSAGE ATTACH |
| 13 | El mensaje encolado incluye el fichero | Quinto campo del push | /tmp/queued_file.txt |
| 14 | El remitente recibe el ACK al entregarse | Primer campo del push al remitente | SEND MESS ATTACH ACK |

**USERS formato usuario::IP::puerto**

| # | Descripción | Condición verificada | Resultado esperado |
|---|---|---|---|
| 15 | USERS devuelve código de éxito | Primer byte de la respuesta | 0 (OK) |
| 16 | USERS devuelve al menos 2 entradas | Número de entradas en la lista | Mayor o igual que 2 |
| 17 | Todas las entradas tienen el formato correcto | Campos al dividir por "::" | Exactamente 3 campos |
| 18 | El usuario buscado aparece en la lista | Presencia de entrada con el prefijo esperado | Entrada encontrada |
| 19 | El puerto en USERS es correcto | Tercer campo de la entrada | Coincide con el puerto de escucha |
| 20 | _connected_users se actualiza | Clave en el diccionario del cliente | Entrada presente |
| 21 | El puerto almacenado en _connected_users es correcto | Puerto en el diccionario | Coincide con el puerto de escucha |

**GETFILE — transferencia P2P**

| # | Descripción | Condición verificada | Resultado esperado |
|---|---|---|---|
| 22 | GETFILE devuelve código de éxito | RC de client.getFile | RC = OK |
| 23 | El contenido del fichero recibido es correcto | Bytes del fichero destino | Idénticos al fichero original |
| 24 | GETFILE a usuario no conectado devuelve error | RC de client.getFile | RC = ERROR |

**SENDATTACH a usuario no registrado**

| # | Descripción | Condición verificada | Resultado esperado |
|---|---|---|---|
| 25 | SENDATTACH a usuario inexistente | Primer byte de la respuesta | 1 (USER DOES NOT EXIST) |

---

## Pruebas del servicio web de normalización

Fichero: tests/test_web_service.py

El servicio web expone una operación SOAP normalize que elimina los espacios duplicados de los mensajes antes de enviarlos. Las pruebas cubren la lógica pura de normalización (sin red), las llamadas SOAP reales al servicio y la gestión del cliente Zeep interno (caché y fallback).

**Tests unitarios — lógica pura sin servidor**

| # | Descripción | Entrada | Resultado esperado |
|---|---|---|---|
| 1 | Espacios múltiples internos | "hola   mundo" | "hola mundo" |
| 2 | Espacios al inicio y al final | "  hola mundo  " | "hola mundo" |
| 3 | Espacios en extremos e interior | "  a  b   c  " | "a b c" |
| 4 | Cadena con un solo espacio entre palabras | "hola mundo" | "hola mundo" |
| 5 | Cadena vacía | "" | "" |
| 6 | Entrada None | None | "" |
| 7 | Cadena formada solo por espacios | "     " | "" |
| 8 | Mensaje largo con múltiples huecos | "Este  es   un   mensaje…" | Espacios reducidos a uno |
| 9 | Cadena de un solo carácter | "x" | "x" |
| 10 | Salto de línea no afectado | "hola\nmundo" | "hola\nmundo" |

**Tests de integración SOAP vía Zeep**

| # | Descripción | Entrada | Resultado esperado |
|---|---|---|---|
| 11 | Espacios múltiples internos | "hola   mundo" | "hola mundo" |
| 12 | Espacios en extremos | "  a  b  " | "a b" |
| 13 | Cadena vacía | "" | "" |
| 14 | Mensaje sin espacios extra (idempotencia) | "correcto" | "correcto" |
| 15 | Cadena de solo espacios | "   " | "" |

**Tests de client._normalize — caché y fallback**

| # | Descripción | Condición verificada | Resultado esperado |
|---|---|---|---|
| 16 | Fallback ante fallo del cliente Zeep | Resultado de _normalize con cliente roto | Devuelve el mensaje original sin cambios |
| 17 | _zeep_client se resetea tras fallback | Atributo _zeep_client tras la excepción | None |
| 18 | Normalización correcta con servicio activo | Resultado de _normalize con espacios extra | "hola mundo" |
| 19 | Segunda llamada reutiliza el cliente en caché | Instancia de _zeep_client antes y después | Misma instancia |

---

## Pruebas de protocolo con netcat

Fichero: tests/test_phase1.sh

Se envían cadenas NUL-terminadas directamente al servidor con nc y se comprueba el byte de respuesta en hexadecimal, sin pasar por la API del cliente Python. Son las pruebas más cercanas al protocolo de red definido en la especificación.

| # | Descripción | Bytes enviados | Respuesta esperada |
|---|---|---|---|
| 1 | REGISTER alice — usuario nuevo | REGISTER\0alice\0 | 0x00 (OK) |
| 2 | REGISTER alice — usuario ya existente | REGISTER\0alice\0 (2.ª vez) | 0x01 (USERNAME IN USE) |
| 3 | REGISTER bob — usuario nuevo | REGISTER\0bob\0 | 0x00 (OK) |
| 4 | UNREGISTER nobody — usuario inexistente | UNREGISTER\0nobody\0 | 0x01 (USER DOES NOT EXIST) |
| 5 | UNREGISTER alice — usuario registrado | UNREGISTER\0alice\0 | 0x00 (OK) |
| 6 | CONNECT ghost — usuario no registrado | CONNECT\0ghost\09999\0 | 0x01 (USER DOES NOT EXIST) |
| 7 | CONNECT bob — usuario registrado | CONNECT\0bob\015001\0 | 0x00 (OK) |
| 8 | CONNECT bob — usuario ya conectado | CONNECT\0bob\015001\0 (2.ª vez) | 0x02 (USER ALREADY CONNECTED) |
| 9 | DISCONNECT bob — usuario conectado | DISCONNECT\0bob\0 | 0x00 (OK) |
| 10 | DISCONNECT bob — usuario ya desconectado | DISCONNECT\0bob\0 (2.ª vez) | 0x02 (USER NOT CONNECTED) |
| 11 | DISCONNECT nobody — usuario inexistente | DISCONNECT\0nobody\0 | 0x01 (USER DOES NOT EXIST) |

---

## Pruebas del servidor RPC de log

Fichero: tests/test_rpc.sh

Se arranca rpc_server y server con LOG_RPC_IP=localhost y se ejecuta una secuencia de operaciones a través de client.py. Después se comprueba que cada operación ha quedado registrada en el log del servidor RPC con el formato usuario + tabulador + OPERACIÓN.

| # | Descripción | Patrón buscado en el log |
|---|---|---|
| 1 | REGISTER alice | alice + REGISTER |
| 2 | REGISTER bob | bob + REGISTER |
| 3 | CONNECT alice | alice + CONNECT |
| 4 | CONNECT bob | bob + CONNECT |
| 5 | SEND de alice | alice + SEND |
| 6 | SENDATTACH de alice con fichero | alice + SENDATTACH + /tmp/rpc_test_file.txt |
| 7 | USERS de alice | alice + USERS |
| 8 | DISCONNECT alice | alice + DISCONNECT |
| 9 | DISCONNECT bob | bob + DISCONNECT |
| 10 | UNREGISTER alice | alice + UNREGISTER |
| 11 | UNREGISTER bob | bob + UNREGISTER |

---

## Resumen

| Suite | Fichero | Casos |
|---|---|---|
| Integración Parte 1 | test_integration_p1.py | 28 |
| Integración Parte 2 | test_p2.py | 25 |
| Servicio web | test_web_service.py | 19 |
| Protocolo P1 con netcat | test_phase1.sh | 11 |
| Servidor RPC de log | test_rpc.sh | 11 |
| **Total** | | **94** |
