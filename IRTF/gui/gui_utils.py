import re
from wsgiref.validate import validator
import numpy as np
import astropy.units as u
from astropy.coordinates import SkyCoord

from PyQt6.QtGui import QRegularExpressionValidator
from PyQt6.QtCore import QRegularExpression


def validator_4int():
    """Input validator for four space-delimited integers.
    """
    validator = QRegularExpressionValidator(
        QRegularExpression(r'^-?\d+\s+-?\d+\s+-?\d+\s+-?\d+$')
    )
    return validator

def validator_2int():
    """Input validator for two space-delimited integers.
    """
    validator = QRegularExpressionValidator(
    QRegularExpression(r'^-?\d+\s+-?\d+$')
    )
    return validator

def is_roi_valid(xmax, ymax, binning, width, height, left, top):
    """Check if the ROI defined by left, top, width, height is valid within the
    bounds of xmax and ymax. Assumes 1-based indexing (for Andor camera).

    Returns
    -------
    bool, str
        Tuple of (is_valid, error_message). If is_valid is True, error_message will
        be empty.
    """
    if not all(isinstance(x, int) for x in [xmax, ymax, binning, left, top, width, height]):
        return False, "All ROI parameters must be integers."
    if xmax < 1 or ymax < 1:
        return False, "Maximum x and y (xmax, ymax) must be positive integers."
    if binning < 1:
        return False, "Binning must be a positive integer."
    if width < 1 or height < 1:
        return False, "Width and height must be positive integers."
    if left < 1 or top < 1:
        return False, "Left and top must be positive integers."
    if left + width - 1 > xmax:
        return False, f"ROI exceeds full frame along x: {xmax}, requested left {left} and width {width}."
    if top + height - 1 > ymax:
        return False, f"ROI exceeds full frame along y: {ymax}, requested top {top} and height {height}."
    if width % binning != 0:
        return False, f"ROI width {width} must be divisible by binning: {binning}."
    if height % binning != 0:
        return False, f"ROI height {height} must be divisible by binning: {binning}."
    return True, ""

def pad_roi_to_full_frame(image, xmax, ymax, binning, width, height, left, top):
    """
    Pad a binned subarray image to full frame size with zeros.
    Input coordinates are in full-frame (unbinned) pixels, 1-based (Andor convention).
    Output shape is (ymax // binning, xmax // binning).

    Parameters
    ----------
    image : np.ndarray, shape (height // binning, width // binning)
    left, top : int, 1-based full-frame origin of the ROI
    width, height : int, ROI dimensions in full-frame pixels
    xmax, ymax : int, full frame dimensions in full-frame pixels
    binning : int, binning factor

    Returns
    -------
    np.ndarray, shape (ymax // binning, xmax // binning)
    """
    binned_xmax = xmax // binning
    binned_ymax = ymax // binning

    full_frame = np.zeros((binned_ymax, binned_xmax), dtype=image.dtype)

    # Convert 1-based full-frame coordinates to 0-based binned coordinates
    row_start = (top - 1) // binning
    col_start = (left - 1) // binning
    binned_height = height // binning
    binned_width = width // binning

    full_frame[row_start:row_start + binned_height, col_start:col_start + binned_width] = image

    return full_frame

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