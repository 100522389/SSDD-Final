"""
web_service.py  –  Servicio web de normalización de mensajes

Uso:
    python3 web_service.py

El servicio queda disponible en http://localhost:7789/?wsdl

Dependencias: requirements.txt
"""

import re
from spyne import Application, rpc, ServiceBase, Unicode
from spyne.protocol.soap import Soap11
from spyne.server.wsgi import WsgiApplication
from wsgiref.simple_server import make_server

# Puerto de escucha
SERVICE_PORT = 7789


class NormalizeService(ServiceBase):
    """Servicio SOAP de normalización de mensajes."""

    @rpc(Unicode, _returns=Unicode)
    def normalize(ctx, message):
        """
        Elimina espacios en blanco repetidos del mensaje.
        Ej.: "hola   mundo  !" → "hola mundo !"
        """
        if message is None:
            return ""
        return re.sub(r' +', ' ', message).strip()


# Aplicación Spyne
application = Application(
    [NormalizeService],
    tns='ssdd.normalize',
    in_protocol=Soap11(validator='lxml'),
    out_protocol=Soap11()
)


if __name__ == '__main__':
    wsgi_app = WsgiApplication(application)
    server   = make_server('0.0.0.0', SERVICE_PORT, wsgi_app)
    print(f"Servicio web activo en http://0.0.0.0:{SERVICE_PORT}/?wsdl")
    server.serve_forever()
