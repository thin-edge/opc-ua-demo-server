"""
Demo nodes for structured values and the less common built-in types.

Everything lives under the `DataTypes` object, with string NodeIds
(`ns=<idx>;s=DataTypes.<Name>`), so a client configuration can name the nodes
without browsing for numeric ids first.

The custom types are created with `new_struct` / `new_enum`, which publish each
type's `DataTypeDefinition` attribute (OPC UA 1.04). A client can read that
definition and decode the structure without any compiled-in type information.

Most nodes follow Pump01's simulation, so they change and can be subscribed to:

| Node                         | Shows                                                          |
|------------------------------|----------------------------------------------------------------|
| PumpStatus                   | structure: scalar, nested structure, enum, array, DateTime,    |
|                              | array of structures, optional field                            |
| PumpStatusAbstract           | the same value, but the variable is declared with the abstract |
|                              | `Structure` type: the concrete type comes from the value       |
| Motor                        | a small structure on its own (changes every update)            |
| Setpoint                     | a union: `Level` while running, `Reason` while in alarm        |
| FlowHistory, Temperatures    | arrays of Double (select one element by index)                 |
| LastService                  | DateTime (set at start and on resetFilter)                     |
| StatusText                   | LocalizedText                                                  |
| LastError                    | StatusCode (Good, or Bad... while the pump is in alarm)        |
| DeviceUid                    | Guid                                                           |
| RelatedNode, RelatedNodeExpanded | NodeId and ExpandedNodeId, pointing at Pump01              |
| BrowseNameValue              | QualifiedName                                                  |
| RawFrame                     | ByteString: level, filter state and flow packed big-endian     |
"""
import struct
import uuid
from datetime import datetime, timezone

from asyncua import ua
from asyncua.common.structures104 import new_enum, new_struct, new_struct_field

DEVICE_UID = uuid.UUID("72962b91-fa75-4ae6-8d28-b404dc7daf63")
FLOW_HISTORY_LEN = 5

# What an alarm reports as LastError. Any Bad code would do; these read well.
ALARM_STATUS = {
    "FilterClogged": ua.StatusCodes.BadDeviceFailure,
    "OilLow": ua.StatusCodes.BadDeviceFailure,
    "BearingOverheated": ua.StatusCodes.BadOutOfRange,
    "PowerFailure": ua.StatusCodes.BadCommunicationError,
    "Leakage": ua.StatusCodes.BadDeviceFailure,
}


