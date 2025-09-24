import asyncio
import copy
import logging
import random
import os
import math
from datetime import datetime
import time
from math import sin

from asyncua import ua, uamethod, Server


_logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')


class SubHandler(object):
    """
    Subscription Handler. To receive events from server for a subscription
    """

    def datachange_notification(self, node, val, data):
        _logger.warning("Python: New data change event %s %s", node, val)

    def event_notification(self, event):
        _logger.warning("Python: New event %s", event)


class PumpController:
    """
    Class to handle pump control and state
    """
    def __init__(self):
        # Get configuration from environment variables with defaults
        self.default_operating_level = int(os.environ.get("PUMP_DEFAULT_OPERATING_LEVEL", 75))
        # Set the pump to start at default operating level
        self.target_level = self.default_operating_level
        
        # Get filter degradation rate from environment (minutes to clog at full load)
        filter_degradation_minutes = int(os.environ.get("PUMP_FILTER_DEGRADATION_RATE", 30))
        
        # Set the default filter degradation rate
        self.filter_degradation_base_rate = 0.1  # Minimal degradation even at idle
        # Calculate load factor based on environment variable
        self.filter_degradation_load_factor = (100.0 / filter_degradation_minutes) - self.filter_degradation_base_rate
        
        # Track the last command executed
        self.last_command = "None"
        self.command_success = True
        # Alarm state tracking
        self.in_alarm_state = False
        self.alarm_start_time = 0
        self.previous_target_level = 0  # Store level before alarm
        self.auto_reset_minutes = float(os.environ.get("PUMP_AUTO_RESET_MINUTES", 3.0))  # Minutes until auto-reset
        
        # Oil parameters
        self.oil_change_hours = int(os.environ.get("PUMP_OIL_CHANGE_HOURS", 2000))  # Run hours until oil change needed
        
        # Temperature parameters
        self.min_inflow_temp = float(os.environ.get("PUMP_MIN_INFLOW_TEMP", 15.0))  # °C
        self.max_inflow_temp = float(os.environ.get("PUMP_MAX_INFLOW_TEMP", 25.0))  # °C
        self.base_bearing_temp = float(os.environ.get("PUMP_BASE_BEARING_TEMP", 35.0))  # °C
        self.max_bearing_temp = float(os.environ.get("PUMP_MAX_BEARING_TEMP", 80.0))  # °C
        
        # Log the configuration
        _logger.info(f"Pump configured with: operating level={self.default_operating_level}%, "
                    f"filter degradation={filter_degradation_minutes} minutes, "
                    f"auto-reset={self.auto_reset_minutes} minutes, "
                    f"oil change={self.oil_change_hours} hours")

    def stop_pump(self):
        _logger.info("Stop command processing")
        self.target_level = 0
        self.last_command = "stopPump"
        self.command_success = True
        return True

    def start_pump(self):
        _logger.info("Start command processing")
        self.target_level = self.default_operating_level
        self.last_command = "startPump"
        self.command_success = True
        return True

    def set_operating_level(self, level):
        if 0 <= level <= 100:
            _logger.info(f"Setting operating level to {level}")
            self.target_level = level
            self.last_command = f"setOperatingLevel({level})"
            self.command_success = True
            return level
        else:
            _logger.warning(f"Invalid operating level requested: {level}")
            self.last_command = f"setOperatingLevel({level})"
            self.command_success = False
            return -1
            
    def set_filter_degradation_rate(self, minutes_to_clog):
        """Set how quickly the filter gets clogged (in minutes to reach 0%)"""
        if minutes_to_clog <= 0:
            _logger.warning(f"Invalid filter degradation rate: {minutes_to_clog}")
            self.last_command = f"setFilterDegradationRate({minutes_to_clog})"
            self.command_success = False
            return False
            
        # Calculate the degradation rate per minute
        # At 100% load, we want the filter to go from 100% to 0% in minutes_to_clog minutes
        self.filter_degradation_base_rate = 0.1  # Minimal degradation even at idle
        
        # The rate at full load should achieve the desired minutes_to_clog
        # Formula: (100% / minutes_to_clog) - base_rate
        self.filter_degradation_load_factor = (100.0 / minutes_to_clog) - self.filter_degradation_base_rate
        
        _logger.info(f"Filter will now clog in approximately {minutes_to_clog} minutes at full load")
        self.last_command = f"setFilterDegradationRate({minutes_to_clog})"
        self.command_success = True
        return True
        
    def set_auto_reset_minutes(self, minutes):
        """Set how long the pump stays in alarm state before auto-resetting"""
        if minutes <= 0:
            _logger.warning(f"Invalid auto-reset minutes: {minutes}")
            self.last_command = f"setAutoResetMinutes({minutes})"
            self.command_success = False
            return False
            
        self.auto_reset_minutes = float(minutes)
        _logger.info(f"Auto-reset time set to {minutes} minutes")
        self.last_command = f"setAutoResetMinutes({minutes})"
        self.command_success = True
        return True
        
    def reset_filter(self):
        """Manually reset the filter (as if it was replaced)"""
        self.last_command = "resetFilter"
        self.command_success = True
        return True
        
    def change_oil(self):
        """Manually change the pump oil"""
        self.last_command = "changeOil"
        self.command_success = True
        return True
        
    def enter_alarm_state(self, alarm_type):
        """Put the pump in alarm state"""
        if not self.in_alarm_state:
            _logger.info(f"Entering alarm state: {alarm_type}")
            self.in_alarm_state = True
            self.alarm_start_time = time.time()
            self.previous_target_level = self.target_level
            self.target_level = 0  # Stop the pump
            
    def check_alarm_auto_reset(self):
        """Check if it's time to auto-reset from alarm state"""
        if not self.in_alarm_state:
            return False
            
        # Check if the auto-reset time has elapsed
        elapsed_minutes = (time.time() - self.alarm_start_time) / 60
        if elapsed_minutes >= self.auto_reset_minutes:
            _logger.info(f"Auto-resetting pump after {elapsed_minutes:.1f} minutes in alarm state")
            self.in_alarm_state = False
            self.target_level = self.previous_target_level  # Restore previous target level
            return True
            
        return False


