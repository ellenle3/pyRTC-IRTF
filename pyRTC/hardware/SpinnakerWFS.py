from pyRTC.WavefrontSensor import *
import PySpin
import time

from functools import wraps

def pause_acquisition(func):
    """Decorator to stop and start acquisition around a function call."""
    @wraps(func)
    def wrapper(self, *args, **kwargs):
        self.cam.EndAcquisition()
        result = func(self, *args, **kwargs)
        self.cam.BeginAcquisition()
        return result
    return wrapper

class SpinnakerWFS(WavefrontSensor):

    # This doesn't use rotpy, which appears to be incompatible with Spinnaker v4

    def __init__(self, conf):
        super().__init__(conf)
        
        self.spin_system = PySpin.System.GetInstance()
        self.cam_list = self.spin_system.GetCameras()
        self.iface_list = self.spin_system.GetInterfaces()
        self.index = conf["index"]

        # If you have a problem initalizing the camera due to an XML error, try
        # opening the camera in SpinView restarting the live view (start, stop, start).        
        # Then you can initialize it here, stop the acquisition in the GUI, and
        # close SpinView. You might have to do this a few times.
        self.cam = self.cam_list.GetByIndex(self.index)
        self.cam.Init()

        self.nodemap = self.cam.GetNodeMap()
        self.roi_nodes = {
            "width": PySpin.CIntegerPtr(self.nodemap.GetNode('Width')),
            "height": PySpin.CIntegerPtr(self.nodemap.GetNode('Height')),
            "offset_x": PySpin.CIntegerPtr(self.nodemap.GetNode('OffsetX')),
            "offset_y": PySpin.CIntegerPtr(self.nodemap.GetNode('OffsetY')),
        }
        self.binning_nodes = {
            "horizontal": PySpin.CIntegerPtr(self.nodemap.GetNode('BinningHorizontal')),
            "vertical": PySpin.CIntegerPtr(self.nodemap.GetNode('BinningVertical'))
        }

        set_stream_mode(self.cam)
        self.handler = ImageEventHandler()
        self.cam.RegisterEventHandler(self.handler)

        self.cam.ExposureAuto.SetValue(PySpin.ExposureAuto_Continuous)
        self.cam.BeginAcquisition()
        self._last_frame_id = 0

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
        if "numBuffers" in conf:
            self.setNumBuffers(conf["numBuffers"])
        return
    
    @staticmethod
    def is_node_changeable(node):
        return PySpin.IsAvailable(node) and PySpin.IsWritable(node)
    
    def setNumBuffers(self, numBuffers):

        s_node_map = self.cam.GetTLStreamNodeMap()
        node_stream_buffer_count_manual = PySpin.CIntegerPtr(s_node_map.GetNode
        ("StreamBufferCountManual"))
        node_stream_buffer_count_manual.SetValue(numBuffers)  # 10 by default

    @pause_acquisition
    def setRoi(self, roi):        
        super().setRoi(roi)

        for node in self.roi_nodes:
            if not self.is_node_changeable(self.roi_nodes[node]):
                return

        try:
            # might fail if ROI is not incremented correctly
            self.roi_nodes["width"].SetValue(self.roiWidth)
            self.roi_nodes["height"].SetValue(self.roiHeight)
            self.roi_nodes["offset_x"].SetValue(self.roiLeft)
            self.roi_nodes["offset_y"].SetValue(self.roiTop)
        except PySpin.SpinnakerException as ex:
            print('Error: %s' % ex)
            return

        # Update number of pixels
        self.size = self.roiWidth * self.roiHeight
        return

    @pause_acquisition 
    def setExposure(self, exposure):
        super().setExposure(exposure)
        self.cam.ExposureAuto.SetValue(PySpin.ExposureAuto_Off)
        self.cam.ExposureMode.SetValue(PySpin.ExposureMode_Timed)
        self.cam.ExposureTime.SetValue(self.exposure)
        return

    @pause_acquisition
    def setBinning(self, binning):
        super().setBinning(binning)

        if self.binning not in [1, 2, 4]:
            return
        
        # Usually change one, the other is locked to the same value. Check if at
        # least one is writable.
        if not any(self.is_node_changeable(self.binning_nodes[node]) for node in self.binning_nodes):
            return

        # This doesn't work in __init__ unless roi is called before.
        # Change roi to match new binning. Otherwise current roi might be too large.
        # new_width = int(self.roiWidth / self.binning)
        # new_height = int(self.roiHeight / self.binning)
        # new_left = int(self.roiLeft / self.binning)
        # new_top = int(self.roiTop / self.binning)

        # if new_left % 4 != 0:
        #     new_left -= new_left % 4      # x must be divisible by 4
        # if new_top % 2 != 0:
        #     new_top -= new_top % 2        # y must be divisible by 2
        # if new_width % 16 != 0:
        #     new_width -= new_width % 16   # width must be divisible by 16
        # if new_height % 2 != 0:
        #     new_height -= new_height % 2  # height must be divisible by 2

        # self.setRoi([new_width, new_height, new_left, new_top])

        # Will throw an error for the one that isn't writable
        try:
            self.binning_nodes["horizontal"].SetValue(self.binning)
        except:
            pass
        try:
            self.binning_nodes["vertical"].SetValue(self.binning)
        except:
            pass
        return
    
    @pause_acquisition
    def setGain(self, gain):
        super().setGain(gain)
        self.cam.GainAuto.SetValue(PySpin.GainAuto_Off)
        self.cam.Gain.SetValue(gain)
        return
    
    @pause_acquisition
    def setBitDepth(self, bitDepth):
        super().setBitDepth(bitDepth)
        node_pixel_format = PySpin.CEnumerationPtr(self.nodemap.GetNode("PixelFormat"))
        if not self.is_node_changeable(node_pixel_format):
            return

        if bitDepth == 8:
            entry = node_pixel_format.GetEntryByName("Mono8")
        elif bitDepth == 12:
            # Some cameras use Mono12p (packed) or Mono12 depending on model
            entry = node_pixel_format.GetEntryByName("Mono12p") or node_pixel_format.GetEntryByName("Mono12")
        elif bitDepth == 16:
            entry = node_pixel_format.GetEntryByName("Mono16")

        if not PySpin.IsAvailable(entry) or not PySpin.IsReadable(entry):
            return

        pixel_format_value = entry.GetValue()
        node_pixel_format.SetIntValue(pixel_format_value)

        return

    def expose(self):
        arr, new_id = self.handler.wait_for_new_image(self._last_frame_id)
        self._last_frame_id = new_id
        self.data = arr
        super().expose()
        return

    def __del__(self):
        super().__del__()
        time.sleep(1e-1)
        try:
            self.cam.EndAcquisition()
        except:
            print("Could not end acquisition")
        self.cam.DeInit()
        del self.cam
        
        self.cam_list.Clear()
        self.iface_list.Clear()
        self.spin_system.ReleaseInstance()
        return
    
