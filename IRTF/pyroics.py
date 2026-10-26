"""Uses soft RTC mode to run all components in a single process. This works up
to frame rates of 190 Hz. It's easier to debug and does not slow down when running
commands that take many frames to execute (e.g., takeRefSlopes).

The ICS exists so that pyRTC can run in a separate process from the GUI. However,
the GUI is responsible for telling the ICS to launch or shut down components.
"""
import Pyro5.api
import json
import os
import yaml
import signal
import threading
import importlib.util
import pyRTC.utils as utils
from pyRTC import *

from Pyro5.errors import CommunicationError
import Pyro5.configure
import serpent

# Allow ND_Arrays to be serialized
def _encode_ndarray(obj, serializer, stream, indent):
    d = {"__class__": "numpy.ndarray", "dtype": str(obj.dtype),
         "data": obj.tolist(), "shape": list(obj.shape)}
    serializer.ser_builtins_dict(d, stream, indent)
def _decode_ndarray(classname, d):
    return np.array(d["data"], dtype=d["dtype"]).reshape(d["shape"])
Pyro5.configure.global_config.SERIALIZER = "serpent"
serpent.register_class(np.ndarray, _encode_ndarray)
Pyro5.api.register_dict_to_class("numpy.ndarray", _decode_ndarray)

def get_ics_config():
    config_path = "/home/felix/src/pyrtc/pyRTC-IRTF/IRTF/config/ics.yaml"
    #config_path = "/Users/ellenlee/Documents/pyRTC-IRTF/IRTF/config/ics.yaml"
    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)
    return config

def get_ics_proxy():
    # Each thread will need its own proxy for the ICS.
    config = get_ics_config()
    ics_uri_path = config["pyro"]["ics_uri_path"]

    with open(ics_uri_path) as f:
        uri = f.read().strip()
    try:
        proxy = Pyro5.api.Proxy(uri)
        # Test the connection
        proxy._pyroBind()
    except CommunicationError:
        raise ConnectionError(f"Could not connect to ICS at {uri}. Is the ICS running?")
    
    return proxy

class ICSErrorCodes:
    MSG_TO_CODE = {
        "Success": 0,
        "Component already exists": 1,
        "Component does not exist": 2,
        "Invalid component type": 3,
        "Failed to launch component": 4,
        "Shutdown timed out": 5,
        "Shutdown encountered error": 6,
        "pyRTC error": -1
    }
    CODE_TO_MSG = {v: k for k, v in MSG_TO_CODE.items()}
    
    @classmethod
    def get_code(cls, message):
        return cls.MSG_TO_CODE.get(message)
    
    @classmethod
    def get_message(cls, code):
        return cls.CODE_TO_MSG.get(code)

