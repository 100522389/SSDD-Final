FROM ubuntu:22.04

# Evitar preguntas interactivas durante la instalación
ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y \
    gcc \
    make \
    libtirpc-dev \
    rpcsvc-proto \
    rpcbind \
    python3 \
    python3-pip \
    netcat-openbsd \
    && rm -rf /var/lib/apt/lists/*

# Código fuente
WORKDIR /app
COPY . .

# Compilar servidor y servidor RPC
RUN make all

# Dependencias Python
RUN pip3 install --break-system-packages spyne zeep lxml 2>/dev/null || \
    pip3 install spyne zeep lxml

# Compatibilidad de spyne con Python 3.10+
# Sustituye importaciones de six.moves por los equivalentes de la biblioteca estándar.
RUN SPYNE=$(python3 -c "import spyne, os; print(os.path.dirname(spyne.__file__))") && \
    grep -rl 'spyne.util.six.moves' "$SPYNE" --include='*.py' | \
    xargs --no-run-if-empty sed -i \
        -e 's|from spyne\.util\.six\.moves\.collections_abc import|from collections.abc import|g' \
        -e 's|from spyne\.util\.six\.moves\.http_cookies import|from http.cookies import|g' \
        -e 's|from spyne\.util\.six\.moves\.urllib\.parse import|from urllib.parse import|g' \
        -e 's|from spyne\.util\.six\.moves\.urllib\.request import|from urllib.request import|g' \
        -e 's|from spyne\.util\.six\.moves\.urllib\.error import|from urllib.error import|g' \
        -e 's|from spyne\.util\.six\.moves import|from collections.abc import|g' || true

# Verificar que spyne importa correctamente
RUN python3 -c "import spyne; from spyne.server.wsgi import WsgiApplication; print('spyne OK')"

EXPOSE 8888
EXPOSE 7789