# Create controller instance for method callbacks
pump_controller = PumpController()

# Get update interval from environment with a default of 2.0 seconds
update_interval = float(os.environ.get("PUMP_UPDATE_INTERVAL", 2.0))
_logger.info(f"Initial update interval set to {update_interval} seconds")

# Method to stop the pump
@uamethod
def stop_pump(parent):
    _logger.warning("Stop pump method called")
    return pump_controller.stop_pump()


# Method to start the pump at default level
@uamethod
def start_pump(parent):
    _logger.warning("Start pump method called")
    return pump_controller.start_pump()


# Method to set the pump's operating level
@uamethod
def set_operating_level(parent, level):
    _logger.warning(f"Set operating level method called with level: {level}")
    return pump_controller.set_operating_level(level)


# Method to configure filter degradation rate
@uamethod
def set_filter_degradation_rate(parent, minutes_to_clog):
    _logger.warning(f"Set filter degradation rate called with: {minutes_to_clog} minutes")
    return pump_controller.set_filter_degradation_rate(minutes_to_clog)


# Method to configure auto-reset minutes
@uamethod
def set_auto_reset_minutes(parent, minutes):
    _logger.warning(f"Set auto-reset minutes called with: {minutes} minutes")
    return pump_controller.set_auto_reset_minutes(minutes)


# Method to manually reset the filter
@uamethod
def reset_filter(parent):
    _logger.warning("Reset filter method called")
    return pump_controller.reset_filter()


# Method to manually change the oil
@uamethod
def change_oil(parent):
    _logger.warning("Change oil method called")
    return pump_controller.change_oil()