@Pyro5.api.expose
class PyroICSSoft:
    """Orchestrates connections to all components. The GUI and other Python
    interfaces should only interact with components through this class, which
    will be exposed through Pyro. This allows the hardware to keep running even
    if the GUI crashes.

    ICS = Instrument Control Server
    """

    def __init__(self):

        self.config = get_ics_config()

        with open(self.config["paths"]["hardware_launchers"]) as f:
            launch_config = json.load(f)
            self.launchers = launch_config
        
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

        self.ao_cals = {
            "imat" : {
                "theor_file": None,
                "synth_file": None,
                "method": None
            },
            "ncpa": {
                "ra_target": "00:00:00.00",
                "dec_target": "+00:00:00.0",
                "ra_guide": "00:00:00.00",
                "dec_guide": "+00:00:00.0",
                "dra": 0.0,
                "ddec": 0.0,
                "auto_offsets": np.zeros( self.config["ao"]["num_modes"] ),
                "user_offsets": np.zeros( self.config["ao"]["num_modes"] )
            }
        }

    def get_aocals(self, key, subkey):
        return self.ao_cals[key][subkey]
    
    def set_aocals(self, key, subkey, value):
        if key in self.ao_cals and subkey in self.ao_cals[key]:
            self.ao_cals[key][subkey] = value
            if subkey in ["auto_offsets", "user_offsets"]:
                self.set_ncpa()  # automatically update slope offsets if modal coefficients change
            return ICSErrorCodes.get_code("Success")
        else:
            return -1
    
    def get_available_launchers(self):
        return list(self.launchers.keys())
    
    def is_connected(self, component_type):
        if component_type not in self.components:
            return ICSErrorCodes.get_code("Invalid component type"), "Invalid component type"
        return self.components[component_type]["instance"] is not None
            
    def launch(self, component_class):
        if component_class not in self.launchers:
            return ICSErrorCodes.get_code("Invalid component type"), "Invalid component type"
        
        component_type = self.launchers[component_class]["type"]
        pyrtc_class_path = self.config["paths"]["pyrtc_class"]
        hardware_config_path = self.config["paths"]["hardware_config"]
        
        with self._locks[component_type]:
            if self.is_connected(component_type):
                return ICSErrorCodes.get_code("Component already exists"), "Component already exists"
            
            hardware_class = os.path.join( pyrtc_class_path, self.launchers[component_class]["class_path"] )
            config_file = os.path.join( hardware_config_path, self.launchers[component_class]["config_path"] )
            conf = utils.read_yaml_file(config_file)[component_type]
            try:
                instance = instantiate_component(component_class, hardware_class, conf)                                    
            except Exception as e:
                print(f"Error while instantiating component {component_class}: {e}")
                return -1

            self.components[component_type]["instance"] = instance
            self.components[component_type]["class"] = component_class
            return 0
        
    def shutdown(self, name, timeout=5.0):
        if name not in self.components:
            return ICSErrorCodes.get_code("Component does not exist"), "Component does not exist"
            
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
            return ICSErrorCodes.get_code("Component does not exist"), "Component does not exist"
            
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

    # Common loop-related functionality
    def open_loop(self, flatten=False):
        """Opens the loop. If flatten=True, also flattens the ASM upon opening
        the loop so we don't have to wait for voltages to leak off.
        """
        if not self.is_connected("loop"):
            return 3
        self.run("loop", "setGain", 0)
        self.set("loop", "leakyGain", 0.0)
        if flatten:
            if not self.is_connected("wfc"):
                return 3
            self.run("wfc", "flatten")

    def close_loop(self):
        if not self.is_connected("loop"):
            return 3
        self.run("slopes", "start")  # In case we force stopped it before
        self.run("wfc", "start")
        self.run("loop", "start")
        self.run("loop", "setGain", 0.05)
        self.set("loop", "leakyGain", 0.0)

    def is_closed_loop(self):
        if not self.is_connected("loop"):
            return 3
        gain = self.get("loop", "gain")
        return gain > 0.0

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
    """Reset all shared memory segments."""
    shm_names = ["wfs", "wfsRaw", "wfc", "wfc2D", "wfcShape", "signal", "signal2D"
                 "psfShort", "psfLong", "wfsInfo", "loop", "refSlopes", "subApMasks",
                 "cmat", "m2c", "simInjectedSlopes"] #list of SHMs to reset
    clear_shms(shm_names)

if __name__ == "__main__":

    config = get_ics_config()
    
    Pyro5.configure.DETAILED_TRACEBACK = config["pyro"]["detailed_traceback"]
    Pyro5.configure.COMMTIMEOUT = config["pyro"]["command_timeout"]
    
    ics = PyroICSSoft()
    daemon = Pyro5.api.Daemon()
    uri = daemon.register(ics, objectId="pyrtc.ics")
    with open(config["pyro"]["ics_uri_path"], "w") as f:
        f.write(str(uri))
    print("Pyro ICS is running. URI:", uri)

    def handler(sig, frame):
        ics.shutdown_all()
        exit(0)

    signal.signal(signal.SIGINT, handler)

    daemon.requestLoop()