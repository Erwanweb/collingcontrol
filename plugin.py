"""
Smart Virtual Thermostat for fan control python plugin for Domoticz
Author: Erwanweb
Version:    0.0.1: alpha
            0.0.2: beta
"""
"""
<plugin key="SVTHW" name="AC Smart Virtual colling control for casaia hardware" author="Erwanweb" version="0.q.1" externallink="https://github.com/Erwanweb/collingcontrol.git">
    <description>
        <h2>Smart Virtual Thermostat for cooling control</h2><br/>
        Easily implement in Domoticz control of the fan of casaia hardware prov4<br/>
        <h3>Set-up and Configuration</h3>
    </description>
    <params>
        <param field="Mode1" label="Hardware Temperature Sensors (csv list of idx)" width="100px" required="true" default="0"/>
<param field="Mode6" label="Logging Level" width="200px">
            <options>
                <option label="Normal" value="Normal"  default="true"/>
                <option label="Verbose" value="Verbose"/>
                <option label="Debug - Python Only" value="2"/>
                <option label="Debug - Basic" value="62"/>
                <option label="Debug - Basic+Messages" value="126"/>
                <option label="Debug - Connections Only" value="16"/>
                <option label="Debug - Connections+Queue" value="144"/>
                <option label="Debug - All" value="-1"/>
            </options>
        </param>
    </params>
</plugin>
"""
import Domoticz
import json
import urllib.parse as parse
import urllib.request as request
from datetime import datetime, timedelta
import time
import base64
import itertools
import os

class deviceparam:

    def __init__(self, unit, nvalue, svalue):
        self.unit = unit
        self.nvalue = nvalue
        self.svalue = svalue


