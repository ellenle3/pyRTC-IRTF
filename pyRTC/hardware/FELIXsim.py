from pyRTC.WavefrontSensor import *
from pyRTC.WavefrontCorrector import *
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
    """Simulates FELIX WFS data with white noise.
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
        if "lag" in conf:
            self.lag = conf["lag"]
        else:
            self.lag = 0

        self.amplitude = conf["amplitude"]
        self.calpts = np.load(conf["calPoints"])
        self.bias = conf["bias"]
        self.detectorNoise = conf["detectorNoise"]
        self.slopeNoise = abs(conf["slopeNoise"])
        self.spotSize = conf["spotSize"]

        self.injectedSlopes = np.zeros_like(self.calpts)

        self.offsets = np.random.uniform(-self.slopeNoise, self.slopeNoise, (4,2))
        self.iter = 0
        return
    
    def updateInjectedSlopes(self, slopes):
        """Updates slope correction by the DM.
        """
        self.injectedSlopes = slopes
        return
    
    def make_felix_data(self):

        a = self.amplitude

        # Wait a certain number of iterations before updating. Otherwise system
        # can't keep up.
        if self.iter < self.lag:
            self.iter += 1
        else:
            self.iter = 0
            # New random offsets every lag iterations
            self.offsets = np.random.uniform(-self.slopeNoise, self.slopeNoise, (4,2))

        pt1 = self.calpts[0] + self.offsets[0] + self.injectedSlopes[0]
        pt2 = self.calpts[1] + self.offsets[1] + self.injectedSlopes[1]
        pt3 = self.calpts[2] + self.offsets[2] + self.injectedSlopes[2]
        pt4 = self.calpts[3] + self.offsets[3] + self.injectedSlopes[3]

        bias = self.bias
        detectorNoise = self.detectorNoise
        spot_size = self.spotSize
        image_size_x = self.roiWidth
        image_size_y = self.roiHeight

        xvals = np.arange(0, image_size_x)
        yvals = np.arange(0, image_size_y)
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

        self.data = self.make_felix_data().astype(np.uint16)
        time.sleep(5e-4)
        super().expose()
        return

    def __del__(self):
        super().__del__()
        time.sleep(1e-1)
        return

class IRTFASMSimulator(WavefrontCorrector):

    @staticmethod
    def generate_layout_irtf1():
        """Creates the layout of IRTF-ASM-1."""
        #xx, yy = np.meshgrid(np.arange(7), np.arange(7))
        #layout = np.sqrt((xx - 3)**2 + (yy-3)**2) < 3.2
        layout = np.full((6, 6), True, dtype=bool) # placeholder

        # can remove layout to make 2D vector faster, write custom viewer for plotting
        # actuator rings
        return layout

    def __init__(self, conf, wfs) -> None:
        #Initialize the pyRTC super class
        super().__init__(conf)

        self.numActuators = conf["numActuators"]
        self.CAP = conf["commandCap"]  # Maximum command amplitude

        layout = self.generate_layout_irtf1()
        self.setLayout(layout)

        # imat is needed to figure out what slopes to inject
        self.imatFile = conf["imatFile"]
        self.loadIM(self.imatFile)

        if conf["floatingActuatorsFile"][-4:] == '.npy':
            floatActuatorInds = np.load(conf["floatingActuatorsFile"])
            self.deactivateActuators(floatActuatorInds)

        #flatten the mirror
        self.flatten()

        if not isinstance(wfs, FELIXSimulator):
            raise ValueError("IRTFASMSimulator requires a FELIXSimulator WFS instance.")
        self.wfs = wfs
        return

    def loadIM(self, file = ''):
        if file == '':
            file = self.imatFile
        self.IM = np.load(file)
    
    def sendToHardware(self):
        #Do all of the normal updating of the super class
        super().sendToHardware()
        #Cap the Commands to reduce likelihood of DM failiure
        self.currentShape = np.clip(self.currentShape, -self.CAP, self.CAP)

        shapeToSend = self.currentShape.copy() - self.flat
        slopes = self.IM @ shapeToSend
        # slopes are x then y. Reshape to ((x,y), (x,y), ...)
        xslopes = slopes[:4]
        yslopes = slopes[4:]
        slopes = np.vstack((xslopes, yslopes)).T
        self.wfs.updateInjectedSlopes(slopes)
        return

    def __del__(self):
        super().__del__()
        self.currentShape = np.zeros(self.numActuators)
        self.sendToHardware()
        return
    
if __name__ == "__main__":

    launchComponent(FELIXSimulator, "wfs", start = True)