"""Uses soft RTC mode to run all components in a single process. This works up
to frame rates of 190 Hz. It's easier to debug and does not slow down when running
commands that take many frames to execute (e.g., takeRefSlopes).
"""
import Pyro5.api
import json
import os
import signal
import sys
import threading
import importlib.util
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
class PyroICSSoft:
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
        
        self.components = {
            "wfc": {                # For soft RTC, component type *must* match the key at the top of the config file
                "instance": None,   # Store launcher object
                "class": None       # Class name of the component
            },
            "wfs": { "instance": None, "class": None },
            "slopes": { "instance": None, "class": None },
            "loop": { "instance": None, "class": None },
            "tel": { "instance": None, "class": None },
        }

        # Create an independent Reentrant Lock for each component type to
        # prevent multiple clients from trying to access the same component
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
            8: "Invalid key",
            -1: "pyRTC error while running function"
        }

        self.ao_cals = {
            "imat" : {
                "theor_file": None,
                "synth_file": None
            },
            "ncpa": {
                "ra_target": None,
                "dec_target": None,
                "ra_guide": None,
                "auto_offsets": [0, 0, 0, 0, 0, 0, 0],
                "user_offsets": [0, 0, 0, 0, 0, 0, 0]
            }
        }

    def get_aocals(self):
        return self.ao_cals
    
    def set_aocals(self, key, subkey, value):
        if key in self.ao_cals and subkey in self.ao_cals[key]:
            self.ao_cals[key][subkey] = value
            return 0
        else:
            return 8
    
    def get_available_launchers(self):
        return list(self.launchers.keys())
    
    def is_connected(self, component_type):
        return self.components[component_type]["instance"] is not None
        
    def launch(self, component_class):
        if component_class not in self.launchers:
            return 4, self.errors[4]
        component_type = self.launchers[component_class]["type"]
        
        # Guard component creation
        with self._locks[component_type]:
            if self.is_connected(component_type):
                return 2, self.errors[2]
            
            hardware_class = PYRTC_CLASS_PATH / self.launchers[component_class]["class_path"]
            config_file = CONFIG_PATH / self.launchers[component_class]["config_path"]
            conf = utils.read_yaml_file(config_file)[component_type]
            instance = instantiate_component(component_class, hardware_class, conf)                                    

            self.components[component_type]["instance"] = instance
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
        # To safely lock everything without deadlocking, acquire all locks in a fixed alphabetical order
        all_locks = [self._locks[k] for k in sorted(self._locks.keys())]
        for lock in all_locks: 
            lock.acquire()
        try:
            for name in self.components:
                self.shutdown(name) # Safe because of RLock
        finally:
            for lock in reversed(all_locks): 
                lock.release()

    def _soft_run(self, component, function, *args):
        func_to_run = getattr(component, function, lambda: -1)
        try:
            result = func_to_run(*args)
        except TypeError:
            print(f"Function {function} not found in component {component}, or passed wrong number of arguments.")
            return -1
        except Exception as e:
            print(f"Error while running {function} on {component}: {e}")
            return -1
        return result

    @Pyro5.api.oneway
    def run_no_wait(self, component_type, function, *args):
        self.run(component_type, function, *args)

    def run(self, component_type, function, *args):
        if component_type not in self.components:
            return 4
            
        # Special Case: Global State Modification
        if function in ["setRoi", "setBinning"] and component_type == "wfs":
            # This method acts on multiple components, so it must capture ALL locks 
            # in a predictable sorted order to prevent cross-client deadlocks.
            all_locks = [self._locks[k] for k in sorted(self._locks.keys())]
            for lock in all_locks: 
                lock.acquire()
            try:
                return self.run_and_reset_wfs_shms(function, *args)
            finally:
                for lock in reversed(all_locks): 
                    lock.release()

        # Normal Case: Single component target
        with self._locks[component_type]:
            component = self.components[component_type]["instance"]
            if component is None:
                return 3
            return self._soft_run(component, function, *args)
    
    def get(self, component_type, property_name):
        if component_type not in self.components:
            return 4
        with self._locks[component_type]:
            component = self.components[component_type]["instance"]
            if component is None:
                return 3
            result = getattr(component, property_name, -1)
            # convert to list if it's a numpy array for Pyro serialization
            if isinstance(result, np.ndarray):
                return result.tolist()
            return result
    
    def set(self, component_type, property_name, value):
        if component_type not in self.components:
            return 4
        with self._locks[component_type]:
            component = self.components[component_type]["instance"]
            if component is None:
                return 3
            setattr(component, property_name, value)
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
                    self._soft_run(val["instance"], "cancelRecording")  # stop telemetry stream if it's running
                self._soft_run(val["instance"], "stop")

        # Set the WFS binning or ROI
        self.reset_wfs_shms()  # clear the WFS SHMs before changing the size to prevent issues with mismatched sizes
        result = self._soft_run(self.components["wfs"]["instance"], function, *args)

        # Reset the WFS SHMs according to the new size
        self._soft_run(self.components["wfs"]["instance"], "initWFSMemory")  # must do this first
        if self.is_connected("slopes"):
            self._soft_run(self.components["slopes"]["instance"], "initWFSMemoryFelix")  # slopes depend on wfs size
        # Leave other components - loop does not access the WFS SHM and telemetry
        # reinits it every time it starts a new recording

        # Start again
        for key, val in self.components.items():
            if self.is_connected(key) and key != "wfs":  # Do not restart the WFS, make the user to it manually
                self._soft_run(val["instance"], "start")

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

def instantiate_component(component_class, class_path, *args, **kwargs):
    spec = importlib.util.spec_from_file_location(component_class, class_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    cls = getattr(module, component_class)
    return cls(*args, **kwargs)

def try_shutdown(component):
    if component is None:
        print("Component is None, skipping shutdown.")
        return
        
    try:
        if hasattr(component, 'stop'):
            component.stop()
            
        if hasattr(component, 'shutdown'):  # for Andor SDK - release the camera
            component.shutdown()
        elif hasattr(component, 'close'):
            component.close()
            
    except Exception as e:
        print(f"Component {component} threw an error during shutdown: {e}")

def reset_shms():
    shm_names = ["wfs", "wfsRaw", "wfc", "wfc2D", "wfcShape", "signal", "signal2D"
                 "psfShort", "psfLong", "wfsInfo", "loop", "refSlopes", "subApMasks",
                 "cmat", "m2c", "simInjectedSlopes"] #list of SHMs to reset
    clear_shms(shm_names)

if __name__ == "__main__":
    ics = PyroICSSoft()
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