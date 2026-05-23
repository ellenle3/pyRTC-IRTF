from sympy import factor

from pyRTC.WavefrontSensor import *
from pyRTC.Pipeline import *
from pyRTC.utils import *

import threading
from time import sleep

def gaussian2d(x, y, c0, s, a):
    """
    c0: tuple
        (x, y) coordinates of center
    """
    return a * np.exp( -((x-c0[0])**2 + (y-c0[1])**2) / (2*s*s) )

class FELIXSimulator(WavefrontSensor):
    """Simulates FELIX WFS data with white noise.
    """

    def __init__(self, conf):
        super().__init__(conf)
        self.simInjectedSlopes, self.slopesShape, self.slopesDType = initExistingShm("simInjectedSlopes",
                                                                                     gpuDevice=self.gpuDevice)
        
        self.downsampledImage = None
        if "bitDepth" in conf:
            self.setBitDepth(conf["bitDepth"])
        if "top" in conf and "left" in conf and "width" in conf and "height" in conf:
            roi=[conf["width"],conf["height"],conf["left"],conf["top"]]
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

        self._pause_event = threading.Event()
        self._pause_event.set()  # Start in unpaused state

        self.offsets = np.random.uniform(-self.slopeNoise, self.slopeNoise, (4,2))
        self.iter = 0
        return
        
    def make_felix_data(self):
        injectedSlopes = self.simInjectedSlopes.read_noblock()

        a = self.amplitude

        # Wait a certain number of iterations before updating. Otherwise system
        # can't keep up.
        if self.iter < self.lag:
            self.iter += 1
        else:
            self.iter = 0
            # New random offsets every lag iterations
            self.offsets = np.random.uniform(-self.slopeNoise, self.slopeNoise, (4,2))

        pt1 = self.calpts[0] + self.offsets[0] + injectedSlopes[0]
        pt2 = self.calpts[1] + self.offsets[1] + injectedSlopes[1]
        pt3 = self.calpts[2] + self.offsets[2] + injectedSlopes[2]
        pt4 = self.calpts[3] + self.offsets[3] + injectedSlopes[3]

        bias = self.bias
        detectorNoise = self.detectorNoise
        spot_size = self.spotSize
        image_size_x = self.roiWidth
        image_size_y = self.roiHeight

        xvals = np.arange(0, image_size_x) - image_size_x // 2
        yvals = np.arange(0, image_size_y) - image_size_y // 2
        X, Y = np.meshgrid(xvals, yvals)

        spot1 = gaussian2d(X, Y, pt1, spot_size, a)
        spot2 = gaussian2d(X, Y, pt2, spot_size, a)
        spot3 = gaussian2d(X, Y, pt3, spot_size, a)
        spot4 = gaussian2d(X, Y, pt4, spot_size, a)
        spots_all = spot1 + spot2 + spot3 + spot4

        spots_all += detectorNoise * np.random.uniform(0, 1, size=(image_size_x, image_size_y))
        spots_all += bias
        
        return spots_all

    def setRoi(self, roi):
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

    def expose(self):
        self._pause_event.wait()  # Wait if paused
        image = self.make_felix_data().astype(np.uint16)
        h, w = image.shape
        b = self.binning
        image = image[:h//b*b, :w//b*b].reshape(
            h//b, b, w//b, b).mean(axis=(1, 3))
        image = image.astype(np.uint16)
        self.data = image
        time.sleep(1e-3 + float(self.exposure))
        super().expose()
        return
    
    def pause(self):
        self._pause_event.clear()
        return

    def resume(self):
        self._pause_event.set()
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