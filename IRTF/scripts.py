import yaml
import numpy as np
from pyroics import get_ics_proxy
from irtfio import run_t3io, get_felix_xyoffset
from nomad import nomad_search_pos
from constants import *

def get_observatory_config():
    #config_path = "/home/felix/src/pyrtc/pyRTC-IRTF/IRTF/config/observatory.yaml"
    config_path = "/Users/ellenlee/Documents/pyRTC-IRTF/IRTF/config/observatory.yaml"
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

def focus_lookup(dra, ddec):
    """Returns a pre-calibrated focus value. (Differece from the on-axis
    focus value.)
    """
    A = 3.351e-5
    dra0 = 180
    ddec0 = 50
    focus = A * ( (dra - dra0)**2 + (ddec - ddec0)**2 )
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
    ics = get_ics_proxy()
    num_modes = ics.get_config("ao", "num_modes")
    dra, ddec = get_felix_guidebox_offset()
    coeffs = np.zeros(num_modes)
    dfocus = focus_lookup(dra, ddec)
    coeffs[2] = dfocus
    slopes = modes_to_slopes(coeffs, reshape=True)
    ics.run("slopes", "setUserSlopeOffsets", slopes)

def run_focus_calibration():
    # Run this on startup
    ics = get_ics_proxy()

    # Measure current focus value

    # Star position
    dra, ddec = get_felix_guidebox_offset()
    dfocus = focus_lookup(dra, ddec)

    # Update the on-axis focus zero point
    slopes = ics.run("slopes", "read", False)
    f_current = ...
    f_onaxis = f_current - focus_lookup(dra, ddec, f0)
    
    # Set internal refslopes for slopes process
    # ...decide whether to save this focus to a file
    # or if it's sufficient to just reboot andor wfs when stopping
    # probably save to a file for ease of use

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

def texpos_active_optics():
    results, err_code = find_stars_near_felix()
    if err_code != 0:
        raise RuntimeError("NOMAD query failed. Error code:", err_code)
    elif len(results) == 0:
        print("No guide stars found.")
        return 0.1, 1

    for record in results:
        mag = 999
        for i in range(4):
            mag_filter = record.magD[i]
            if mag_filter != '-':
                mag = float(mag_filter)
                break
        if mag != 999:
            break
    if mag == 999:
        print("No valid magnitudes found for any of the stars.")
        return 0.1, 1

    # flux limited...
    if mag < 8:
        return 0.05, 50  # extremely bright - just avoid saturating

    mag0 = 12
    t0 = 1
    fscale = 10**(-0.4 * (mag - mag0))
    t = t0 * fscale

    coadds = 1
    if t <= 2:
        coadds = round(5/t)   # integrate for 5 sec minimum
    elif t > 20:
        coadds = round(t/20) # if itime > 20 sec, split across coadds
        t = 20

    return t, coadds