/*
 * rpc_server.c  –  Servidor ONC-RPC de log de operaciones
 *
 * Implementa log_operation_1_svc, generado a partir de log.x mediante:
 *   rpcgen -a log.x
 *
 * Compilar junto con los stubs generados (log_svc.c, log_xdr.c):
 *   gcc -std=gnu99 -Wall -Wextra -o rpc_server rpc_server.c log_svc.c log_xdr.c
 *
 * Uso:
 *   ./rpc_server
 *   (portmap / rpcbind debe estar activo)
 */

#include "log.h"     /* generado por rpcgen */
#include <stdio.h>
#include <stdlib.h>

/*
 * log_operation_1_svc – imprime por stdout el nombre del usuario y la
 * operación que ha realizado.
 *
 * Formato de salida:
 *   <username>\t<operation>
 *
 * Para SENDATTACH, operation incluye el nombre del fichero:
 *   alice\tSENDATTACH /tmp/datos.txt
 */
int *log_operation_1_svc(char **username, char **operation,
                           struct svc_req *rqstp)
{
    static int result;
    (void)rqstp;

    if (!username || !*username || !operation || !*operation) {
        result = -1;
        return &result;
    }

    printf("%s\t%s\n", *username, *operation);
    fflush(stdout);

    result = 0;
    return &result;
}
