# FILE: calc_samp_freq.py

# Import packages
import numpy as np

def calc_samp_freq(clocktime_usec):
    """
    Estimate the sampling frequency from the clocktime
    array in the imaka telemetery file (in microseconds).
    
    Parameters
    ----------
    clocktime_usec : np.ndarray
        1D array of timestamps in microseconds.

    Returns
    -------
    fsamp : float
        Estimated average sampling frequency in Hz.
    dt_1_sigma : float
        Average time between samples in seconds.
    """
    
    clocktime_sec = clocktime_usec * 1e-6 # convert to seconds
    dt = np.diff(clocktime_sec) # take time differences between successive steps
    
    # Take the one-sigma mean
    dt_mean = np.mean(dt)
    dt_std = np.std(dt)
    inliers = (dt > dt_mean - dt_std) & (dt < dt_mean + dt_std)
    dt_1_sigma = np.mean(dt[inliers])

    
    # Take the sampling frequency from the average
    fsamp = 1.0 / dt_1_sigma
    fsamp = int(fsamp)
    
    return fsamp, dt_1_sigma