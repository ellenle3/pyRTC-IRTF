# FILE: find_peak_freq.py

# Import packages

import numpy as np

def find_peak_actuator_frequencies(actuator_fft_magnitude, freq_mask, freq_pos, silent):
    n_actuators = actuator_fft_magnitude.shape[1]
    peak_frequency_indices = np.zeros(n_actuators, dtype=np.int32)
    thresh = np.max(actuator_fft_magnitude[5:, :]) / 20.0 # arbitrary
    
    filtered_magnitude = actuator_fft_magnitude * freq_mask[:, np.newaxis]
    
    for actuator in range(n_actuators):
        max_response = np.max(filtered_magnitude[:, actuator])
        
        if max_response > thresh:
            peak_index = np.argmax(filtered_magnitude[:, actuator])
            peak_frequency_indices[actuator] = peak_index
            
            if not silent:
                freq_hz = freq_pos[peak_index]
                strength = actuator_fft_magnitude[peak_index, actuator]
                print(f"Actuator {actuator}: Peak at bin {peak_index}, freq {freq_hz:.2f} Hz, strength {strength:.2e}")
        else:
            peak_frequency_indices[actuator] = 0
            if not silent:
                print(f"Actuator {actuator}: No strong peak found.")
    
    return peak_frequency_indices