class BasePlugin:

    def __init__(self):

        self.debug = False
        self.ActiveSensors = {}
        self.InTempSensors = []
        self.intemperror = False
        self.intemp = 65.0
        self.setpoint = 50.0
        self.nexttemps = datetime.now()
        self.temptimeout = datetime.now()
        self.cooling = False
        self.autocooling = False
        return


    def onStart(self):

        # setup the appropriate logging level
        try:
            debuglevel = int(Parameters["Mode6"])
        except ValueError:
            debuglevel = 0
            self.loglevel = Parameters["Mode6"]
        if debuglevel != 0:
            self.debug = True
            Domoticz.Debugging(debuglevel)
            DumpConfigToLog()
            self.loglevel = "Verbose"
        else:
            self.debug = False
            Domoticz.Debugging(0)

        # create the child devices if these do not exist yet
        devicecreated = []
        if 1 not in Devices:
            Options = {"LevelActions": "||",
                       "LevelNames": "Off|Auto|Forced",
                       "LevelOffHidden": "false",
                       "SelectorStyle": "0"}
            Domoticz.Device(Name="Cooling mode", Unit=1, TypeName="Selector Switch", Switchtype=18, Image=15,
                            Options=Options, Used=1).Create()
            devicecreated.append(deviceparam(1, 0, "0"))  # default is Off state
        if 2 not in Devices:
            Domoticz.Device(Name="Setpoint", Unit=2, Type=242, Subtype=1, Used=1).Create()
            devicecreated.append(deviceparam(2, 0, "60"))  # default is 60 degrees
        if 3 not in Devices:
            Domoticz.Device(Name="Fan", Unit=3, TypeName="Switch", Image=9).Create()
            devicecreated.append(deviceparam(3, 0, ""))  # default is Off

        # if any device has been created in onStart(), now is time to update its defaults
        for device in devicecreated:
            Devices[device.unit].Update(nValue=device.nvalue, sValue=device.svalue)

        # build lists of sensors and switches
        self.InTempSensors = parseCSV(Parameters["Mode1"])
        Domoticz.Debug("Inside Temperature sensors = {}".format(self.InTempSensors))


        # build dict of status of all temp sensors to be used when handling timeouts
        for sensor in itertools.chain(self.InTempSensors):
            self.ActiveSensors[sensor] = True


    def onStop(self):

        Domoticz.Debugging(0)


    def onCommand(self, Unit, Command, Level, Color):

        Domoticz.Debug("onCommand called for Unit {}: Command '{}', Level: {}".format(Unit, Command, Level))

        if Unit == 1:  # cooling control
            nvalue = 1 if Level > 0 else 0
            svalue = str(Level)
            self.onHeartbeat()

        else:
            nvalue = 1 if Level > 0 else 0
            svalue = str(Level)

        Devices[Unit].Update(nValue=nvalue, sValue=svalue)

    def onHeartbeat(self):

        now = datetime.now()

        self.setpoint = float(Devices[2].sValue)

        # fool proof checking.... based on users feedback
        if not all(device in Devices for device in (1,2,3)):
            Domoticz.Error("one or more devices required by the plugin is/are missing, please check domoticz device creation settings and restart !")
            return

        if Devices[1].sValue == "0":  # Thermostat is off
           if not Devices[3].nValue == 0:
               Devices[3].Update(nValue = 0,sValue = Devices[3].sValue)
               cmd = 'raspi-gpio set 26 op dl'
               os.system(cmd)
               Domoticz.Log("switching cooling off...")
           Domoticz.Log("cooling off - Hardware Temp : {}ºC , fan is off".format(self.intemp))
           self.autocooling = False

        elif Devices[1].sValue == "20":  # Thermostat is in forced mode
            if Devices[3].nValue == 0:
              Devices[3].Update(nValue = 1,sValue = Devices[3].sValue)
              cmd = 'raspi-gpio set 26 op dh'
              os.system(cmd)
              Domoticz.Log("switching cooling on...")
            Domoticz.Log("cooling forced - Hardware Temp : {}ºC , fan is off".format(self.intemp))
            self.autocooling = False

        else:  # thermostart is in auto mode
            self.autocooling = True
            if self.intemp > self.setpoint :
                if not Devices[3].nValue == 1:
                    Devices[3].Update(nValue=1, sValue=Devices[3].sValue)
                    cmd = 'raspi-gpio set 26 op dh'
                    os.system(cmd)
                    Domoticz.Log("switching cooling on...")
                    self.cooling = True

            else:
                if self.intemp < self.setpoint - 15 :
                    if not Devices[3].nValue == 0:
                        Devices[3].Update(nValue=0, sValue=Devices[3].sValue)
                        cmd = 'raspi-gpio set 26 op dl'
                        os.system(cmd)
                        Domoticz.Log("switching cooling off...")
                        self.cooling = False
            if self.cooling :
                Domoticz.Log("cooling Auto - Hardware Temp : {}ºC - Setpoint : {}ºC - Fan is on ".format(self.intemp, self.setpoint))
            else :
                Domoticz.Log("cooling Auto - Hardware Temp : {}ºC - Setpoint : {}ºC - Fan is off ".format(self.intemp, self.setpoint))


        if self.nexttemps <= now:
            # call the Domoticz json API for a temperature devices update, to get the lastest temps (and avoid the
            # connection time out time after 10mins that floods domoticz logs in versions of domoticz since spring 2018)
            self.readTemps()


    def readTemps(self):

        # set update flag for next temp update
        is self.autocooling :
            if not self.cooling :
                self.nexttemps = datetime.now() + timedelta(minutes=1)
            else :
                self.nexttemps = datetime.now() + timedelta(minutes=10)
        else :
            self.nexttemps = datetime.now() + timedelta(minutes=5)
        now = datetime.now()

        # fetch all the devices from the API and scan for sensors
        noerror = True
        listintemps = []
        devicesAPI = DomoticzAPI("type=devices&filter=temp&used=true&order=Name")
        if devicesAPI:
            for device in devicesAPI["result"]:  # parse the devices for temperature sensors
                idx = int(device["idx"])
                if idx in self.InTempSensors:
                    if "Temp" in device:
                        Domoticz.Debug("device: {}-{} = {}".format(device["idx"], device["Name"], device["Temp"]))
                        # check temp sensor is not timed out
                        if not self.SensorTimedOut(idx, device["Name"], device["LastUpdate"]):
                            listintemps.append(device["Temp"])
                    else:
                        Domoticz.Error("device: {}-{} is not a Temperature sensor".format(device["idx"], device["Name"]))

        # calculate the average hardware temperature
        nbtemps = len(listintemps)
        if nbtemps > 0:
            self.intemp = round(sum(listintemps) / nbtemps, 1)
            self.temptimeout = datetime.now() + timedelta(minutes=30)
        else:
            if self.temptimeout <= now:
                Domoticz.Error("No Hardware Temperature found... Switching cooling Off")
                Devices[1].Update(nValue=0, sValue="0")  # switch off the thermostat
                noerror = False

        self.WriteLog("Hardware Temperature = {}".format(self.intemp), "Verbose")
        return noerror



    def WriteLog(self, message, level="Normal"):

        if self.loglevel == "Verbose" and level == "Verbose":
            Domoticz.Log(message)
        elif level == "Normal":
            Domoticz.Log(message)

    def SensorTimedOut(self, idx, name, datestring):

        def LastUpdate(datestring):
            dateformat = "%Y-%m-%d %H:%M:%S"
            # the below try/except is meant to address an intermittent python bug in some embedded systems
            try:
                result = datetime.strptime(datestring, dateformat)
            except TypeError:
                result = datetime(*(time.strptime(datestring, dateformat)[0:6]))
            return result

        timedout = LastUpdate(datestring) + timedelta(minutes=int(Settings["SensorTimeout"])) < datetime.now()

        # handle logging of time outs... only log when status changes (less clutter in logs)
        if timedout:
            if self.ActiveSensors[idx]:
                Domoticz.Error("skipping timed out temperature sensor '{}'".format(name))
                self.ActiveSensors[idx] = False
        else:
            if not self.ActiveSensors[idx]:
                Domoticz.Status("previously timed out temperature sensor '{}' is back online".format(name))
                self.ActiveSensors[idx] = True

        return timedout


