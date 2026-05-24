import Pyro5.api
import json
import os
import signal
import sys
import threading
import pyRTC.utils as utils
from pyRTC import *

from Pyro5.errors import CommunicationError
import Pyro5.configure
Pyro5.configure.DETAILED_TRACEBACK = True  # allow remote traceback

from pathlib import Path
CONFIG_PATH = Path(__file__).parent.parent / "config"
ICS_URI_PATH = CONFIG_PATH / "pyrtc_uri.txt"
PYRTC_CLASS_PATH = Path(__file__).parent.parent.parent / "pyRTC"
with open(CONFIG_PATH / "ports.json") as f:
    PORTS = json.load(f)

def get_ics_proxy():
    # Each thread will need its own proxy for the ICS.
    with open(ICS_URI_PATH) as f:
        uri = f.read().strip()
    try:
        proxy = Pyro5.api.Proxy(uri)
        # Test the connection
        proxy._pyroBind()
    except CommunicationError:
        raise ConnectionError(f"Could not connect to ICS at {uri}. Is the ICS running?")
    
    return Pyro5.api.Proxy(uri)

@Pyro5.api.expose
class PyroICS:
    """Orchestrates connections to all components. The GUI and other Python
    interfaces should only interact with components through this class, which
    will be exposed through Pyro. This allows the hardware to keep running even
    if the GUI crashes.

    ICS = Instrument Control Server
    """    
    def __init__(self):
        self.components = {
            "wfc": {
                "launcher": None,  # Store launcher object
                "type": None       # Class name of the component
            },
            "wfs": {
                "launcher": None,
                "type": None
            },
            "slopes": {
                "launcher": None,
                "type": None
            },
            "loop": {
                "launcher": None,
                "type": None
            },
            "tel": {
                "launcher": None,
                "type": None
            }
        }

        self.launcher_funcs = {
            "ImakaDM": get_imakadm,
            "DMsim": get_dmsim,
            "FELIXsim": get_felixsim,
            "AndorWFS": get_andor,
            "SlopesProcess": get_slopes,
            "Loop": get_loop,
            "ImakaTelemetry": get_imakatel
        }

        self.errors = {
            0: "Success",
            1: "pyRTC run success",
            2: "Component already exists",
            3: "Component does not exist",
            4: "Invalid component type",
            5: "Failed to launch",
            6: "Shutdown timed out",
            7: "Shutdown encountered an error",
            -1: "pyRTC error while running function"
        }

    def get_available_launchers(self):
        return list(self.launcher_funcs.keys())

    def launch(self, name, component_type):
        if self.components[name]["launcher"] is not None:
            return 2
        if component_type not in self.launcher_funcs:
            return 4
        launcher = self.launcher_funcs[component_type]()
        launcher.launch()
        self.components[name]["launcher"] = launcher
        self.components[name]["type"] = component_type
        return 0
        
    def shutdown(self, name, timeout=5.0):
        print(f"Shutting down {name}")
        component = self.components[name]["launcher"]
        
        result = [None]
        def do_shutdown():
            try:
                result[0] = try_shutdown(component)
            except Exception as e:
                result[0] = e

        t = threading.Thread(target=do_shutdown)
        t.start()
        t.join(timeout=timeout)

        if t.is_alive():
            print(f"\033[91mWARNING: {name} shutdown timed out after {timeout} s.\033[0m")
            self.components[name] = {"launcher": None, "type": None}
            return 6

        if isinstance(result[0], Exception):
            print(f"\033[91mERROR: {name} shutdown failed: {result[0]}\033[0m")
            self.components[name] = {"launcher": None, "type": None}
            return 7

        self.components[name] = {"launcher": None, "type": None}
        del component
        return 0
    
    def shutdown_all(self):
        for name in self.components:
            self.shutdown(name)

    def is_connected(self, name):
        return self.components[name]["launcher"] is not None
        
    def run(self, name, function, *args):
        component = self.components[name]["launcher"]
        comptype = self.components[name]["type"]
        if component is None:
            return 3
        if function in ["setRoi", "setBinning"] and comptype in ["AndorWFS", "FELIXsim"]:
            result = self.run_and_reset_wfs_shms(function, *args)
        else:
            result = component.run(function, *args)
        return result
    
    def get(self, name, property_name):
        component = self.components[name]["launcher"]
        if component is None:
            return 3
        result = component.getProperty(property_name)
        return result
    
    def set(self, name, property_name, value):
        component = self.components[name]["launcher"]
        if component is None:
            return 3
        component.setProperty(property_name, value)
        return 0
    
    def get_type(self, name):
        return self.components[name]["type"]
    
    def run_and_reset_wfs_shms(self, function, *args):
        # For when the WFS image size changes from ROI or binning. This is significantly
        # faster than shutting down all of the components and reconnecting to them.

        # Stop everything (not shut down, just pause)
        for key, val in self.components.items():
            if self.is_connected(key):
                if key == "tel":
                    val["launcher"].run("cancelRecording")  # stop telemetry stream if it's running
                val["launcher"].run("stop")

        # Set the WFS binning or ROI
        clear_shms(["wfs", "wfsRaw", "subApMasks"])
        result = self.components["wfs"]["launcher"].run(function, *args)

        # Reset the WFS SHMs according to the new size
        self.components["wfs"]["launcher"].run("initWFSMemory")  # must do this first
        if self.is_connected("slopes"):
            self.components["slopes"]["launcher"].run("initWFSMemoryFelix")  # slopes depend on wfs size
        # Leave other components - loop does not access the WFS SHM and telemetry
        # reinits it every time it starts a new recording

        # Start again
        for key, val in self.components.items():
            if self.is_connected(key):
                val["launcher"].run("start")

        return result
    
    def reset_shms(self):
        self.shutdown_all()
        shm_names = ["wfs", "wfsRaw", "wfc", "wfc2D", "wfcShape", "signal", "signal2D",
                     "psfShort", "psfLong", "wfsInfo", "loop", "refSlopes", "subApMasks",
                     "cmat", "m2c", "simInjectedSlopes"] #list of SHMs to reset
        clear_shms(shm_names)

