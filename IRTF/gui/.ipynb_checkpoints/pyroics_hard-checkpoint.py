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
Pyro5.configure.COMMTIMEOUT = 15

from pathlib import Path
CONFIG_PATH = Path(__file__).parent.parent / "config"
ICS_URI_PATH = CONFIG_PATH / "pyrtc_uri.txt"
PYRTC_CLASS_PATH = Path(__file__).parent.parent.parent / "pyRTC"

LAUNCHER_TIMEOUT = 10.0  # seconds to wait for a component to launch before timing out

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
    
    return proxy

@Pyro5.api.expose
class PyroICS:
    """Orchestrates connections to all components. The GUI and other Python
    interfaces should only interact with components through this class, which
    will be exposed through Pyro. This allows the hardware to keep running even
    if the GUI crashes.

    ICS = Instrument Control Server
    """    
    def __init__(self):
        with open(CONFIG_PATH / "irtf_ic.json") as f:
            config = json.load(f)
            self.launchers = config["classes"]
            self.ports = config["ports"]
        
        self.components = {
            "wfc": {"instance": None, "class": None},
            "wfs": {"instance": None, "class": None},
            "slopes": {"instance": None, "class": None},
            "loop": {"instance": None, "class": None},
            "tel": {"instance": None, "class": None}
        }

        # Create an independent Reentrant Lock for each component type
        self._locks = {ctype: threading.RLock() for ctype in self.components}

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
        return list(self.launchers.keys())
    
    def is_connected(self, component_type):
        return self.components[component_type]["instance"] is not None
        
    def launch(self, component_class):
        if component_class not in self.launchers:
            return 4
        component_type = self.launchers[component_class]["type"]
        
        # Serialize launching for this specific component type
        with self._locks[component_type]:
            if self.is_connected(component_type):
                return 2
            
            hardware_class = PYRTC_CLASS_PATH / self.launchers[component_class]["class_path"]
            config_file = CONFIG_PATH / self.launchers[component_class]["config_path"]
            port = self.ports[component_type]
            launcher = check_config_and_make_launcher(hardware_class, config_file, port)                                    
            launcher.launch()

            self.components[component_type]["instance"] = launcher
            self.components[component_type]["class"] = component_class
            return 0
        
    def shutdown(self, name, timeout=5.0):
        if name not in self.components:
            return 4
            
        # Serialize shutdown actions on this specific component
        with self._locks[name]:
            print(f"Shutting down {name}")
            component = self.components[name]["instance"]
            if component is None:
                return 0
            
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
                self.components[name] = {"instance": None, "class": None}
                return 6

            if isinstance(result[0], Exception):
                print(f"\033[91mERROR: {name} shutdown failed: {result[0]}\033[0m")
                self.components[name] = {"instance": None, "class": None}
                return 7

            self.components[name] = {"instance": None, "class": None}
            return 0
    
    def shutdown_all(self):
        # Acquire all locks in a predictable alphabetical order to prevent cross-client deadlocks
        all_locks = [self._locks[k] for k in sorted(self._locks.keys())]
        for lock in all_locks:
            lock.acquire()
        try:
            for name in self.components:
                self.shutdown(name)  # Safe nested acquire because of RLock
        finally:
            for lock in reversed(all_locks):
                lock.release()
        
    def run(self, component_type, function, *args):
        if component_type not in self.components:
            return 4
            
        # Special Multi-Component Modification Case
        if function in ["setRoi", "setBinning"] and component_type == "wfs":
            # Collect all locks alphabetically since run_and_reset_wfs_shms cascades across components
            all_locks = [self._locks[k] for k in sorted(self._locks.keys())]
            for lock in all_locks:
                lock.acquire()
            try:
                return self.run_and_reset_wfs_shms(function, *args)
            finally:
                for lock in reversed(all_locks):
                    lock.release()

        # Normal isolated execution
        with self._locks[component_type]:
            component = self.components[component_type]["instance"]
            if component is None:
                return 3
            return component.run(function, *args)
    
    def get(self, component_type, property_name):
        if component_type not in self.components:
            return 4
        with self._locks[component_type]:
            component = self.components[component_type]["instance"]
            if component is None:
                return 3
            return component.getProperty(property_name)
    
    def set(self, component_type, property_name, value):
        if component_type not in self.components:
            return 4
        with self._locks[component_type]:
            component = self.components[component_type]["instance"]
            if component is None:
                return 3
            component.setProperty(property_name, value)
            return 0
    
    def get_component_class(self, component_type):
        return self.components[component_type]["class"]
    
    def run_and_reset_wfs_shms(self, function, *args):
        # For when the WFS image size changes from ROI or binning. This is significantly
        # faster than shutting down all of the components and reconnecting to them.

        # Stop everything (not shut down, just pause)
        for ctype, val in self.components.items():
            if self.is_connected(ctype):
                if ctype == "tel":
                    val["instance"].run("cancelRecording")  # stop telemetry stream if it's running
                val["instance"].run("stop")

        # Set the WFS binning or ROI
        self.reset_wfs_shms()  # clear the WFS SHMs before changing the size to prevent issues with mismatched sizes
        result = self.components["wfs"]["instance"].run(function, *args)

        # Reset the WFS SHMs according to the new size
        self.components["wfs"]["instance"].run("initWFSMemory")  # must do this first
        if self.is_connected("slopes"):
            self.components["slopes"]["instance"].run("initWFSMemoryFelix")  # slopes depend on wfs size

        # Start again
        for key, val in self.components.items():
            if self.is_connected(key):
                val["instance"].run("start")

        return result
    
    def reset_shms(self, shm_names=None):
        if shm_names is None:
            shm_names = ["wfs", "wfsRaw", "wfc", "wfc2D", "wfcShape", "signal", "signal2D",
                         "psfShort", "psfLong", "wfsInfo", "loop", "refSlopes", "subApMasks",
                         "cmat", "m2c", "simInjectedSlopes"]  #list of SHMs to reset
        clear_shms(shm_names)

    def reset_wfs_shms(self):
        # Resets all shared memories dependent on WFS image size
        self.reset_shms(["wfs", "wfsRaw", "subApMasks"])

def check_config_and_make_launcher(hardware_class, config, port):
    if not os.path.exists(hardware_class):
        raise FileNotFoundError(f"Hardware class file {hardware_class} not found.")
    if not os.path.exists(config):
        raise FileNotFoundError(f"Config file {config} not found.")
    return hardwareLauncher(hardware_class, config, port, timeout=LAUNCHER_TIMEOUT)

def try_shutdown(component):
    if component is None:
        print("Component is None, skipping shutdown.")
        return
    try:
        component.shutdown()
    except AttributeError:
        print(f"Component {component} cannot be shut down.")

if __name__ == "__main__":
    ics = PyroICS()
    daemon = Pyro5.api.Daemon()
    uri = daemon.register(ics, objectId="pyrtc_soft.ics")
    with open(ICS_URI_PATH, "w") as f:
        f.write(str(uri))
    print("Pyro ICS is running. URI:", uri)

    def handler(sig, frame):
        ics.shutdown_all()
        exit(0)

    signal.signal(signal.SIGINT, handler)

    daemon.requestLoop()