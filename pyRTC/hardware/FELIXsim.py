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

class FELIXSimulator(WavefrontSensor):
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

        self.amplitude = conf["amplitude"]
        self.calpts = np.load(conf["cal_pts"])
        self.bias = conf["bias"]
        self.noise = conf["noise"]
        self.spot_size = conf["spot_size"]

        self.total_frames = 0

        return
    
    def make_felix_data(self):

        a = self.amplitude
        pt1 = self.calpts[0]
        pt2 = self.calpts[1]
        pt3 = self.calpts[2]
        pt4 = self.calpts[3]
        bias = self.bias
        noise = self.noise
        spot_size = self.spot_size
        image_size_x = self.roiWidth
        image_size_y = self.roiHeight

        xvals = np.arange(-image_size_x/2, image_size_x/2)
        yvals = np.arange(-image_size_y/2, image_size_y/2)
        X, Y = np.meshgrid(xvals, yvals)

        spot1 = gaussian2d(X, Y, pt1, spot_size, a)
        spot2 = gaussian2d(X, Y, pt2, spot_size, a)
        spot3 = gaussian2d(X, Y, pt3, spot_size, a)
        spot4 = gaussian2d(X, Y, pt4, spot_size, a)
        spots_all = spot1 + spot2 + spot3 + spot4

        spots_all += noise * np.random.uniform(0, 1, size=(image_size_x, image_size_y))
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

        self.data = self.make_felix_data().astype(np.uint16)
        super().expose()
        return

    def __del__(self):
        super().__del__()
        time.sleep(1e-1)
        return
    
if __name__ == "__main__":

    launchComponent(FELIXSimulator, "wfs", start = True)