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

## Structured values and other data types

Besides the pumps, the server has a `DataTypes` object with one node for each kind of value that
needs more than a plain number or string to decode. The node ids are strings, `ns=2;s=DataTypes.<Name>`,
and most values follow Pump01's simulation, so they change over time.

| Node | Type | Shows |
|---|---|---|
| `PumpStatus` | `PumpStatus` structure | scalar fields, a nested structure (`Motor.Current`), an enum (`Mode`), an array (`FlowHistory[4]`), a DateTime (`LastService`), an array of structures (`Readings[1].Value`), an optional field (`AlarmText`, present only in alarm) |
| `PumpStatusAbstract` | `Structure` (abstract) | the same value; the concrete type is found through the value's encoding |
| `Motor` | `PumpMotor` structure | a small structure that changes every update (for subscriptions) |
| `Setpoint` | `PumpSetpoint` union | `Level` while running, `Reason` (the alarm) while in alarm |
| `FlowHistory`, `Temperatures` | Double[] | arrays; read one element by index |
| `LastService` | DateTime | set at start-up and by `resetFilter` / `changeOil` |
| `StatusText` | LocalizedText | `Idle`, `Running` or `Alarm` (en-US) |
| `LastError` | StatusCode | `Good`, or a Bad code while in alarm |
| `DeviceUid` | Guid | fixed |
| `RelatedNode`, `RelatedNodeExpanded` | NodeId, ExpandedNodeId | point at `Pump01` |
| `BrowseNameValue` | QualifiedName | `2:Pump01` |
| `RawFrame` | ByteString | operating level and filter state (uint16) and flow (float32), big-endian |

The custom types (`PumpStatus`, `PumpMotor`, `PumpReading`, `PumpMode`, `PumpSetpoint`) publish
their `DataTypeDefinition` (OPC UA 1.04), so a client can decode them without compiled-in type
information. The definitions live in `src/datatypes.py`.

A tedge-dot connector configuration that reads all of them is in
[`examples/tedge-dot-datatypes.toml`](examples/tedge-dot-datatypes.toml):

```sh
tedge-dot read -c examples/tedge-dot-datatypes.toml
```

`status_alarm_text` and `setpoint_reason` report bad quality while the pump is not in alarm: the
optional field is absent and the union holds the other member. That is expected. To see the alarm
side quickly, run the server with `PUMP_FILTER_DEGRADATION_RATE=1`: the filter clogs within about a minute.

## Local development

You can build the image locally with:

`docker build -t opcserver:latest src`

Then you can run the container with:

`docker compose -f src/docker-compose_local.yml up`
