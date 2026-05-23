import os
import pyRTC.utils as utils
from pyRTC import *
from pathlib import Path

CONFIG_PATH = Path(__file__).parent.parent / "config"
PYRTC_CLASS_PATH = Path(__file__).parent.parent.parent / "pyRTC"
with open(CONFIG_PATH / "ports.json") as f:
    PORTS = json.load(f)


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
    launcher = check_config_and_make_launcher(hardware_class, config, "wfs")
    return launcher

def get_loop():
    hardware_class = PYRTC_CLASS_PATH / "Loop.py"
    config = CONFIG_PATH / "hrtc_loop.yaml"
    launcher = check_config_and_make_launcher(hardware_class, config, "wfs")
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
    components = [get_imakadm(), get_slopes(), get_loop(), get_felixsim(), get_andor()]
    for comp in components:
        try_shutdown(comp)

def reset_shms():
    shm_names = ["wfs", "wfsRaw", "wfc", "wfc2D", "wfcShape", "signal", "signal2D"
                 "psfShort", "psfLong", "wfsInfo", "loop", "refSlopes", "subApMasks",
                 "cmat", "m2c"] #list of SHMs to reset
    clear_shms(shm_names)

def reset_wfs_shm(wfs, loop, slopes):

    # reset the WFS SHM

    # reset slopes

    # reset loop wfsInfo SHM
    
    return wfs, loop, slopes