# Method to set the update interval
@uamethod
def set_update_interval(parent, seconds):
    global update_interval
    if seconds < 0.1:
        _logger.warning(f"Invalid update interval requested: {seconds} (must be ≥ 0.1)")
        return False
    if seconds > 60:
        _logger.warning(f"Invalid update interval requested: {seconds} (must be ≤ 60)")
        return False
    
    update_interval = float(seconds)
    _logger.info(f"Update interval set to {update_interval} seconds")
    return True


async def main():
    server = Server()
    await server.init()
    server.historize_node_data_changes = True
    server.set_endpoint("opc.tcp://0.0.0.0:4840/")
    server.set_server_name("Cumulocity Demo OPC UA Server")
    server.set_security_policy(
        [
            ua.SecurityPolicyType.NoSecurity,
            ua.SecurityPolicyType.Basic256Sha256_SignAndEncrypt,
            ua.SecurityPolicyType.Basic256Sha256_Sign,
        ]
    )

    # setup our own namespace
    uri = "http://www.cumulocity.com"
    idx = await server.register_namespace(uri)

    # Create a server configuration object
    server_config = await server.nodes.objects.add_object(idx, "ServerConfig")
    
    # Add update interval variable to server configuration
    update_interval_var = await server_config.add_variable(idx, "updateInterval", update_interval)
    await update_interval_var.set_writable()
    
    # Add method to set update interval to server configuration
    await server_config.add_method(
        idx,
        "setUpdateInterval",
        set_update_interval,
        [ua.VariantType.Double],  # seconds
        [ua.VariantType.Boolean]  # success/failure
    )

    # populating our address space
    # Defining pump01 (the main pump with all functionality)
    pump01 = await server.nodes.objects.add_object(idx, "Pump01")
    # operating Level of pump in %
    performance = await pump01.add_variable(idx, "operatingLevel", 100)
    await performance.set_writable()
    # statuses are: Idle, Running, Alarm
    status = await pump01.add_variable(idx, "status", "Idle", ua.VariantType.String)
    await status.set_writable()
    # flow in l/s
    flow = await pump01.add_variable(idx, "flow", 5.0)
    await flow.set_writable()
    # Alarms could be: "PowerFailure", "Leakage", "FilterClogged"
    alarm = await pump01.add_variable(idx, "activeAlarm", 0)
    await alarm.set_writable()
    # Current Energy consumption in W
    power = await pump01.add_variable(idx, "power", 450)
    await power.set_writable()
    # Run hours in h
    run_hours = await pump01.add_variable(idx, "runHours", 0)
    await run_hours.set_writable()
    
    # Add filter state as percentage (100% = clean, 0% = completely clogged)
    filter_state = await pump01.add_variable(idx, "filterState", 100)
    await filter_state.set_writable()
    
    # Add oil level as percentage (100% = full, 0% = empty)
    oil_level = await pump01.add_variable(idx, "oilLevel", 100)
    await oil_level.set_writable()
    
    # Add inflow temperature in °C
    inflow_temperature = await pump01.add_variable(idx, "inflowTemperature", 20.0)
    await inflow_temperature.set_writable()
    
    # Add bearing temperature in °C
    bearing_temperature = await pump01.add_variable(idx, "bearingTemperature", 35.0)
    await bearing_temperature.set_writable()
    
    # Add alarm time remaining (seconds until auto-reset)
    alarm_time_remaining = await pump01.add_variable(idx, "alarmTimeRemaining", 0)
    await alarm_time_remaining.set_writable()
    
    # Add command feedback variables to track last command execution
    last_command = await pump01.add_variable(idx, "lastCommand", "None", ua.VariantType.String)
    await last_command.set_writable()
    
    command_success = await pump01.add_variable(idx, "commandSuccess", True, ua.VariantType.Boolean)
    await command_success.set_writable()
    
    # Add filter degradation rate in minutes (time to clog at full load)
    filter_degradation_rate = await pump01.add_variable(idx, "filterDegradationRate", 30)
    await filter_degradation_rate.set_writable()
    
    # Add auto-reset minutes configuration
    auto_reset_minutes = await pump01.add_variable(idx, "autoResetMinutes", pump_controller.auto_reset_minutes)
    await auto_reset_minutes.set_writable()
    
    # Add default operating level configuration
    default_operating_level = await pump01.add_variable(idx, "defaultOperatingLevel", pump_controller.default_operating_level)
    await default_operating_level.set_writable()
    
    # Add methods to control the pump
    await pump01.add_method(
        idx, 
        "stopPump", 
        stop_pump, 
        [], 
        [ua.VariantType.Boolean]
    )
    
    await pump01.add_method(
        idx, 
        "startPump", 
        start_pump, 
        [], 
        [ua.VariantType.Boolean]
    )
    
    await pump01.add_method(
        idx,
        "setOperatingLevel",
        set_operating_level,
        [ua.VariantType.Int64],
        [ua.VariantType.Int64]
    )
    
    # Add method to configure filter degradation rate
    await pump01.add_method(
        idx,
        "setFilterDegradationRate",
        set_filter_degradation_rate,
        [ua.VariantType.Int64],  # minutes to clog
        [ua.VariantType.Boolean]  # success/failure
    )
    
    # Add method to configure auto-reset minutes
    await pump01.add_method(
        idx,
        "setAutoResetMinutes",
        set_auto_reset_minutes,
        [ua.VariantType.Double],  # minutes
        [ua.VariantType.Boolean]  # success/failure
    )
    
    # Add method to manually reset the filter
    await pump01.add_method(
        idx,
        "resetFilter",
        reset_filter,
        [],
        [ua.VariantType.Boolean]
    )
    
    # Add method to manually change the oil
    await pump01.add_method(
        idx,
        "changeOil",
        change_oil,
        [],
        [ua.VariantType.Boolean]
    )

    # Add Pump02 (dummy pump with static values)
    pump02 = await server.nodes.objects.add_object(idx, "Pump02")
    await pump02.add_variable(idx, "operatingLevel", 85)
    await pump02.add_variable(idx, "status", "Running", ua.VariantType.String)
    await pump02.add_variable(idx, "flow", 4.2)
    await pump02.add_variable(idx, "activeAlarm", 0)
    await pump02.add_variable(idx, "power", 380)
    await pump02.add_variable(idx, "runHours", 120)
    await pump02.add_variable(idx, "filterState", 92)
    await pump02.add_variable(idx, "oilLevel", 93)
    await pump02.add_variable(idx, "inflowTemperature", 21.5)
    await pump02.add_variable(idx, "bearingTemperature", 37.2)
    await pump02.add_variable(idx, "lastCommand", "None", ua.VariantType.String)
    await pump02.add_variable(idx, "commandSuccess", True, ua.VariantType.Boolean)

    # Add Pump03 (dummy pump with static values)
    pump03 = await server.nodes.objects.add_object(idx, "Pump03")
    await pump03.add_variable(idx, "operatingLevel", 65)
    await pump03.add_variable(idx, "status", "Running", ua.VariantType.String)
    await pump03.add_variable(idx, "flow", 3.5)
    await pump03.add_variable(idx, "activeAlarm", 0)
    await pump03.add_variable(idx, "power", 320)
    await pump03.add_variable(idx, "runHours", 250)
    await pump03.add_variable(idx, "filterState", 78)
    await pump03.add_variable(idx, "oilLevel", 85)
    await pump03.add_variable(idx, "inflowTemperature", 19.8)
    await pump03.add_variable(idx, "bearingTemperature", 39.5)
    await pump03.add_variable(idx, "lastCommand", "None", ua.VariantType.String)
    await pump03.add_variable(idx, "commandSuccess", True, ua.VariantType.Boolean)

    # starting!
    async with server:
        print("Available loggers are: ", logging.Logger.manager.loggerDict.keys())
        _logger.info("Server started with environment-based configuration")
        # enable following if you want to subscribe to nodes on server side
        # handler = SubHandler()
        # sub = await server.create_subscription(500, handler)
        # handle = await sub.subscribe_data_change(flow)
        runHoursValue = 0
        # Add pump simulation state variables
        pumpState = "Idle"
        currentLevel = 0
        leakageProbability = 0.001
        filterStateValue = 100
        oilLevelValue = 100
        
        # Temperature simulation variables
        inflowTempValue = 20.0
        bearingTempValue = pump_controller.base_bearing_temp
        
        # Create a time-based cycle for temperature variation
        cycle_start_time = time.time()
        temp_cycle_hours = 24  # 24-hour temperature cycle
        
        while True:
            # Use the configurable update interval
            await asyncio.sleep(update_interval)
            
            # Update the update_interval variable in OPC UA
            await server.write_attribute_value(
                update_interval_var.nodeid, ua.DataValue(update_interval)
            )
            
            # Check if we should auto-reset from alarm state
            if pump_controller.check_alarm_auto_reset():
                _logger.info("Auto-reset activated: clearing alarm and resetting filter")
                filterStateValue = 100  # Reset filter to 100% clean
            
            # Get target level from the controller
            targetLevel = pump_controller.target_level
            
            # Gradually approach target level with realistic ramp-up/down
            if currentLevel < targetLevel:
                currentLevel = min(targetLevel, currentLevel + random.randint(1, 5))
            elif currentLevel > targetLevel:
                currentLevel = max(targetLevel, currentLevel - random.randint(1, 3))
            
            # Determine pump state based on operating level
            if pump_controller.in_alarm_state:
                pumpState = "Alarm"
            elif currentLevel == 0:
                pumpState = "Idle"
            else:
                pumpState = "Running"
            
            # Handle manual filter reset
            if pump_controller.last_command == "resetFilter" and pump_controller.command_success:
                _logger.info("Manually resetting filter to 100%")
                filterStateValue = 100
                # Reset the command to avoid multiple resets
                pump_controller.last_command = "None"
            
            # Handle manual oil change
            if pump_controller.last_command == "changeOil" and pump_controller.command_success:
                _logger.info("Manually changing oil to 100%")
                oilLevelValue = 100
                # Reset the command to avoid multiple changes
                pump_controller.last_command = "None"
            
            # Filter gets gradually clogged with usage - using configurable degradation rate
            if currentLevel > 0:
                # Convert the per-minute rate to per-second
                base_rate_per_second = pump_controller.filter_degradation_base_rate / 60.0
                load_factor_per_second = pump_controller.filter_degradation_load_factor / 60.0
                
                # Calculate degradation based on current load and configured rates - scale by update_interval
                degradation_rate = (base_rate_per_second + (currentLevel / 100.0) * load_factor_per_second) * update_interval
                filterStateValue = max(0, filterStateValue - degradation_rate)
            
            # Oil level decreases over time when pump is running
            if pumpState == "Running":
                # Oil depletes based on operating level and run time
                # At 100% operating level, oil should last for oil_change_hours
                oil_depletion_per_hour = 100.0 / pump_controller.oil_change_hours
                oil_depletion_per_second = oil_depletion_per_hour / 3600.0
                
                # Adjust depletion based on operating level (higher level = faster depletion)
                # Scale by update_interval to account for varying update rates
                oil_depletion = oil_depletion_per_second * (0.5 + currentLevel / 200.0) * update_interval
                
                # Apply oil depletion
                oilLevelValue = max(0, oilLevelValue - oil_depletion)
            
            # Calculate inflow temperature variation based on time
            # Create a sinusoidal variation over the course of the day
            hours_since_start = (time.time() - cycle_start_time) / 3600
            cycle_position = (hours_since_start % temp_cycle_hours) / temp_cycle_hours
            temp_amplitude = (pump_controller.max_inflow_temp - pump_controller.min_inflow_temp) / 2
            temp_midpoint = (pump_controller.max_inflow_temp + pump_controller.min_inflow_temp) / 2
            
            # Sinusoidal temperature variation with some randomness
            inflowTempValue = temp_midpoint + temp_amplitude * math.sin(cycle_position * 2 * math.pi)
            # Add small random variations
            inflowTempValue += random.uniform(-0.5, 0.5)
            
            # Calculate bearing temperature based on operating level, oil level, and filter state
            # Start with a base temperature when idle
            if currentLevel == 0:
                # Bearing cools down slowly when pump is idle - scale by update_interval
                bearing_cool_rate = 0.2 * update_interval
                bearingTempValue = max(
                    pump_controller.base_bearing_temp,
                    bearingTempValue - bearing_cool_rate
                )
            else:
                # Temperature increases with operating level
                level_factor = currentLevel / 100.0
                
                # Low oil increases bearing temperature
                oil_factor = 1.0 + max(0, (1.0 - oilLevelValue / 100.0) * 0.5)
                
                # Clogged filter increases bearing temperature
                filter_factor = 1.0 + max(0, (1.0 - filterStateValue / 100.0) * 0.3)
                
                # Calculate target temperature based on factors
                target_bearing_temp = pump_controller.base_bearing_temp + (
                    (pump_controller.max_bearing_temp - pump_controller.base_bearing_temp) * 
                    level_factor * oil_factor * filter_factor
                )
                
                # Add small random variations
                target_bearing_temp += random.uniform(-0.2, 0.2)
                
                # Approach target temperature gradually - scale by update_interval
                if bearingTempValue < target_bearing_temp:
                    bearing_heat_rate = 0.3 * update_interval
                    bearingTempValue = min(target_bearing_temp, bearingTempValue + bearing_heat_rate)
                else:
                    bearing_cool_rate = 0.1 * update_interval
                    bearingTempValue = max(target_bearing_temp, bearingTempValue - bearing_cool_rate)
            
            # Determine if an alarm condition exists
            alarmValue = 0
            alarmType = ""
            
            # Filter clogged alarm
            if filterStateValue < 20 and not pump_controller.in_alarm_state:
                alarmValue = 1
                alarmType = "FilterClogged"
                pump_controller.enter_alarm_state(alarmType)
            
            # Oil level alarm
            if oilLevelValue < 15 and not pump_controller.in_alarm_state:
                alarmValue = 1
                alarmType = "OilLow"
                pump_controller.enter_alarm_state(alarmType)
            
            # Bearing temperature alarm
            if bearingTempValue > 75 and not pump_controller.in_alarm_state:
                alarmValue = 1
                alarmType = "BearingOverheated"
                pump_controller.enter_alarm_state(alarmType)
            
            # Random power failure - scale probability by update_interval
            if random.random() < (0.002 * update_interval) and not pump_controller.in_alarm_state:
                alarmValue = 1
                alarmType = "PowerFailure"
                pump_controller.enter_alarm_state(alarmType)
            
            # Leakage probability increases with lower filter state - scale by update_interval
            leakageChance = leakageProbability * (1 + (100 - filterStateValue)/20) * update_interval
            if random.random() < leakageChance and not pump_controller.in_alarm_state:
                alarmValue = 1
                alarmType = "Leakage"
                pump_controller.enter_alarm_state(alarmType)
            
            # Calculate alarm time remaining
            alarm_remaining_seconds = 0
            if pump_controller.in_alarm_state:
                elapsed_seconds = time.time() - pump_controller.alarm_start_time
                total_seconds = pump_controller.auto_reset_minutes * 60
                alarm_remaining_seconds = max(0, total_seconds - elapsed_seconds)
                alarmValue = 1  # Ensure alarm is active if in alarm state
            
            # Calculate flow based on operating level with some natural variation
            maxFlowRate = 10.0
            # As filter clogs, flow rate decreases (down to 50% of normal)
            filterFactor = 0.5 + (filterStateValue / 100) * 0.5
            baseFlow = (currentLevel / 100) * maxFlowRate * filterFactor
            flowValue = max(0, baseFlow * random.uniform(0.95, 1.05))
            
            # Calculate power consumption based on operating level, flow rate and pump state
            basePower = 100
            if currentLevel > 0:
                # Calculate efficiency factor - decreases as filter clogs
                # A clogged filter (0%) can make the pump up to 100% less efficient (2x power)
                efficiency_factor = 1 + (1 - filterStateValue / 100) * 1.0  # 1.0-2.0 range
                
                # Base power depends on operating level
                level_power = currentLevel * 5
                
                # Calculate increased power due to back-pressure from clogged filter
                # More clogged = higher back-pressure = more power needed
                clogging_resistance = (100 - filterStateValue) / 100  # 0-1 range
                clogging_power = level_power * clogging_resistance * 2  # Up to 2x additional power
                
                # Total power with some random variation
                powerValue = (basePower + level_power * efficiency_factor + clogging_power) * random.uniform(0.95, 1.05)
            else:
                powerValue = 0
                
            # Increment run hours only when pump is actually running
            # Scale by update_interval (convert to hours)
            if pumpState == "Running":
                runHoursValue += (update_interval / 3600) *12
            
            # Calculate current filter degradation rate in minutes (for display)
            current_degradation_rate = 30  # Default value
            if pump_controller.filter_degradation_load_factor > 0:
                current_degradation_rate = int(100.0 / (pump_controller.filter_degradation_base_rate + 
                                                      pump_controller.filter_degradation_load_factor))
            
            # Write values to OPC UA server (only for Pump01)
            await server.write_attribute_value(
                power.nodeid, ua.DataValue(int(powerValue))
            )
            await server.write_attribute_value(
                status.nodeid, ua.DataValue(pumpState)
            )
            await server.write_attribute_value(
                flow.nodeid, ua.DataValue(float(flowValue))
            )
            await server.write_attribute_value(
                run_hours.nodeid, ua.DataValue(int(runHoursValue))
            )
            await server.write_attribute_value(
                alarm.nodeid, ua.DataValue(int(alarmValue))
            )
            await server.write_attribute_value(
                performance.nodeid, ua.DataValue(int(currentLevel))
            )
            await server.write_attribute_value(
                filter_state.nodeid, ua.DataValue(int(filterStateValue))
            )
            await server.write_attribute_value(
                oil_level.nodeid, ua.DataValue(int(oilLevelValue))
            )
            await server.write_attribute_value(
                inflow_temperature.nodeid, ua.DataValue(float(round(inflowTempValue, 1)))
            )
            await server.write_attribute_value(
                bearing_temperature.nodeid, ua.DataValue(float(round(bearingTempValue, 1)))
            )
            await server.write_attribute_value(
                alarm_time_remaining.nodeid, ua.DataValue(int(alarm_remaining_seconds))
            )
            await server.write_attribute_value(
                filter_degradation_rate.nodeid, ua.DataValue(int(current_degradation_rate))
            )
            await server.write_attribute_value(
                auto_reset_minutes.nodeid, ua.DataValue(float(pump_controller.auto_reset_minutes))
            )
            await server.write_attribute_value(
                default_operating_level.nodeid, ua.DataValue(int(pump_controller.default_operating_level))
            )
            
            # Update command status variables
            await server.write_attribute_value(
                last_command.nodeid, ua.DataValue(pump_controller.last_command)
            )
            await server.write_attribute_value(
                command_success.nodeid, ua.DataValue(pump_controller.command_success)
            )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())