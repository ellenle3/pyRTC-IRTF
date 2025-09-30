# FILE: make_cacofoni.py

# Import packages
import numpy as np
from astropy.io import fits

from cacofoni.mc.config import CacofoniConfig, print_config
from cacofoni.mc.calc_samp_freq import calc_samp_freq
from cacofoni.mc.deriv2D import deriv2D
from cacofoni.mc._load_and_log_telemetry import _load_and_log_telemetry, load_combined_telemetry
from cacofoni.mc.file_utils import check_default_path, check_user_path, resolve_filepath
from cacofoni.mc._compute_fft import _compute_fft
from cacofoni.mc.find_peak_freq import find_peak_actuator_frequencies

def make_cacofoni(telemetry_filepath=None,
                  modal_filepath=None,
                  modal=None,
                  closed=None,
                  choose_n_steps=None,
                  start_index=None,
                  silent=False,
                  debug=None,
                  config=None,
                  keep_as_modal=False):  # keep_as_modal will not convert imat back o actuators at the end
    """   
    """
    
    if not silent:
        print("Setting up make_cacofoni...\n")
        
    config = config or CacofoniConfig()
    if not silent:
        print_config(config)
    
    silent = config.silent if silent is None else silent
    modal = config.modal if modal is None else modal
    closed = config.closed if closed is None else closed

    telemetry_filepath = resolve_filepath(telemetry_filepath, config.telemetry_filename, silent)
    telemetry_data = _load_and_log_telemetry(telemetry_filepath, choose_n_steps, start_index, silent)

    xcentroids, ycentroids, deltav, voltage, n_steps, n_act, n_centroids, sampling_freq_hz, nyquist_freq_hz = telemetry_data
    commands = deltav if closed else voltage
    
    if modal:
        if not silent:
            print("Loading modal file and computing modal commands...\n")
    
        modal_filepath = resolve_filepath(modal_filepath, config.modal_filename, silent) 
    
        with fits.open(modal_filepath) as hdul:
            mirmodes = hdul[0].data.astype(np.float32)  # shape (n_modes, n_act)

        modcom = np.dot(commands, mirmodes.T)
        fft_actuators_all = _compute_fft(modcom)
        
        # Convert back from modal space to actuator space
        mod2act = np.linalg.pinv(mirmodes) # --changed, go from inv to pinv
    else:
        fft_actuators_all = _compute_fft(commands)
        mod2act = None
    
    if debug:
        # For debugging, matches idl better 
        sampling_freq_hz = 996  
        nyquist_freq_hz = sampling_freq_hz / 2
        
    centroids = np.concatenate((xcentroids, ycentroids), axis=2).astype(np.float32)
    centroids_flat = centroids.reshape(n_steps, -1) 
    centroid_means = np.mean(centroids_flat, axis=0, keepdims=True)
    centroids_centered = centroids_flat - centroid_means
        
    fft_centroids_all = _compute_fft(centroids_centered)
    fft_response_all = fft_centroids_all[:, :, np.newaxis] / fft_actuators_all[:, np.newaxis, :]

    n_pos_freq_bins = n_steps // 2
    freq_pos = ((np.arange(n_pos_freq_bins) + 1) / n_pos_freq_bins * nyquist_freq_hz).astype(np.float32) 
        
    freq_mask = (freq_pos >= config.minimum_freq_hz) & (freq_pos <= config.maximum_freq_hz)
    actuator_fft_magnitude = np.abs(fft_actuators_all[0:n_pos_freq_bins, :]) 
    fft_centroids_real = np.real(fft_centroids_all[0:n_pos_freq_bins, :])
    
    if not silent: 
        print("Preparing for interaction matrix...\n")
        
    peak_freq_indices = find_peak_actuator_frequencies(actuator_fft_magnitude, freq_mask, freq_pos, silent)
    
    if not silent:
        print("Computing interaction matrix...\n")
        
    interaction_matrix = np.zeros((n_centroids, n_act), dtype=np.float32)
    for i in range(n_act):
        positive_idx = peak_freq_indices[i]
        negative_idx = n_steps - positive_idx
        
        if negative_idx >= n_steps:
            negative_idx = n_steps -1
        
        interaction_matrix[:, i] = -1.0 * (
            fft_response_all[positive_idx, :, i].real +
            fft_response_all[negative_idx, :, i].real
        ) / 2.0
        
    if mod2act is not None and not keep_as_modal:
        interaction_matrix = interaction_matrix @ mod2act.T
        
    if closed:
        interaction_matrix *= -1.0
            
    if not silent:
        print("Computing laplacian...")
            
    if config.laplacian:
        inffuncdx = np.zeros((int(config.n_xsubapertures), int(config.n_ysubapertures), n_act), dtype=float)
        inffuncdy = np.zeros((int(config.n_xsubapertures), int(config.n_ysubapertures), n_act), dtype=float)
        laplacian = np.zeros((int(config.n_xsubapertures), int(config.n_ysubapertures), n_act), dtype=float)

        for i in range(n_act):
            inffuncdx[:, :, i] = interaction_matrix[0:n_centroids//2, i].reshape(int(config.n_xsubapertures), int(config.n_ysubapertures), order='F')
            inffuncdy[:, :, i] = interaction_matrix[n_centroids//2:n_centroids, i].reshape(int(config.n_xsubapertures), int(config.n_ysubapertures), order='F')

            laplacian[:, :, i] = (
                deriv2D(inffuncdy[:, :, i], y=True) +
                deriv2D(inffuncdx[:, :, i], x=True)
            )
    else:
        laplacian = None
            
    return freq_pos, fft_centroids_real, actuator_fft_magnitude, freq_mask, interaction_matrix, laplacian




# Under construction, useable but now fully done
# Needs better flexibility
def make_cacofoni_only_laplacian(args):
    from cacofoni.mc._load_and_log_telemetry import load_telemetry
    
    telemetry_filepath, n_steps, step_start, modal_filepath, modal, closed, silent, debug, config = args
    
    try:
        _, _, _, _, _, laplacian = make_cacofoni(
            telemetry_filepath,
            modal_filepath=modal_filepath,
            modal=modal,
            choose_n_steps=n_steps,
            start_index=step_start,
            closed=closed,
            debug=debug,
            silent=silent,
            config=config
        )
        return laplacian
    except Exception as e:
        print(f"  Failed for segment {step_start}–{step_start+n_steps}: {e}")
        
        return None
    
def make_cacofoni_binned(telemetry_filepath,
                         window_step_size=1000,
                         max_steps=27000,
                         modal_filepath=None,
                         modal=False,
                         closed=None,
                         silent=True,
                         debug=True,
                         config=None):
    
    from tqdm import tqdm
    from multiprocessing import Pool, cpu_count
    
    binned_laplacian = []
    window_sizes = list(range(1000, max_steps + 1, window_step_size))
    n_processes = cpu_count()
    
    for window in window_sizes:
        print(f"\n--- Running with a window size = {window} ---")
        tasks = []
        for step_start in range(0, max_steps - window + 1, window):
            tasks.append((telemetry_filepath,
                          window,
                          step_start,
                          modal_filepath,
                          modal,
                          closed,
                          silent,
                          debug,
                          config))
        with Pool(n_processes) as pool:
            laplacians_from_window = list(tqdm(
                pool.imap(make_cacofoni_only_laplacian, tasks),
                total=len(tasks)
            ))    
            binned_laplacian.append(laplacians_from_window)
            
    return binned_laplacian