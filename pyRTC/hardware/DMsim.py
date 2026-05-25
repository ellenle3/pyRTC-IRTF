from pyRTC.WavefrontCorrector import *
from pyRTC.Pipeline import *
from pyRTC.utils import *

from time import sleep


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

    def __init__(self, conf) -> None:
        #Initialize the pyRTC super class
        super().__init__(conf)
        self.simInjectedSlopes = ImageSHM("simInjectedSlopes", (4,2), np.float64, gpuDevice=self.gpuDevice, consumer=False)
        self.simInjectedSlopes.write(np.zeros((4,2)))

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

        return

    def loadIM(self, file = ''):
        if file == '':
            file = self.imatFile
        self.IM = np.load(file)
        return
    
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
        # Rotate by 45 degrees to match the orientation of the spots on the WFS
        slopes = np.vstack((xslopes, yslopes)).T
        self.simInjectedSlopes.write(slopes)
        return

    def __del__(self):
        # self.currentShape = np.zeros(self.numActuators)
        # self.sendToHardware()
        self.flatten()
        super().__del__()
        return
    
        
if __name__ == "__main__":

    launchComponent(IRTFASMSimulator, "wfc", start = True)