#!/usr/bin/env python3
import numpy as np
import matplotlib.pyplot as plt
import argparse
import os

from astropy.io import fits

def quadrant_masks(N, angle_deg=0.0):
    """
    Generate 4 quadrant masks for an NxN image with optional axis rotation.

    Parameters
    ----------
    N : int
        Image size (NxN).
    angle_deg : float
        Rotation angle in degrees (counterclockwise).

    Returns
    -------
    masks : np.ndarray
        Array of shape (4, N, N) with dtype '>i8'.
        Order: [upper-left, lower-left, upper-right, lower-right].
    """
    # Grid of pixel centers
    y, x = np.meshgrid(np.arange(N), np.arange(N), indexing='ij')
    cx, cy = (N - 1) / 2.0, (N - 1) / 2.0
    x = x - cx
    y = y - cy

    # Rotate coordinates
    theta = np.deg2rad(angle_deg)
    xr =  x * np.cos(theta) + y * np.sin(theta)
    yr = -x * np.sin(theta) + y * np.cos(theta)

    # Allocate
    masks = np.zeros((4, N, N), dtype=">i8")

    # Quadrants (strict inequalities)
    masks[0] = (xr < 0) & (yr > 0)    # upper left
    masks[1] = (xr < 0) & (yr < 0)    # lower left
    masks[2] = (xr > 0) & (yr > 0)    # upper right
    masks[3] = (xr > 0) & (yr < 0)    # lower right

    # Axis tie-break rules
    masks[1] |= (xr <= 0) & (yr == 0)   # left side y=0
    masks[3] |= (xr >  0) & (yr == 0)   # right side y=0

    return masks

def main():
    parser = argparse.ArgumentParser(description="Generate 2x2 subaperture masks for an NxN image.")
    parser.add_argument("N", type=int, help="Image size (NxN, typically even).")
    parser.add_argument("--angle", type=float, default=0.0, help="Rotation angle in degrees (default: 0).")
    args = parser.parse_args()

    masks = quadrant_masks(args.N, args.angle)

    plt.figure()
    for i in range(4):
        plt.subplot(2, 2, i + 1)
        plt.imshow(masks[i], cmap='gray', origin='lower')
        plt.title(f"Mask {i+1}")
        plt.axis('off')
    plt.tight_layout()
    plt.show()

    filename = f"subaps2x2_{args.N}pix.fits"

    hdu_mask = fits.PrimaryHDU(masks.astype('>i8'))
    hdu_offsets = fits.ImageHDU(np.zeros(2, dtype='>i8'), name="OFFSETS")
    hdul = fits.HDUList([hdu_mask, hdu_offsets])
    hdul.writeto(filename, overwrite=True)
    
    print(f"Saved masks to {os.path.abspath(filename)}")

if __name__ == "__main__":
    main()
