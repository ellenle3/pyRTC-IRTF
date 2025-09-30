"""Generates cacofoni playback buffers as a FITS file.
Note that the way this is implemented, the playback files are in terms of modal
coefficients rather than commands.
"""
import argparse
import numpy as np
from astropy.io import fits

def make_cacofoni_pb_pyrtc(loop_rate: float, ncb: int, nmodes: int, amp: float,
                           fmin: float, df: float):
    """Creates a cacofoni playback buffer. Because pyRTC takes modal coefficients
    rather than actuator commands, these buffers are applicable to any modal basis
    (e.g., zonal, zernikes, mirror).

    Parameters
    ----------
    loop_rate : float
        Loop rate in Hz.
    ncb : int
        Length of the playback buffer (number of loop iterations).
    nmodes : int
        Number of modes in the playback buffer.
    """
    pb = np.zeros((ncb, nmodes), dtype=np.float32)
    dt = 1 / loop_rate
    t = 0

    for i in range(ncb):
        for j in range(nmodes):
            freq = fmin + j * df
            pb[i, j] = amp * np.sin(2 * np.pi * freq * t)
        t += dt
    
    return pb

if __name__ == "__main__":

    loop_rate = 1000.0  # Hz
    fmin = 4
    df = 0.2
    n_modes = 36
    amp = 0.01

    ncb = round( loop_rate / df )  # capture a full cycle
    pb = make_cacofoni_pb_pyrtc(loop_rate=loop_rate, ncb=ncb, nmodes=n_modes, amp=amp,
                                fmin=fmin, df=df)
    
    calib_dir = "calib/pb/"
    np.save(f"{calib_dir}cacofoni_pb_{loop_rate}Hz_x{ncb}_nmodes{n_modes}_amp{amp}_fmin{fmin}_df{df}.npy", pb)