class DataTypeDemo:
    """The DataTypes object and its nodes; `update` mirrors Pump01 into them."""

    @classmethod
    async def create(cls, server, idx, pump01):
        self = cls()
        self.server = server
        self.idx = idx
        self.flow_history = [0.0] * FLOW_HISTORY_LEN
        self.last_service = datetime.now(timezone.utc)

        motor_type, _ = await new_struct(server, idx, "PumpMotor", [
            new_struct_field("Current", ua.VariantType.Float),
            new_struct_field("Temperature", ua.VariantType.Float),
        ])
        mode_type = await new_enum(server, idx, "PumpMode", ["Idle", "Running", "Alarm"])
        reading_type, _ = await new_struct(server, idx, "PumpReading", [
            new_struct_field("Name", ua.VariantType.String),
            new_struct_field("Value", ua.VariantType.Double),
        ])
        await new_struct(server, idx, "PumpStatus", [
            new_struct_field("Running", ua.VariantType.Boolean),
            new_struct_field("OperatingLevel", ua.VariantType.Double),
            new_struct_field("Motor", motor_type),
            new_struct_field("Label", ua.VariantType.String),
            new_struct_field("Mode", mode_type),
            new_struct_field("FlowHistory", ua.VariantType.Double, array=True),
            new_struct_field("LastService", ua.VariantType.DateTime),
            new_struct_field("Readings", reading_type, array=True),
            new_struct_field("AlarmText", ua.VariantType.String, optional=True),
            new_struct_field("RunHours", ua.VariantType.UInt32),
        ])
        await new_struct(server, idx, "PumpSetpoint", [
            new_struct_field("Level", ua.VariantType.Double),
            new_struct_field("Reason", ua.VariantType.String),
        ], is_union=True)
        # Makes ua.PumpStatus etc. available as Python classes.
        await server.load_data_type_definitions()

        self.folder = await server.nodes.objects.add_object(
            ua.NodeId("DataTypes", idx), ua.QualifiedName("DataTypes", idx))

        status = self._status(running=False, level=0.0, current=0.0, temperature=35.0,
                              mode=ua.PumpMode.Idle, alarm=None, flow=0.0, power=0.0,
                              run_hours=0)
        self.pump_status = await self._add(
            "PumpStatus", status, ua.VariantType.ExtensionObject, ua.PumpStatus.data_type)
        self.pump_status_abstract = await self._add(
            "PumpStatusAbstract", status, ua.VariantType.ExtensionObject,
            ua.NodeId(ua.ObjectIds.Structure))
        self.motor = await self._add(
            "Motor", ua.PumpMotor(Current=0.0, Temperature=35.0),
            ua.VariantType.ExtensionObject, ua.PumpMotor.data_type)
        self.setpoint = await self._add(
            "Setpoint", self._setpoint(level=0.0, alarm=None),
            ua.VariantType.ExtensionObject, ua.PumpSetpoint.data_type)

        self.flow_history_node = await self._add(
            "FlowHistory", list(self.flow_history), ua.VariantType.Double)
        self.temperatures = await self._add(
            "Temperatures", [20.0, 35.0], ua.VariantType.Double)

        self.last_service_node = await self._add(
            "LastService", self.last_service, ua.VariantType.DateTime)
        self.status_text = await self._add(
            "StatusText", ua.LocalizedText("Idle", "en-US"), ua.VariantType.LocalizedText)
        self.last_error = await self._add(
            "LastError", ua.StatusCode(ua.StatusCodes.Good), ua.VariantType.StatusCode)
        await self._add("DeviceUid", DEVICE_UID, ua.VariantType.Guid)
        await self._add("RelatedNode", pump01.nodeid, ua.VariantType.NodeId)
        expanded = ua.ExpandedNodeId(pump01.nodeid.Identifier, pump01.nodeid.NamespaceIndex,
                                     NamespaceUri="http://www.cumulocity.com")
        await self._add("RelatedNodeExpanded", expanded, ua.VariantType.ExpandedNodeId)
        await self._add("BrowseNameValue", ua.QualifiedName("Pump01", idx),
                        ua.VariantType.QualifiedName)
        self.raw_frame = await self._add(
            "RawFrame", self._frame(0, 100, 0.0), ua.VariantType.ByteString)
        return self

    async def _add(self, name, value, variant_type, data_type=None):
        kwargs = {"datatype": data_type} if data_type is not None else {}
        return await self.folder.add_variable(
            ua.NodeId(f"DataTypes.{name}", self.idx), ua.QualifiedName(name, self.idx),
            ua.Variant(value, variant_type), **kwargs)

    def _status(self, running, level, current, temperature, mode, alarm, flow, power,
                run_hours):
        return ua.PumpStatus(
            Running=running,
            OperatingLevel=float(level),
            Motor=ua.PumpMotor(Current=float(current), Temperature=float(temperature)),
            Label="Pump01",
            Mode=mode,
            FlowHistory=list(self.flow_history),
            LastService=self.last_service,
            Readings=[ua.PumpReading(Name="flow", Value=float(flow)),
                      ua.PumpReading(Name="power", Value=float(power))],
            # Present only while the pump is in alarm: an absent optional field.
            AlarmText=alarm,
            RunHours=int(run_hours),
        )

    @staticmethod
    def _setpoint(level, alarm):
        sp = ua.PumpSetpoint()
        if alarm:
            sp.Reason = alarm
        else:
            sp.Level = float(level)
        return sp

    @staticmethod
    def _frame(level, filter_state, flow):
        # uint16 level, uint16 filter state, float32 flow -- 8 bytes, big-endian
        return struct.pack(">HHf", int(level), int(filter_state), float(flow))

    def service_done(self):
        """Called on resetFilter / changeOil: LastService moves to now."""
        self.last_service = datetime.now(timezone.utc)

    async def update(self, *, state, level, target_level, flow, power, bearing_temp,
                     inflow_temp, filter_state, run_hours, alarm):
        """Mirror one simulation step of Pump01. `alarm` is the alarm type or None."""
        self.flow_history = self.flow_history[1:] + [round(float(flow), 2)]
        mode = {"Idle": ua.PumpMode.Idle, "Running": ua.PumpMode.Running,
                "Alarm": ua.PumpMode.Alarm}[state]
        # A motor at 230 V: current from the electrical power.
        current = power / 230.0
        status = self._status(running=state == "Running", level=level, current=current,
                              temperature=bearing_temp, mode=mode, alarm=alarm, flow=flow,
                              power=power, run_hours=run_hours)

        def ext(value):
            return ua.DataValue(ua.Variant(value, ua.VariantType.ExtensionObject))

        write = self.server.write_attribute_value
        await write(self.pump_status.nodeid, ext(status))
        await write(self.pump_status_abstract.nodeid, ext(status))
        await write(self.motor.nodeid, ext(ua.PumpMotor(Current=float(current),
                                                         Temperature=float(bearing_temp))))
        await write(self.setpoint.nodeid, ext(self._setpoint(target_level, alarm)))
        await write(self.flow_history_node.nodeid,
                    ua.DataValue(ua.Variant(list(self.flow_history), ua.VariantType.Double)))
        await write(self.temperatures.nodeid,
                    ua.DataValue(ua.Variant([round(float(inflow_temp), 1),
                                             round(float(bearing_temp), 1)],
                                            ua.VariantType.Double)))
        await write(self.last_service_node.nodeid,
                    ua.DataValue(ua.Variant(self.last_service, ua.VariantType.DateTime)))
        await write(self.status_text.nodeid,
                    ua.DataValue(ua.Variant(ua.LocalizedText(state, "en-US"),
                                            ua.VariantType.LocalizedText)))
        code = ALARM_STATUS.get(alarm, ua.StatusCodes.BadUnexpectedError) if alarm \
            else ua.StatusCodes.Good
        await write(self.last_error.nodeid,
                    ua.DataValue(ua.Variant(ua.StatusCode(code), ua.VariantType.StatusCode)))
        await write(self.raw_frame.nodeid,
                    ua.DataValue(ua.Variant(self._frame(level, filter_state, flow),
                                            ua.VariantType.ByteString)))
