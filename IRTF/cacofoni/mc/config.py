# FILE: config.py
# Contains default configuration values and path
# Note: The files are assumed to be in data/.

# Import packages
from dataclasses import dataclass, field

@dataclass
class CacofoniConfig:
    telemetry_filename: str = "aocb0090.fits"
    #param_filename: str = SETTINGS["RESOURCES"]["imaka_parm"]  # imakaparm.txt
    modal_filename: str = "calib/z2a.empirical_norm.20250408b.fits"
    
    minimum_freq_hz: float = 3.0
    maximum_freq_hz: float = 5.0

    n_actuators: int = 7
    n_xsubapertures: int = 2 #12
    n_ysubapertures: int = 2 #12

    closed: bool = False
    modal: bool = False
    thresh: bool = None
    apply_hanning: bool = False
    laplacian: bool = True
    silent: bool = False
    
def print_config(config):
    print(f"[Config] Assuming {config.n_actuators} actuators from config for loading telemetry data.")
    print(f"[Config] Assuming {config.n_xsubapertures} 'x' subapertures from config for loading telemetry data.")
    print(f"[Config] Assuming {config.n_ysubapertures} 'y' subapertures from config for loading telemetry data.\n")
    print(f"[Config] Assuming {config.minimum_freq_hz} Hz for minimum frequency.")
    print(f"[Config] Assuming {config.maximum_freq_hz} Hz for maximum frequency.\n")
    
    return