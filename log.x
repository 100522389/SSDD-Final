/*
 * log.x  –  Interfaz ONC-RPC del servicio de log de operaciones
 * Sistemas Distribuidos – UC3M 2025-2026
 *
 * Generar stubs con:
 *   rpcgen -a log.x
 *
 * El servidor de mensajería (server.c) es el CLIENTE de este servicio.
 * El proceso rpc_server es el SERVIDOR que implementa log_operation_1_svc.
 *
 * Cada vez que el servidor de mensajería recibe una operación envía:
 *   log_operation(username, operacion)
 *
 * Donde operacion puede ser: REGISTER, UNREGISTER, CONNECT, DISCONNECT,
 * USERS, SEND o "SENDATTACH <fichero>".
 *
 * Justificación de la interfaz:
 *   - Se usa 'string' (cadena de longitud variable) para username y
 *     operation con un límite de 256 caracteres, suficiente para ambos
 *     campos según los requisitos de la práctica.
 *   - El valor de retorno 'int' permite indicar éxito (0) o error (-1)
 *     al servidor de mensajería.
 *   - Se define una única versión (LOG_VERS = 1) con un único
 *     procedimiento (log_operation = 1).
 */

program LOG_PROG {
    version LOG_VERS {
        int log_operation(string username<256>, string operation<256>) = 1;
    } = 1;
} = 0x20000001;
