# FILE: deriv2D.py

# Import packages
import numpy as np

def deriv2D(ima, x=False, y=False):
    """
    Compute derivative along x or y directions using 3-point Lagrangian rule.
    Adapted to compute over 2 points. The derivative is the same for both points
    in that case.
    
    Parameters:
    ima : 2D numpy array
        Input image or grid.
    x : bool
        If True, compute derivative along x (columns).
    y : bool
        If True, compute derivative along y (rows).
    
    Returns:
    result : 2D numpy array
        The derivative result.
    """
    ima = ima.astype(float)
    result = np.zeros_like(ima)

    if y:
        for i in range(ima.shape[0]):
            row = ima[i, :]
            n = row.size
            d = np.zeros_like(row)

            if n == 2:
                # Simple forward/backward difference
                diff = row[1] - row[0]
                d[0] = diff
                d[1] = diff
            else:
                # Middle points
                for j in range(1, n - 1):
                    d[j] = 0.5 * (row[j + 1] - row[j - 1])

                # Ends
                d[0]  = (-3.0 * row[0] + 4.0 * row[1] - row[2]) / 2.
                d[-1] = ( 3.0 * row[-1] - 4.0 * row[-2] + row[-3]) / 2.

            result[i, :] = d

    else:
        for i in range(ima.shape[1]):
            col = ima[:, i]
            n = col.size
            d = np.zeros_like(col)

            if n == 2:
                # Simple forward/backward difference
                diff = col[1] - col[0]
                d[0] = diff
                d[1] = diff
            else:
                # Middle points
                for j in range(1, n - 1):
                    d[j] = 0.5 * (col[j + 1] - col[j - 1])

                # Ends
                d[0]  = (-3.0 * col[0] + 4.0 * col[1] - col[2]) / 2.
                d[-1] = ( 3.0 * col[-1] - 4.0 * col[-2] + col[-3]) / 2.

            result[:, i] = d

    return result


def deriv2D_old(ima, x=False, y=False):
    """
    Compute derivative along x or y directions using 3-point Lagrangian rule.
    
    Parameters:
    ima : 2D numpy array
        Input image or grid.
    x : bool
        If True, compute derivative along x (columns).
    y : bool
        If True, compute derivative along y (rows).
    
    Returns:
    result : 2D numpy array
        The derivative result.
    """
    ima = ima.astype(float)
    result = np.zeros_like(ima)

    if y:
        for i in range(ima.shape[0]):
            row = ima[i, :]
            n = row.size
            d = np.zeros_like(row)

            # Middle points
            for j in range(1, n - 1):
                d[j] = 0.5 * (row[j + 1] - row[j - 1])

            # Ends
            d[0] = (-3.0 * row[0] + 4.0 * row[1] - row[2]) / 2.
            d[-1] = (3.0 * row[-1] - 4.0 * row[-2] + row[-3]) / 2.

            result[i, :] = d

    else:
        for i in range(ima.shape[1]):
            col = ima[:, i]
            n = col.size
            d = np.zeros_like(col)

            # Middle points
            for j in range(1, n - 1):
                d[j] = 0.5 * (col[j + 1] - col[j - 1])

            # Ends
            d[0] = (-3.0 * col[0] + 4.0 * col[1] - col[2]) / 2.
            d[-1] = (3.0 * col[-1] - 4.0 * col[-2] + col[-3]) / 2.

            result[:, i] = d

    return result