def check_config_and_make_launcher(hardware_class, config, port_name):
    # Need to explicilty check these files or the GUI will hang itself
    if not os.path.exists(hardware_class):
        raise FileNotFoundError(f"Hardware class file {hardware_class} not found.")
    if not os.path.exists(config):
        raise FileNotFoundError(f"Config file {config} not found.")
    return hardwareLauncher(hardware_class, config, port=PORTS[port_name])

def get_imakadm():
    hardware_class = PYRTC_CLASS_PATH / "hardware" / "ImakaDM.py"
    config = CONFIG_PATH / "hrtc_wfc.yaml"
    launcher = check_config_and_make_launcher(hardware_class, config, "wfc")
    return launcher

def get_dmsim():
    hardware_class = PYRTC_CLASS_PATH / "hardware" / "DMsim.py"
    config = CONFIG_PATH / "hrtc_wfcsim.yaml"
    launcher = check_config_and_make_launcher(hardware_class, config, "wfc")
    return launcher

def get_felixsim():
    hardware_class = PYRTC_CLASS_PATH / "hardware" / "FELIXsim.py"
    config = CONFIG_PATH / "hrtc_wfs_felixsim.yaml"
    launcher = check_config_and_make_launcher(hardware_class, config, "wfs")
    return launcher

def get_andor():
    hardware_class = PYRTC_CLASS_PATH / "hardware" / "AndorWFS.py"
    config = CONFIG_PATH / "hrtc_wfs_andor.yaml"
    launcher = check_config_and_make_launcher(hardware_class, config, "wfs")
    return launcher

def get_slopes():
    hardware_class = PYRTC_CLASS_PATH / "SlopesProcess.py"
    config = CONFIG_PATH / "hrtc_slopes.yaml"
    launcher = check_config_and_make_launcher(hardware_class, config, "slopes")
    return launcher

def get_loop():
    hardware_class = PYRTC_CLASS_PATH / "Loop.py"
    config = CONFIG_PATH / "hrtc_loop.yaml"
    launcher = check_config_and_make_launcher(hardware_class, config, "loop")
    return launcher

def get_imakatel():
    hardware_class = PYRTC_CLASS_PATH / "ImakaTelemetry.py"
    config = CONFIG_PATH / "hrtc_tel.yaml"
    launcher = check_config_and_make_launcher(hardware_class, config, "tel")
    return launcher

def try_shutdown(component):
    if component is None:
        print("Component is None, skipping shutdown.")
        return
    try:
        component.shutdown()
    except AttributeError:
        print(f"Component {component} cannot be shut down.")

def shutdown_all():
    components = [get_imakatel(), get_loop(), get_slopes(), get_imakadm(), get_andor(),
                  get_dmsim(), get_felixsim()]
    for comp in components:
        try_shutdown(comp)

def reset_shms():
    shm_names = ["wfs", "wfsRaw", "wfc", "wfc2D", "wfcShape", "signal", "signal2D"
                 "psfShort", "psfLong", "wfsInfo", "loop", "refSlopes", "subApMasks",
                 "cmat", "m2c", "simInjectedSlopes"] #list of SHMs to reset
    clear_shms(shm_names)

if __name__ == "__main__":
    ics = PyroICS()
    daemon = Pyro5.api.Daemon()
    uri = daemon.register(ics, objectId="pyrtc.ics")
    with open(ICS_URI_PATH, "w") as f:
        f.write(str(uri))
    print("Pyro ICS is running. URI:", uri)
    daemon.requestLoop()