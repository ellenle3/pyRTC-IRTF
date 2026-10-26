import yaml
import numpy as np
from pyroics import get_ics_proxy
from irtfio import run_t3io, get_felix_xyoffset
from nomad import nomad_search_pos
from constants import *

def get_observatory_config():
    config_path = "/home/felix/src/pyrtc/pyRTC-IRTF/IRTF/config/observatory.yaml"
    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)
    return config

def felix_radec_to_xy(dra, ddec):
    """Converts RA and Dec offsets to pixels using the plate scale and position
    angle. Returns subpixel values (floats).
    """
    ics = get_ics_proxy()    
    if not ics.is_connected("wfs"):
        print("Felix is not running.")
        return

    config = get_observatory_config()
    
    # Convert to pixel offsets
    ps = config["felix"]["plate_scale"]
    dx = dra / ps
    dy = ddec / ps

    # rotate ccw by the position angle to align with the camera coordinates
    theta = np.radians( config["felix"]["pos_angle"] )
    dx_rot = dx * np.cos(theta) - dy * np.sin(theta)
    dy_rot = dx * np.sin(theta) + dy * np.cos(theta)
    dx = dx_rot
    dy = dy_rot

    # subap masks are defined in terms of the final binned image
    binning = ics.get("wfs", "binning")
    dx /= binning
    dy /= binning

    return dx, dy

def felix_xy_to_radec(dx, dy):
    """Opposite as above.
    """
    ics = get_ics_proxy()
    if not ics.is_connected("wfs"):
        print("Felix is not running.")
        return
        
    config = get_observatory_config()
    binning = ics.get("wfs", "binning")
    dx *= binning
    dy *= binning
    
    theta = -1 * np.radians( config["felix"]["pos_angle"] )
    dx_rot = dx * np.cos(theta) - dy * np.sin(theta)
    dy_rot = dx * np.sin(theta) + dy * np.cos(theta)
    dx = dx_rot
    dy = dy_rot

    ps = config["felix"]["plate_scale"]
    dra = dx * ps
    ddec = dy * ps
    
    return dra, ddec

def focus_lookup(dra, ddec, f0):
    """Returns a pre-calibrated focus value.
    """
    A = 3.351e-5
    dra0 = 180
    ddec0 = 50
    focus = f0 + A * ( (dra - dra0)**2 + (ddec - ddec0)**2 )
    return focus

def get_felix_guidebox_offset():
    """Gets position of Felix guidebox in delta RA and Dec (arcseconds).
    """
    ics = get_ics_proxy()
    
    dra_stage, ddec_stage = get_felix_xyoffset()  # xy stage offset
    dx_guide = ics.get("slopes", "xSubApOffset")
    dy_guide = ics.get("slopes", "ySubApOffset")
    dra_guide, ddec_guide = felix_xy_to_radec(dx_guide, dy_guide)

    print(dra_stage, ddec_stage)
    print(dra_guide, ddec_guide)
    
    dra  = dra_stage  + dra_guide
    ddec = ddec_stage + ddec_guide
    return dra, ddec

def set_focus_reference():
    # Run this on startup
    ics = get_ics_proxy()

    # Star position
    dra, ddec = get_felix_guidebox_offset()

    # Update the on-axis focus zero point
    f_current = ...
    f_onaxis = f_current - focus_lookup(dra, ddec, f0)
    
    # Set internal refslopes for slopes process
    # ...decide whether to save this focus to a file
    # or if it's sufficient to just reboot andor wfs when stopping
    # probably save to a file for ease of use

def set_ncpa():
    """Updates slope offsets from modal coefficients.
    auto_offsets and user_offsets must be a 1D list or array of modal coefficients.
    """
    ics = get_ics_proxy()
    
    total_slope_offsets = np.zeros( (4,2) )
    auto_offsets = ics.get_aocals("ncpa", "auto_offsets")
    user_offsets = ics.get_aocals("ncpa", "user_offsets")
    
    total_slope_offsets += modes_to_slopes(auto_offsets, reshape=True)     
    total_slope_offsets += modes_to_slopes(user_offsets, reshape=True)
    
    self.run("slopes", "setUserSlopeOffsets", total_slope_offsets)

def modes_to_slopes(coeffs, reshape=True):
    ics = get_ics_proxy()
    
    coeffs = np.array(coeffs)
    imat = ics.get("loop", "IM")
    slope_offsets = imat @ np.array(coeffs)
    if reshape:
        slope_offsets = np.reshape(slope_offsets, (4,2))
    return slope_offsets

def slopes_to_modes(slopes):
    ics = get_ics_proxy()

    slopes = ics.run("slopes", "read", False)
    imat = ics.get("loop", "IM")
    modes = np.linalg.pinv(imat) @ slopes
    return modes

def find_stars_near_felix():
    config = get_observatory_config()
    fov = config["felix"]["fov"]
    nomad_path = config["felix"]["nomad_path"]
    mag_limit = config["felix"]["nomad_mag_limit"]
    max_results = config["felix"]["nomad_max_results"]
    search_radius = fov * DAS2R / 2

    output = run_t3io("info", "SPr")  # ADD IN TOTAL OFFSETS!
    
    ra_rad, dec_rad = float(output[1]), float(output[2])
    dra_felix, ddec_felix = get_felix_guidebox_offset()
    dra_felix  *= DAS2R
    ddec_felix *= DAS2R

    results, err_code = nomad_search_pos(
        ra = ra_rad + dra_felix, # radians
        dec = dec_rad + ddec_felix,
        radius = search_radius,
        nomad_root = nomad_path,
        maximum = 20,
        enable_mag_limit = True,
        mag_limit = max_results,
        debug = False
    )
    return results, err_code

def texpos_test_image(V):
    results, err_code = find_stars_near_felix()
    if err_code != 0:
        raise RuntimeError("NOMAD query failed. Error code:", err_code)
    elif len(results) == 0:
        print("No guide stars found.")
        return 1
    
def texpos_active_optics(V):
    pass
    