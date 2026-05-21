# FILE: _compute_fft.py

# Import packages
import numpy as np

def _compute_fft(signal_array):
    """Compute the fast fourier transform for a signal array."""
    n_steps = signal_array.shape[0]

    scaled = signal_array
    fft_result = np.fft.fft(scaled, axis=0).astype(np.complex64)
    
    return fft_result