class ImageEventHandler(PySpin.ImageEventHandler):
    """Class to handle image acquisition events. Based on the example ImageEvents.py.
    """

    def __init__(self):
        """
        Constructor.
        """
        super(ImageEventHandler, self).__init__()
        self._lock = threading.Lock()
        self._cond = threading.Condition(self._lock)
        self._latest_array = None
        self._frame_id = 0

    def OnImageEvent(self, image):
        if image.IsIncomplete():
            image.Release()
            return

        arr = np.array(image.GetNDArray(), dtype=np.uint16, copy=True)
        image.Release()

        with self._cond:
            self._latest_array = arr
            self._frame_id += 1
            self._cond.notify_all()

    def wait_for_new_image(self, last_id):
        """
        Block until there is a valid image, then return it as a numpy array.
        """
        with self._cond:
            while self._frame_id <= last_id:
                self._cond.wait()
            return self._latest_array, self._frame_id


def set_stream_mode(cam):
    """
    This function changes the stream mode. Taken from example Acquisition.py.

    :param cam: Camera to change stream mode.
    :type cam: CameraPtr
    :type nodemap_tlstream: INodeMap
    :return: True if successful, False otherwise.
    :rtype: bool
    """
    streamMode = "Socket"  # always use socket if not Windows

    result = True

    # Retrieve Stream nodemap
    nodemap_tlstream = cam.GetTLStreamNodeMap()

    # In order to access the node entries, they have to be casted to a pointer type (CEnumerationPtr here)
    node_stream_mode = PySpin.CEnumerationPtr(nodemap_tlstream.GetNode('StreamMode'))

    # The node "StreamMode" is only available for GEV cameras.
    # Skip setting stream mode if the node is inaccessible.
    if not PySpin.IsReadable(node_stream_mode) or not PySpin.IsWritable(node_stream_mode):
        return True

    # Retrieve the desired entry node from the enumeration node
    node_stream_mode_custom = PySpin.CEnumEntryPtr(node_stream_mode.GetEntryByName(streamMode))

    if not PySpin.IsReadable(node_stream_mode_custom):
        # Failed to get custom stream node
        print('Stream mode ' + streamMode + ' not available. Aborting...')
        return False

    # Retrieve integer value from entry node
    stream_mode_custom = node_stream_mode_custom.GetValue()

    # Set integer as new value for enumeration node
    node_stream_mode.SetIntValue(stream_mode_custom)

    print('Stream Mode set to %s...' % node_stream_mode.GetCurrentEntry().GetSymbolic())
    return result


if __name__ == "__main__":

    launchComponent(SpinnakerWFS, "wfs", start = True)
        
