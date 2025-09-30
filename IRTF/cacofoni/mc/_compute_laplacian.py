# FILE: compute_laplacian

# Import packages
import numpy as np
from cacofoni.deriv2D import deriv2D
from cacofoni.config import CacofoniConfig

def compute_laplacian(interaction_matrix):
    
    imat = interaction_matrix
    
    nact = interaction_matrix.shape[1]
    ncentroids = interaction_matrix.shape[0]
    ncentroids_half = ncentroids // 2
    
    nsub_x = config.num_dimx_subapertures
    nsub_y = config.num_dimy_subapertures
    
    influence_map_x = np.zeros((nsub_x, nsub_y, nact), dtype=float)
    influence_map_y = np.zeros((nsub_x, nsub_y, nact), dtype=float)
    laplacian_map = np.zeros((nsub_x, nsub_y, nact), dtype=float)
    
    imat_xslice, imat_yslice = get_imat_slice(imat, ncentroids_half, nact)
    
    return

def get_imat_slice()


x_slice = interaction_matrix[0:half, actuator_index]
    y_slice = interaction_matrix[half:, actuator_index]
    return x_slice, y_slice


def compute_influence_functions(interaction_matrix, nact, ncentroids_half, nsub_x, nsub_y):

def compute_laplacian(interaction_matrix, num_dimx_subap, num_dimy_subap):

    
    inffuncdx = np.zeros((num_dimx_subap, num_dimy_subap, nact), dtype=float)
    inffuncdy = np.zeros((num_dimx_subap, num_dimy_subap, nact), dtype=float)
    laplacian = np.zeros((num_dimx_subap, num_dimy_subap, nact), dtype=float)
    
    half = ncentroids // 2
    
    for i in range(nact):
        # Reshape x/y parts into 12x12 grid, Fortran order like IDL
        inffuncdx[:, :, i] = interaction_matrix[0:half, i].reshape(
            (num_dimx_subap, num_dimy_subap), order='F'
        )
        inffuncdy[:, :, i] = interaction_matrix[half:, i].reshape(
            (num_dimx_subap, num_dimy_subap), order='F'
        )
        
        # Compute laplacian
        laplacian[:, :, i] = (
            deriv2D(inffuncdy[:, :, i], y=True) +
            deriv2D(inffuncdx[:, :, i], x=True)
        )
        
    return laplacian, inffuncdx, inffuncdy
import numpy as np
from .deriv2D import deriv2D  # Adjust import path as needed

def compute_laplacian(interaction_matrix, num_dimx_subap, num_dimy_subap):
    """
    Main function: compute laplacian and influence functions.
    """
    nact = interaction_matrix.shape[1]
    ncentroids = interaction_matrix.shape[0]
    half = ncentroids // 2

    inffuncdx, inffuncdy = compute_influence_functions(
        interaction_matrix, nact, half, num_dimx_subap, num_dimy_subap
    )
    
    laplacian = compute_laplacian_from_inffuncs(inffuncdx, inffuncdy)

    return laplacian, inffuncdx, inffuncdy

def compute_influence_functions(interaction_matrix, nact, half, num_dimx_subap, num_dimy_subap):
    """
    Reshape interaction matrix into dx and dy influence functions.
    """
    inffuncdx = np.zeros((num_dimx_subap, num_dimy_subap, nact), dtype=float)
    inffuncdy = np.zeros((num_dimx_subap, num_dimy_subap, nact), dtype=float)
    
    for i in range(nact):
        inffuncdx[:, :, i] = reshape_influence_vector(
            interaction_matrix[0:half, i], num_dimx_subap, num_dimy_subap
        )
        inffuncdy[:, :, i] = reshape_influence_vector(
            interaction_matrix[half:, i], num_dimx_subap, num_dimy_subap
        )
    
    return inffuncdx, inffuncdy

def reshape_influence_vector(vec, num_dimx_subap, num_dimy_subap):
    """
    Reshape 1D influence vector into 2D grid (Fortran order to match IDL).
    """
    return vec.reshape((num_dimx_subap, num_dimy_subap), order='F')

def compute_laplacian_from_inffuncs(inffuncdx, inffuncdy):
    """
    Compute Laplacian from dx and dy influence functions.
    """
    num_dimx_subap, num_dimy_subap, nact = inffuncdx.shape
    laplacian = np.zeros((num_dimx_subap, num_dimy_subap, nact), dtype=float)

    for i in range(nact):
        laplacian[:, :, i] = (
            deriv2D(inffuncdy[:, :, i], y=True) +
            deriv2D(inffuncdx[:, :, i], x=True)
        )
    
    return laplacian


def get_actuator_influence_slices(interaction_matrix, actuator_index, half):
    """
    Extracts the x and y centroid slices for a given actuator.
    """
    x_slice = interaction_matrix[0:half, actuator_index]
    y_slice = interaction_matrix[half:, actuator_index]
    return x_slice, y_slice



for i in range(nact):
    x_vec, y_vec = get_actuator_influence_slices(interaction_matrix, i, half)

    inffuncdx[:, :, i] = reshape_influence_vector(x_vec, num_dimx_subap, num_dimy_subap)
    inffuncdy[:, :, i] = reshape_influence_vector(y_vec, num_dimx_subap, num_dimy_subap)