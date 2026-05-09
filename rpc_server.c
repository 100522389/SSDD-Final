/* rpc_server.c – Implementación del servidor ONC-RPC de log de operaciones.
 * Compilar junto con log_svc.c y log_xdr.c (generados con rpcgen -N log.x).
 * Requiere rpcbind.
 */

#include "log.h"
#include <stdio.h>
#include <stdlib.h>

/* Imprime por stdout una línea "username\toperation" por cada llamada RPC. */
int *log_operation_1_svc(char *username, char *operation,
                          struct svc_req *rqstp)
{
    static int result;
    (void)rqstp;

    if (!username || !operation) {
        result = -1;
        return &result;
    }

    printf("%s\t%s\n", username, operation);
    fflush(stdout);

    result = 0;
    return &result;
}
