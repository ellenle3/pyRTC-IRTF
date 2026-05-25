import re
import numpy as np
from astropy.coordinates import SkyCoord
import astropy.units as u


def parse_and_validate_ra(ra_str):
    """Parse RA string hh:mm:ss.ss and return decimal degrees."""
    pattern = r'^(\d{1,2}):(\d{2}):(\d{2}(?:\.\d+)?)$'
    m = re.match(pattern, ra_str.strip())
    if not m:
        raise ValueError(f"RA '{ra_str}' must be in hh:mm:ss.ss format.")
    
    hh, mm, ss = int(m.group(1)), int(m.group(2)), float(m.group(3))
    
    if not (0 <= hh < 24):
        raise ValueError(f"RA hours must be in [0, 24). Got {hh}.")
    if not (0 <= mm < 60):
        raise ValueError(f"RA minutes must be in [0, 60). Got {mm}.")
    if not (0.0 <= ss < 60.0):
        raise ValueError(f"RA seconds must be in [0, 60). Got {ss}.")
    
    return hh + mm / 60.0 + ss / 3600.0  # decimal hours, passed to SkyCoord


def parse_and_validate_dec(dec_str):
    """Parse Dec string +dd:mm:ss.s and return decimal degrees."""
    pattern = r'^([+-]?\d{1,2}):(\d{2}):(\d{2}(?:\.\d+)?)$'
    m = re.match(pattern, dec_str.strip())
    if not m:
        raise ValueError(f"Dec '{dec_str}' must be in +dd:mm:ss.s format.")
    
    dd_str, mm, ss = m.group(1), int(m.group(2)), float(m.group(3))
    dd = int(dd_str)
    sign = -1 if dd_str.startswith('-') else 1

    if not (-90 <= dd <= 90):
        raise ValueError(f"Dec degrees must be in [-90, 90]. Got {dd}.")
    if not (0 <= mm < 60):
        raise ValueError(f"Dec arcminutes must be in [0, 60). Got {mm}.")
    if not (0.0 <= ss < 60.0):
        raise ValueError(f"Dec arcseconds must be in [0, 60). Got {ss}.")
    
    decimal_deg = abs(dd) + mm / 60.0 + ss / 3600.0
    if abs(decimal_deg) > 90.0:
        raise ValueError(f"Dec magnitude cannot exceed 90 degrees. Got {decimal_deg}.")
    
    return sign * decimal_deg

def angular_separation(ra1, dec1, ra2, dec2):
    """
    Compute angular separation between two sky coordinates.

    Parameters
    ----------
    ra1, ra2  : str, RA in hh:mm:ss.ss format
    dec1, dec2: str, Dec in +dd:mm:ss.s format (sign required)

    Returns
    -------
    float
        Angular separation in arcseconds.
    """
    ra1_h  = parse_and_validate_ra(ra1)
    dec1_d = parse_and_validate_dec(dec1)
    ra2_h  = parse_and_validate_ra(ra2)
    dec2_d = parse_and_validate_dec(dec2)

    c1 = SkyCoord(ra=ra1_h * u.hourangle, dec=dec1_d * u.deg)
    c2 = SkyCoord(ra=ra2_h * u.hourangle, dec=dec2_d * u.deg)

    return c1.separation(c2).arcsecond

def calc_ncpa_lookup(ra_target, dec_target, ra_guide, dec_guide):
    """
    Calculate NCPA lookup values.
    """
    dist_as = angular_separation(ra_target, dec_target, ra_guide, dec_guide)
    pass

def make_imat_synthetic(self, ics, theoretical_imat, method):
    pass