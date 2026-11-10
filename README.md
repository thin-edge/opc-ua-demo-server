# Overview

This container runs an OPC UA demo server based on [asyncua](https://github.com/FreeOpcUa/opcua-asyncio) 2.1.0. You can connect to it on port 4840 without any authentication, either without security or with Basic256Sha256 (Sign or SignAndEncrypt).

The server will simulate an industrial pump including al lot of runtime values. Basic idea is that the pump measures the pump has an operating level flow, filter state and power consumption.

## Functionality

Over time the filter slowly clogs. This reduces the flow and increases the power the pump needs. If the filter state drops below 20%, the pump raises an alarm and stops. Low oil (below 15%), an overheated bearing (above 75 °C), a random power failure, and a leakage also raise alarms. After `PUMP_AUTO_RESET_MINUTES` the alarm clears and the cycle starts again.

Pump01 has OPC UA methods to control it: `startPump`, `stopPump`, `setOperatingLevel`, `setFilterDegradationRate`, `setAutoResetMinutes`, `resetFilter`, and `changeOil`. All method arguments have names and descriptions.

You can also write these variables directly. A write has the same effect as calling the matching method, and an invalid value is rejected (the variable shows the active value again after the next update):

| Variable | Effect |
|---|---|
| `ServerConfig.updateInterval` | update interval in seconds (0.1 to 60), same as `setUpdateInterval` |
| `Pump01.operatingLevel` | target operating level in % (0 to 100), same as `setOperatingLevel` |
| `Pump01.filterDegradationRate` | minutes until the filter clogs at full load |
| `Pump01.autoResetMinutes` | minutes the pump stays in alarm |
| `Pump01.defaultOperatingLevel` | level that `startPump` uses |

### Alarm events

When Pump01 raises or clears an alarm, the server fires a `PumpAlarmEventType` event (a subtype of `BaseEventType`). It is sent from both `Pump01` and the `Server` object, so subscribe to one of them. Besides the standard fields (`Message`, `Severity`, `SourceName`, `Time`), the event has:

- `AlarmType`: `FilterClogged`, `OilLow`, `BearingOverheated`, `PowerFailure`, or `Leakage`
- `Active`: `true` when the alarm is raised, `false` when it clears

Select these two fields with an event filter on `PumpAlarmEventType`. A filter on `BaseEventType` returns only the standard fields.

### History

The server keeps the values of Pump01's variables in memory, so clients can read their history (HistoryRead, raw values). History is lost when the server restarts.

### Timestamps

All values have a source timestamp and a server timestamp.

## Configuration

See an example docker-compose.yml file in src/docker-compose.yml. You can set the following parameters as environment variables:

      - PUMP_FILTER_DEGRADATION_RATE=3 # in minutes the filter will be clogged
      - PUMP_AUTO_RESET_MINUTES=1 # after 1 minute the alarm will be reset and the cycle starts again
      - PUMP_DEFAULT_OPERATING_LEVEL=80 # Pump operating level
      - PUMP_UPDATE_INTERVAL=3.0 # new measurements every 3 seconds

Optional:

      - PUMP_OIL_CHANGE_HOURS=2000 # run hours until the oil is empty
      - PUMP_HISTORY_HOURS=24 # how long history is kept
      - PUMP_HISTORY_MAX_VALUES=50000 # history values kept per variable
      - OPCUA_CERT_DIR=/certs # where the server certificate is stored
      - OPCUA_CERT_HOSTNAME=opcserver # host name in the certificate (default: the container's host name)

### Server certificate

On first start, the server creates a self-signed certificate in `OPCUA_CERT_DIR` and reuses it while it stays valid. It creates a new one when the host name changes, so the compose files set `hostname: opcserver` and keep `/certs` on a volume. Clients that connect with security must trust this certificate. Client certificates are not checked.

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
| `AlarmInfo` | `PumpAlarmInfo` structure | a second enum (`AlarmType`, of type `PumpAlarmType`), a LocalizedText field (`Message`), an optional DateTime (`RaisedAt`, present only in alarm), and UInt16, Int32, and UInt32 fields (`Severity`, `RemainingSeconds`, `AlarmCount`) |

The custom types (`PumpStatus`, `PumpMotor`, `PumpReading`, `PumpMode`, `PumpSetpoint`, `PumpAlarmInfo`, `PumpAlarmType`) publish
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

To run the server without Docker (Python 3.10 or later):

```sh
pip install asyncua==2.1.0
cd src && python3 server.py
```

### Node ids

The pump variables and methods have numeric node ids (`ns=2;i=...`) that asyncua assigns in creation order. Client configurations store these ids, so add new nodes only at the end of `main()` in `server.py` (after `DataTypeDemo.create`), or give them string node ids.

## Releasing

The `release` workflow (`.github/workflows/release.yaml`) builds the image for `linux/amd64` and `linux/arm64`, pushes it to `ghcr.io/thin-edge/opc-ua-demo-server`, and then creates the git tag and a GitHub release with generated notes.

1. In GitHub, open **Actions > release > Run workflow**.
2. Keep the branch on `main` and enter the new version, such as `0.1.0` (no `v` prefix).

Pushing a tag such as `0.1.0` starts the same workflow.

| Version | Image tags |
|---|---|
| `0.1.0` | `0.1.0`, `0.1`, `latest` |
| `0.2.0-rc.1` | `0.2.0-rc.1` (marked as a prerelease, `latest` is unchanged) |

The tag and release are created only after the image was pushed. If the build fails, nothing is tagged and you can run the workflow again with the same version.
