### 1. Get Linux
FROM python:3.11


ARG BUILDTIME
ARG REVISION
ARG VERSION=1018.0.308

LABEL org.opencontainers.image.title="opc-ua-demo-server"
LABEL org.opencontainers.image.created=$BUILDTIME
LABEL org.opencontainers.image.version=$VERSION
LABEL org.opencontainers.image.revision=$REVISION
LABEL org.opencontainers.image.description="OPC-UA Demo Server"
LABEL org.opencontainers.image.source="https://github.com/Cumulocity-IoT/opc-ua-demo-server"
LABEL org.opencontainers.image.authors="Marco Stoffel"
LABEL org.opencontainers.image.licenses="Apache 2.0"

### 2. Install opcua
RUN pip install asyncua

### 3. Start server
EXPOSE 4840    
ADD server.py /
CMD ["python3", "server.py"]