from sympy import factor

from pyRTC.WavefrontSensor import *
from pyRTC.Pipeline import *
from pyRTC.utils import *

from time import sleep

def gaussian2d(x, y, c0, s, a):
    """
    c0: tuple
        (x, y) coordinates of center
    """
    return a * np.exp( -((x-c0[0])**2 + (y-c0[1])**2) / (2*s*s) )

import time
import threading
import numpy as np
# Assuming gaussian2d, initExistingShm, and WavefrontSensor are imported elsewhere

class FELIXSimulator(WavefrontSensor):
    """Simulates FELIX WFS data with white noise."""

    def __init__(self, conf):
        super().__init__(conf)
        self.simInjectedSlopes, self.slopesShape, self.slopesDType = initExistingShm(
            "simInjectedSlopes", gpuDevice=self.gpuDevice)
        
        self.downsampledImage = None

        # --- NEW: Read detector size and center coordinate from config ---
        self.imageSize = conf.get("imageSize", 512)
        # Default the center coordinate to the middle of the detector
        self.spotCenter = conf.get("spotCenter", [self.imageSize // 2, self.imageSize // 2])
        
        # Initialize ROI defaults to full frame before config parsing
        super().setRoi([self.imageSize, self.imageSize, 0, 0])

        if "bitDepth" in conf:
            self.setBitDepth(conf["bitDepth"])
        if "top" in conf and "left" in conf and "width" in conf and "height" in conf:
            roi = [conf["width"], conf["height"], conf["left"], conf["top"]]
            self.setRoi(roi)
        if "binning" in conf:
            self.setBinning(conf["binning"])
        else:
            self.setBinning(1)
        if "exposure" in conf:
            self.setExposure(conf["exposure"])
        else:
            self.setExposure(0.001)
        if "gain" in conf:
            self.setGain(conf["gain"])
        if "lag" in conf:
            self.setLag(conf["lag"])
        else:
            self.setLag(0)

        self.setAmplitude(conf["amplitude"])
        self.setSlopeNoise(abs(conf["slopeNoise"]))
        self.calpts = np.load(conf["calPoints"])
        self.bias = conf["bias"]
        self.detectorNoise = conf["detectorNoise"]
        self.spotSize = conf["spotSize"]

        self.offsets = np.random.uniform(-self.slopeNoise, self.slopeNoise, (4,2))
        self.iter = 0
        return
    
    def setSpotCenter(self, center):
        """Set the center coordinate for the simulated spots."""
        self.spotCenter = center
        return
        
    def makeFelixData(self):
        injectedSlopes = self.simInjectedSlopes.read_noblock()
        a = self.amplitude

        # Wait a certain number of iterations before updating.
        if self.iter < self.lag:
            self.iter += 1
        else:
            self.iter = 0
            # New random offsets every lag iterations
            self.offsets = np.random.uniform(-self.slopeNoise, self.slopeNoise, (4,2))

        # Add the spotCenter offset to position the spots on the full detector
        pt1 = self.calpts[0] + self.offsets[0] + injectedSlopes[0] + self.spotCenter
        pt2 = self.calpts[1] + self.offsets[1] + injectedSlopes[1] + self.spotCenter
        pt3 = self.calpts[2] + self.offsets[2] + injectedSlopes[2] + self.spotCenter
        pt4 = self.calpts[3] + self.offsets[3] + injectedSlopes[3] + self.spotCenter

        bias = self.bias
        detectorNoise = self.detectorNoise
        spot_size = self.spotSize
        
        # --- NEW: Generate over the FULL detector size ---
        image_size_x = self.imageSize
        image_size_y = self.imageSize

        # Absolute coordinates [0, imageSize) instead of shifting by half
        xvals = np.arange(0, image_size_x)
        yvals = np.arange(0, image_size_y)
        X, Y = np.meshgrid(xvals, yvals)

        spot1 = gaussian2d(X, Y, pt1, spot_size, a)
        spot2 = gaussian2d(X, Y, pt2, spot_size, a)
        spot3 = gaussian2d(X, Y, pt3, spot_size, a)
        spot4 = gaussian2d(X, Y, pt4, spot_size, a)
        spots_all = spot1 + spot2 + spot3 + spot4

        # Add noise covering the full frame
        # Note: Size argument respects (Y, X) shape matching meshgrid output.
        spots_all += detectorNoise * np.random.uniform(0, 1, size=(image_size_y, image_size_x))
        spots_all += bias
        
        # --- NEW: Trim off the array to simulate the applied ROI ---
        trimmed_image = spots_all[
            self.roiTop : self.roiTop + self.roiHeight,
            self.roiLeft : self.roiLeft + self.roiWidth
        ]
        
        return trimmed_image

    def setRoi(self, roi):
        # Cache the ROI dimensions so we can trim the detector easily
        # Check if these are valid for a 512x512 detector
        width, height, left, top = roi
        if width <= 0 or height <= 0:
            print(f"Invalid ROI: Width and height must be strictly positive. Got width={width}, height={height}.")
            return
        
        if left < 0 or top < 0:
            print(f"Invalid ROI: Top and left coordinates cannot be negative. Got left={left}, top={top}.")
            return
        
        if (left + width) > self.imageSize or (top + height) > self.imageSize:
            print(
                f"Invalid ROI: Exceeds detector boundaries. "
                f"ROI spans X:[{left} to {left + width}], Y:[{top} to {top + height}], "
                f"but detector size is {self.imageSize}x{self.imageSize}."
            )
            return
        
        super().setRoi(roi)
        return

    def setExposure(self, exposure):
        super().setExposure(exposure)
        return
    
    def setBinning(self, binning):
        super().setBinning(binning)
        return
    
    def setGain(self, gain):
        super().setGain(gain)
        return
    
    def setBitDepth(self, bitDepth):
        super().setBitDepth(bitDepth)
        return
    
    def takeDark(self):
        # For simplicity, we won't simulate a separate dark frame. Just return the bias level.
        dark = np.full((self.roiHeight, self.roiWidth), self.bias, dtype=np.uint16)
        super().setDark(dark)
        time.sleep(1e-3)
        return

    def expose(self):
        image = self.makeFelixData().astype(np.uint16)
        h, w = image.shape
        b = self.binning
        image = image[:h//b*b, :w//b*b].reshape(
            h//b, b, w//b, b).mean(axis=(1, 3))
        image = image.astype(np.uint16)
        self.data = image
        time.sleep(1e-3 + float(self.exposure))
        super().expose()
        return
    
    def setLag(self, lag):
        self.lag = lag
        return
    
    def setAmplitude(self, amplitude):
        self.amplitude = amplitude
        return
    
    def setSlopeNoise(self, slopeNoise):
        self.slopeNoise = slopeNoise
        return

    def __del__(self):
        super().__del__()
        time.sleep(1e-1)
        return
        
if __name__ == "__main__":

    launchComponent(FELIXSimulator, "wfs", start = True)