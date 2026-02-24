# Overview

This container will run an OPC-UA Demo Server based on https://github.com/FreeOpcUa/opcua-asyncio. You can connect to it on port 4840 without any authentication.

The server will simulate an industrial pump including al lot of runtime values. Basic idea is that the pump measures the pump has an operating level flow, filter state and power consumption.

## Functionality

Over time the filter is slowly clogging. This reduces the flow and increases the needed power. If the filter degrades below 30% the pump will throw an alarm and stops. After a period the cycle starts from scratch.

There are opc-ua methods included to configure the server over opc-ua. These are e.g. startPump, stopPump, resetfilter, changeOil etc. just play with it.
On the ServerConfig node you can update the update interval.

## Configuration

See an example docker-compose.yml file in src/docker-compose.yml. You can set the following parameters as environment variables:

      - PUMP_FILTER_DEGRADATION_RATE=3 # in minutes the filter will be clogged
      - PUMP_AUTO_RESET_MINUTES=1 # after 1 minute the alarm will be reset and the cycle starts again
      - PUMP_DEFAULT_OPERATING_LEVEL=80 # Pump operating level
      - PUMP_UPDATE_INTERVAL=3.0 # new measurements every 3 seconds

## Local development

You can build the image locally with:

`docker build -t opcserver:latest -f src/Dockerfile .`

Then you can run the container with:

`docker compose -f src/docker-compose_local.yml up`
