from pyRTC.WavefrontSensor import *
from pyAndorSDK2 import atmcd, atmcd_codes, atmcd_errors
from pyRTC.Pipeline import *
from pyRTC.utils import *

from time import sleep
from functools import wraps


class AndorWFSSim(WavefrontSensor):
    """Simulates FELIX WFS data.
    """

    def __init__(self, conf):
        super().__init__(conf)
        
        self.downsampledImage = None
        if "bitDepth" in conf:
            self.setBitDepth(conf["bitDepth"])
        if "top" in conf and "left" in conf and "width" in conf and "height" in conf:
            roi=[conf["width"],conf["height"],conf["left"],conf["top"]]
            self.setRoi(roi)
        if "binning" in conf:
            self.setBinning(conf["binning"])
        if "exposure" in conf:
            self.setExposure(conf["exposure"])
        if "gain" in conf:
            self.setGain(conf["gain"])

        self.total_frames = 0

        return

    def _make_spot(loc, size, intensity=1.0):
        """Generates a 2D Gaussian spot."""
        xsize = self.roi.Width
        ysize = self.roi.Height
        x = np.linspace(-xsize/2, xsize/2, xsize)
        y = np.linspace(-ysize/2, ysize/2, ysize)
        X, Y = np.meshgrid(x, y)
        spot = intensity * np.exp(-((X - loc[0])**2 + (Y - loc[1])**2) / (2 * size**2))
        return spot

    def setRoi(self, roi):
        super().setRoi(roi)
        return

    def setExposure(self, exposure):
        super().setExposure(exposure)
        return
    
    def setBinning(self, binning):
        super().setBinning(binning)

        if self.binning in [1, 2, 4]:
            self.sdk.SetImage(
                hbin   = self.binning,
                vbin   = self.binning,
                hstart = self.roiLeft,
                hend   = self.roiLeft + self.roiWidth - 1,
                vstart = self.roiTop,
                vend   = self.roiTop + self.roiHeight - 1
            )
        return
    
    def setGain(self, gain):
        super().setGain(gain)
        return
    
    def setBitDepth(self, bitDepth):
        super().setBitDepth(bitDepth)
        return

    def expose(self):

        img = np.zeros((self.roiHeight, self.roiWidth)).astype(np.float32)
        # add spots
        img += 

        self.data = img
        super().expose()
        return

    def __del__(self):
        super().__del__()
        time.sleep(1e-1)
        return
    
if __name__ == "__main__":

    launchComponent(AndorWFSSim, "wfs", start = True)