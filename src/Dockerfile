### 1. Get Linux
FROM python:3.11-slim


ARG BUILDTIME
ARG REVISION
ARG VERSION=1018.0.308

LABEL org.opencontainers.image.title="opc-ua-demo-server"
LABEL org.opencontainers.image.created=$BUILDTIME
LABEL org.opencontainers.image.description="OPC-UA Demo Server"
LABEL org.opencontainers.image.source="docker pull ghcr.io/thin-edge/opc-ua-demo-server:latest"
LABEL org.opencontainers.image.authors="Marco Stoffel, Stefan Witschel"
LABEL org.opencontainers.image.licenses="Apache 2.0"

RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    && rm -rf /var/lib/apt/lists/*

### 2. Install opcua
RUN pip --no-cache-dir install git+https://github.com/FreeOpcUa/opcua-asyncio.git@master
#COPY monitored_item_service.py /usr/local/lib/python3.11/site-packages/asyncua/server/
RUN apt-get purge -y --auto-remove git
### 3. Start server
EXPOSE 4840    
ADD server.py /
CMD ["python3", "server.py"]