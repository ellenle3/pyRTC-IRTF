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
        self.codes = atmcd_codes
        self.errors = atmcd_errors.Error_Codes

        self.sdk.Initialize("/usr/local/etc/andor")  # Initialize camera, directory is valid for Linux
        self.sdk.SetReadMode(self.codes.Read_Mode.IMAGE)
        self.sdk.SetShutter(1, 1, 0, 0)
        #self.openShutter() # always open for Andor iXon L. opening and closing time is 0 ms
        self.sdk.SetAcquisitionMode(self.codes.Acquisition_Mode.RUN_TILL_ABORT)
        self.sdk.SetTriggerMode(self.codes.Trigger_Mode.INTERNAL)

        # Begin running continuously. Kinetic cycle time to minimum possible amount (>0)
        self.sdk.SetKineticCycleTime(0)

        self.sdk.PrepareAcquisition()
        self.sdk.StartAcquisition()
        
        self.downsampledImage = None
        if "bitDepth" in conf:
            self.setBitDepth(conf["bitDepth"])
        # ROI needs to be set before binning
        if "top" in conf and "left" in conf and "width" in conf and "height" in conf:
            roi=[conf["width"],conf["height"],conf["left"],conf["top"]]
            self.setRoi(roi)
        if "binning" in conf:
            self.setBinning(conf["binning"])
        if "exposure" in conf:
            self.setExposure(conf["exposure"])
        if "gain" in conf:
            self.setGain(conf["gain"])
        #if "HSSpeedIndex" in conf and "VSSpeedIndex" in conf:
        #    self.setReadout(conf["HSSpeedIndex"], conf["VSSpeedIndex"])
        #else:
        #    self.setReadout(hi=0, vi=0)  # 17 MHz, 0.3 us. Note that recommended VSS is 3 us (vi=5)
        
        #hi = setFromConfig(conf, "HSSpeedIndex", 0)
        #vi = setFromConfig(conf, "VSSpeedIndex", 0)
        #self.setReadout(hi, vi)

        self.coadds = setFromConfig(conf, "coadds", 1)

        temperature = setFromConfig(conf, "temperature", -65)
        self.setTemperature(temperature)

        self.oldTotalFrames = 0
        return

    @pause_acquisition
    def openShutter(self):
        self.sdk.SetShutter(1, 1, 0, 0)

    @pause_acquisition
    def closeShutter(self):
        self.sdk.SetShutter(1, 2, 0, 0)

    @pause_acquisition
    def startCooler(self):
        self.sdk.CoolerON()
        return
    
    @pause_acquisition
    def stopCooler(self):
        self.sdk.CoolerOFF()
        return
    
    @pause_acquisition
    def setTemperature(self, temperature):
        self.sdk.SetTemperature(temperature)
        self.startCooler()
        return

    @pause_acquisition
    def setReadout(self, hi, vi):
        return
        #self.sdk.SetHSSpeed(0, hi)
        #self.sdk.SetVSSpeed(vi)
        #return

    @pause_acquisition
    def setRoi(self, roi):
        super().setRoi(roi)
 
        if not hasattr(self, "binning"):
            super().setBinning(1)
        
        self.sdk.SetImage(
            hbin   = self.binning,
            vbin   = self.binning,
            hstart = self.roiLeft,
            hend   = self.roiLeft + self.roiWidth - 1,
            vstart = self.roiTop,
            vend   = self.roiTop + self.roiHeight - 1
        )

        # Update number of pixels
        self.size = int( self.roiWidth * self.roiHeight / (self.binning * self.binning) )
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

        # Update number of pixels
        self.size = int( self.roiWidth * self.roiHeight / (self.binning * self.binning) )
        return
    
    @pause_acquisition
    def setGain(self, gain):
        super().setGain(gain)
        #if self.sdk.IsPreAmpGainAvailable():
        #    self.sdk.SetPreAmpGain(self.gain)
        return
    
    @pause_acquisition
    def setBitDepth(self, bitDepth):
        super().setBitDepth(bitDepth)
        if self.bitDepth == 16:  # I think this always needs to be 16...
            self.sdk.SetBitsPerPixel(self.bitDepth)
        return

    def expose(self):
        # Check if total number of frames has changed
        images = []
        for i in range(self.coadds):
            ret, newTotal = self.sdk.GetTotalNumberImagesAcquired()

            # Hasn't increased yet. Wait for acquisition to complete
            if newTotal <= self.oldTotalFrames:
                ret = self.sdk.WaitForAcquisition()
                newTotal += 1

            ret, raw = self.sdk.GetMostRecentImage16(self.size)
            raw = np.array(raw, copy=True)
            img = raw.reshape((self.roiHeight//self.binning, self.roiWidth//self.binning))

            images.append(img.astype(np.uint16))
            self.oldTotalFrames = newTotal
        
        self.data = np.sum(images, axis=0)
        super().expose()
        return

    def __del__(self):
        super().__del__()
        time.sleep(1e-1)
        self.sdk.AbortAcquisition()
        self.sdk.SetAcquisitionMode(self.codes.Acquisition_Mode.SINGLE_SCAN)
        self.sdk.ShutDown()  # clean up
        return
    
    def showAvailableReadout(self):
        # Copy of example ReadOutRates.py
        sdk = self.sdk

        HSSpeeds = []
        VSSpeeds = []
        amp_modes = []

        (ret, ADchannel) = sdk.GetNumberADChannels()
        print("Function GetNumberADChannels returned {} number of available channels {}".format(
            ret, ADchannel))
        for channel in range(0, ADchannel):
            (ret, speed) = sdk.GetNumberHSSpeeds(channel, 0)
            print("Function GetNumberHSSpeeds {} number of available speeds {}".format(
                ret, speed))
            for x in range(0, speed):
                (ret, speed) = sdk.GetHSSpeed(channel, 0, x)
                HSSpeeds.append(speed)

            print("Available HSSpeeds in MHz {} ".format(HSSpeeds))

            (ret, speed) = sdk.GetNumberVSSpeeds()
            print("Function GetNumberVSSpeeds {} number of available speeds {}".format(
                ret, speed))
            for x in range(0, speed):
                (ret, speed) = sdk.GetVSSpeed(x)
                VSSpeeds.append(speed)
            print("Available VSSpeeds in us {}".format(VSSpeeds))

            (ret, index, speed) = sdk.GetFastestRecommendedVSSpeed()
            print("Recommended VSSpeed {} index {}".format(speed, index))

            (ret, amps) = sdk.GetNumberAmp()
            print("Function GetNumberAmp returned {} number of amplifiers {}".format(ret, amps))
            for x in range(0, amps):
                (ret, name) = sdk.GetAmpDesc(x, 21)
                amp_modes.append(name)

            print("Available amplifier modes {}".format(amp_modes))

    
if __name__ == "__main__":

    launchComponent(AndorWFS, "wfs", start = True)
