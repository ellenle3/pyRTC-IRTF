
import subprocess
import numpy as np
from pyroics_soft import get_ics_proxy

PLATE_SCALE = 0.16 # "/pixel
POS_ANGLE = 2.3    # degrees, align image to sky coordinates

def Overseer():
    """Monitors components to make sure that they are in a safe and functional
    state.
    """
    def __init__(self):
        self.ics = get_ics_proxy()  # Communicate with AO loop and hardware
        self.offset_last = (0, 0)
        self.tasks = []

    def register_check(self, name, check_func, callback_func, frequency):
        """Registers a check function to be called at a specified frequency.
        """
        self.tasks.append({
            "name": name,
            "check_func": check_func,
            "callback_func": callback_func,
            "frequency": frequency,
            "last_run": 0
        })
        print(f"Registered check: {name} to run at {frequency} Hz.")
    
    def check_t3io_total_offset(self):
        """Retrieves the current guide box offsets from t3io.
        """
        result = subprocess.run(["t3io", "info", "OS"], capture_output=True, text=True)
        output = result.stdout.strip()
        output = output.split(' ')
        if output[0] != "OK":
            raise ConnectionError(f"t3io error. Output: {output}")
        
        # Format is OK TotalOS(ra dec) UserOS(ra dec enable) BeamOS(ra dec enable) ScanOS(ra dec) [all in arcsec]
        # We only care about the total offset
        offset_new = (output[1], output[2])
        return offset_new
    
    def set_last_offset_to_current(self):
        """Gets the current offset from t3io and sets it as the last known offset.
        Use at the beginning closed loop operations.
        """
        self.offset_last = self.check_t3io_total_offset()

    def update_t3io_guidebox(self, offset):
        """Changes the offset
        """
        if offset == self.offset_last:
            return
        if not self.ics.is_connected("slopes"):
            print("Slopes process not connected. Cannot update guide box.")
            return
        if not self.ics.is_connected("wfs"):
            print("Felix is not running. Cannot update the guide box.")
            return
        
        dra = offset[0] - self.offset_last[0]
        ddec = offset[1] - self.offset_last[1]

        # Convert to pixel offsets
        dx = dra / PLATE_SCALE
        dy = ddec / PLATE_SCALE

        # rotate ccw by the position angle to align with the camera coordinates
        theta = np.radians(POS_ANGLE)
        dx_rot = dx * np.cos(theta) - dy * np.sin(theta)
        dy_rot = dx * np.sin(theta) + dy * np.cos(theta)
        dx = dx_rot
        dy = dy_rot

        # subap masks are defined in terms of the final binned image
        binning = self.ics.get("slopes", "binning")
        dx /= binning
        dy /= binning
        dx = round(dx)
        dy = round(dy)
        
        # Update the subApMasks.
        x0 = self.ics.get("slopes", "xSubApOffset")  # Current mask center coordinates
        y0 = self.ics.get("slopes", "ySubApOffset")  # should always be integers
        cx = int(x0 + dx)
        cy = int(y0 + dy)
        self.ics.run("slopes", "makeSubApMasks", cx, cy)

        self.offset_last = offset
            
    def check_commands(self):
        """Monitors commands sent to ASM.
        """
        pass


if __name__=='__main__':
    overseer = Overseer()