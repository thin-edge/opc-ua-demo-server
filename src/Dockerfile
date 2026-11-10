FROM python:3.13-slim

ARG BUILDTIME
ARG REVISION
ARG ASYNCUA_VERSION=2.1.0

LABEL org.opencontainers.image.title="opc-ua-demo-server"
LABEL org.opencontainers.image.created=$BUILDTIME
LABEL org.opencontainers.image.revision=$REVISION
LABEL org.opencontainers.image.description="OPC-UA Demo Server"
LABEL org.opencontainers.image.source="https://github.com/thin-edge/opc-ua-demo-server"
LABEL org.opencontainers.image.authors="Marco Stoffel, Stefan Witschel"
LABEL org.opencontainers.image.licenses="Apache-2.0"

RUN pip --no-cache-dir install "asyncua==${ASYNCUA_VERSION}"

# The server's self-signed certificate lives here. Mount a volume to keep it across
# container restarts, so clients that trusted it don't have to trust a new one.
ENV OPCUA_CERT_DIR=/certs
RUN mkdir -p /certs

EXPOSE 4840
COPY server.py datatypes.py /
CMD ["python3", "server.py"]