global _plugin
_plugin = BasePlugin()


def onStart():
    global _plugin
    _plugin.onStart()


def onStop():
    global _plugin
    _plugin.onStop()


def onCommand(Unit, Command, Level, Color):
    global _plugin
    _plugin.onCommand(Unit, Command, Level, Color)


def onHeartbeat():
    global _plugin
    _plugin.onHeartbeat()


# Plugin utility functions ---------------------------------------------------

def parseCSV(strCSV):

    listvals = []
    for value in strCSV.split(","):
        try:
            val = int(value)
        except:
            pass
        else:
            listvals.append(val)
    return listvals


def DomoticzAPI(APICall):

    resultJson = None
    url = "http://127.0.0.1:8080/json.htm?{}".format(parse.quote(APICall, safe="&="))
    Domoticz.Debug("Calling domoticz API: {}".format(url))
    try:
        req = request.Request(url)
        if Parameters["Username"] != "":
            Domoticz.Debug("Add authentification for user {}".format(Parameters["Username"]))
            credentials = ('%s:%s' % (Parameters["Username"], Parameters["Password"]))
            encoded_credentials = base64.b64encode(credentials.encode('ascii'))
            req.add_header('Authorization', 'Basic %s' % encoded_credentials.decode("ascii"))

        response = request.urlopen(req)
        if response.status == 200:
            resultJson = json.loads(response.read().decode('utf-8'))
            if resultJson["status"] != "OK":
                Domoticz.Error("Domoticz API returned an error: status = {}".format(resultJson["status"]))
                resultJson = None
        else:
            Domoticz.Error("Domoticz API: http error = {}".format(response.status))
    except:
        Domoticz.Error("Error calling '{}'".format(url))
    return resultJson


def CheckParam(name, value, default):

    try:
        param = int(value)
    except ValueError:
        param = default
        Domoticz.Error("Parameter '{}' has an invalid value of '{}' ! defaut of '{}' is instead used.".format(name, value, default))
    return param


# Generic helper functions
def DumpConfigToLog():
    for x in Parameters:
        if Parameters[x] != "":
            Domoticz.Debug("'" + x + "':'" + str(Parameters[x]) + "'")
    Domoticz.Debug("Device count: " + str(len(Devices)))
    for x in Devices:
        Domoticz.Debug("Device:           " + str(x) + " - " + str(Devices[x]))
        Domoticz.Debug("Device ID:       '" + str(Devices[x].ID) + "'")
        Domoticz.Debug("Device Name:     '" + Devices[x].Name + "'")
        Domoticz.Debug("Device nValue:    " + str(Devices[x].nValue))
        Domoticz.Debug("Device sValue:   '" + Devices[x].sValue + "'")
        Domoticz.Debug("Device LastLevel: " + str(Devices[x].LastLevel))
    return
