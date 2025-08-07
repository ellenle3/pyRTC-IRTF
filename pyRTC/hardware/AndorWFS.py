from pyRTC.WavefrontSensor import *
from pyAndorSDK2 import atmcd, atmcd_codes, atmcd_errors
from pyRTC.Pipeline import *
from pyRTC.utils import *

from time import sleep
from functools import wraps

def pause_acquisition(func):
    """Decorator to stop and start acquisition around a function call."""
    @wraps(func)
    def wrapper(self, *args, **kwargs):
        self.sdk.AbortAcquisition()
        result = func(self, *args, **kwargs)
        self.sdk.StartAcquisition()
        return result
    return wrapper

class AndorWFS(WavefrontSensor):
    """For Andor iXON ultra EMCCD.
    """

    def __init__(self, conf):
        super().__init__(conf)

        # Following documentation and example Image.py in Andor Linux SDK v2.104.30088.0
        self.sdk = atmcd()
        self.codes = atmcd_codes()
        self.errors = atmcd_codes.Error_Codes

        ret = self.sdk.Initialize("/usr/local/etc/andor")  # Initialize camera
        if ret != self.errors.AT_SUCCESS:
            raise RuntimeError(f"Failed to initialize Andor SDK: {self.sdk.GetErrorMessage(ret)}")

        self.sdk.SetReadMode(self.codes.Read_Mode.IMAGE)
        self.sdk.SetAcquisitionMode(self.codes.Acquisition_Mode.RUN_TILL_ABORT)

        # Begin running continuously. Kinetic cycle time to minimum possible amount (>0)
        self.sdk.SetKineticCycleTime(0)
        ret = self.sdk.StartAcquisition()
        
        self.downsampledImage = None
        if "bitDepth" in conf:
            self.setBitDepth(conf["bitDepth"])
        if "binning" in conf:
            self.setBinning(conf["binning"])
        if "exposure" in conf:
            self.setExposure(conf["exposure"])
        if "top" in conf and "left" in conf and "width" in conf and "height" in conf:
            roi=[conf["width"],conf["height"],conf["left"],conf["top"]]
            self.setRoi(roi)
        if "gain" in conf:
            self.setGain(conf["gain"])

        return

    @pause_acquisition
    def setRoi(self, roi):
        super().setRoi(roi)

        self.roiWidth = roi[0]
        self.roiHeight = roi[1]
        self.roiLeft = roi[2]
        self.roiTop = roi[3]

        self.sdk.SetImage(
            hbin   = self.binning,
            vbin   = self.binning,
            hstart = self.roiLeft,
            hend   = self.roiLeft + self.roiWidth - 1,
            vstart = self.roiTop,
            vend   = self.roiTop + self.roiHeight - 1
        )
        return
    
    @pause_acquisition
    def setExposure(self, exposure):
        super().setExposure(exposure)
        self.sdk.SetExposureTime(self.exposure)
        return
    
    @pause_acquisition
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
    
    @pause_acquisition
    def setGain(self, gain):
        super().setGain(gain)
        if self.sdk.IsPreAmpGainAvailable():
            self.sdk.SetPreAmpGain(self.gain)
        return
    
    @pause_acquisition
    def setBitDepth(self, bitDepth):
        super().setBitDepth(bitDepth)
        if self.bitDepth == 16:  # I think this always needs to be 16...
            self.sdk.SetBitsPerPixel(self.bitDepth)
        return

    def expose(self):
        
        # Wait until new image is available
        ret = self.sdk.GetNumberNewImages()
        while ret == self.errors.DRV_NO_NEW_DATA:
            ret = self.sdk.GetNumberNewImages()

        junk, self.data = self.sdk.GetMostRecentImage16()
        super().expose()
        return

    def __del__(self):
        super().__del__()
        time.sleep(1e-1)
        self.sdk.AbortAcquisition()
        # Do not shut down the camera as it is also used for target acquisition
        return
    
if __name__ == "__main__":

    launchComponent(AndorWFS, "wfs", start = True)