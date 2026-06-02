
import subprocess
import time
import threading
import numpy as np
from pyroics import get_ics_proxy

PLATE_SCALE = 0.16 # "/pixel
POS_ANGLE = 2.3 - 90   # degrees, align image to sky coordinates
SLEW_SPEED = 1800 # fast slew speed "/s
TT_TO_RADEC_FILE = "/home/felix/src/pyrtc/pyRTC-IRTF/IRTF/calib/tt_to_radec.npy"  # numpy file containing a 2D grid of tip-tilt values corresponding to RA and Dec offsets, generated from Zemax
DRA_MAX, DDEC_MAX = 0.2, 0.2  # max pointing adjustment before error
TT_OFFLOAD_GAIN = 0.1 # gain for offloading tip-tilt corrections

def print_color(s: str, c: str) -> None:
    """Prints a colored string.

    Options: 'red', 'green', 'yellow', 'blue', 'magenta', 'cyan', 'black', 'white',
        'bold', 'underline'
    """
    color_dict = {
        'red': '\033[31m',
        'green': '\033[32m',
        'yellow': '\033[33m',
        'blue': '\033[34m',
        'magenta': '\033[35m',
        'cyan': '\033[36m',
        'black': '\033[30m',
        'white': '\033[37m',
        'bold':'\033[1m',
        'underline': '\033[4m'
    }
    assert c in color_dict, "The ANSI escape sequence for c must be defined print_color"

    color_code = color_dict[c]
    end_code = '\033[0m'
    print(f'{color_code}' + s + f'{end_code}')

class Overseer():
    """Monitors components to make sure that they are in a safe and functional
    state. Runs registered checks continuously in a background thread, each
    at its own specified frequency.
    """
    def __init__(self):
        self.offset_last = (0, 0)
        self.tt_to_radec = np.load(TT_TO_RADEC_FILE)
        self.ns_rra, self.ns_rdec = (0, 0)

        self.tasks = {}
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def _run_loop(self):
        """Main loop. Runs in a background thread, dispatching checks based on
        their individual frequencies.
        """
        while not self._stop_event.is_set():
            now = time.monotonic()
            with self._lock:
                tasks_snapshot = list(self.tasks.values())

            for task in tasks_snapshot:
                interval = 1.0 / task["frequency"]
                if now - task["last_run"] >= interval:
                    try:
                        result = task["check_func"]()
                        task["callback_func"](result)
                    except Exception as e:
                        print(f"[Overseer] Error in task '{task['name']}': {e}")
                    task["last_run"] = now

            time.sleep(0.001)  # 1 ms idle to avoid busy-waiting

    def stop(self):
        """Signals the background thread to stop and waits for it to exit."""
        self._stop_event.set()
        self._thread.join()

    def register_check(self, name, check_func, callback_func, frequency):
        """Registers a check function to be called at a specified frequency (Hz).
        Replaces any existing task with the same name.
        """
        with self._lock:
            self.tasks[name] = {
                "name": name,
                "check_func": check_func,
                "callback_func": callback_func,
                "frequency": frequency,
                "last_run": 0.0
            }
        print(f"Registered check: '{name}' at {frequency} Hz.")

    def deregister_check(self, name):
        """Removes a registered check by name. No-op if the name is not found."""
        with self._lock:
            if name in self.tasks:
                del self.tasks[name]
                print(f"Deregistered check: '{name}'.")
            else:
                print(f"[Overseer] Warning: no task named '{name}' to deregister.")

    def radec_to_xy(self, dra, ddec):
        """Converts RA and Dec offsets to pixels using the plate scale and position
        angle. Returns subpixel values (floats).
        """
        if not ics.is_connected("wfs"):
            print("Felix is not running.")
            return
        
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
        ics = get_ics_proxy()
        binning = ics.get("wfs", "binning")
        dx /= binning
        dy /= binning

        return dx, dy
    
    # Slewing
    def is_telescope_slewing(self):
        """Checks if the telescope is currently slewing by querying t3io.
        """
        result = subprocess.run(["t3io", "info", "sm"], capture_output=True, text=True)
        output = result.stdout.strip()
        output = output.split(' ')
        if output[0] != "OK":
            raise ConnectionError(f"t3io error. Output: {output}")
        
        is_slew = (output[1] == "slew")
        est_time = int(output[2])  # estimated time remaining in seconds, if slewing
                                   # 0 otherwise
        return is_slew, est_time
    
    def open_loop_if_closed(self, slew_state):
        """Opens the loop if it is currently closed. Returns True if the loop was
        open or was successfully opened, False if there was an error.
        """
        ics = get_ics_proxy()
        is_slew, est_time = slew_state
        if not is_slew:
            return True  # not slewing, no need to open loop

        if not ics.is_connected("loop"):
            print("Loop process not connected. Cannot check loop state.")
            return False
        if ics.is_closed_loop():
            print_color("Slew detected while closed loop! Opening the loop...", "red")
            ics.open_loop()
            return True
        
        return True

    # TCS offsets
    def get_tcs_total_offset(self):
        """Retrieves the current guide box offsets from t3io.
        """
        result = subprocess.run(["t3io", "info", "OS"], capture_output=True, text=True)
        output = result.stdout.strip()
        output = output.split(' ')
        if output[0] != "OK":
            raise ConnectionError(f"t3io error. Output: {output}")
        
        # Format is OK TotalOS(ra dec) UserOS(ra dec enable) BeamOS(ra dec enable) ScanOS(ra dec) [all in arcsec]
        # We only care about the total offset
        offset_new = (float(output[1]), float(output[2]))
        return offset_new
    
    def get_tcs_nonsidereal(self):
        result = subprocess.run(["t3io", "info", "NS"], capture_output=True, text=True)
        output = result.stdout.strip()
        output = output.split(' ')
        if output[0] != "OK":
            raise ConnectionError(f"t3io error. Output: {output}")
        
        # Format is OK ra dec
        ns_rra, ns_rdec = (float(output[1]), float(output[2]))
        return ns_rra, ns_rdec  # rra = rate ra, rdec = rate dec in arcsec/s

    def set_last_offset_to_current(self):
        """Gets the current offset from t3io and sets it as the last known offset.
        Use at the beginning closed loop operations.
        """
        self.offset_last = self.get_tcs_total_offset()

    def update_guidebox(self, offset):
        """Changes the subaperture masks (basically the guidebox) based differences
        between the last offset and current offset reported by t3io.
        """
        if offset == self.offset_last:
            return  # no change, no need to update
        ics = get_ics_proxy()
        if not ics.is_connected("slopes"):
            print("Slopes process not connected. Cannot update guide box.")
            return
        if not ics.is_connected("loop"):
            print("Loop process not connected.")
            return
        if not ics.is_connected("wfc"):
            print("ASM not connected.")
            return
        
        print(f"Updating guide box from offset: {offset}")
        
        dra = offset[0] - self.offset_last[0]
        ddec = offset[1] - self.offset_last[1]

        dx, dy = self.radec_to_xy(dra, ddec)
        dx = round(dx)
        dy = round(dy)
        
        # Update the subApMasks.
        x0 = ics.get("slopes", "xSubApOffset")  # Current mask center coordinates
        y0 = ics.get("slopes", "ySubApOffset")  # should always be integers
        cx = int(x0 - dx)
        cy = int(y0 - dy)

        # If loop is currently closed, we need to open it before changing the masks,
        # then wait for the telescope to finish slewing, and then close the loop again.
        is_close_again = ics.is_closed_loop()
        if is_close_again:
            ics.open_loop()
        
        result = ics.run("slopes", "makeSubApMasks", cx, cy)
        if result == -1:
            print("Failed to update guide box from offset.")
            return
        
        if is_close_again:
            total_offset = np.sqrt( dra**2 + ddec**2 )
            # multiply by 2 in case we're going in the slow direction
            slew_time = 2 * total_offset / SLEW_SPEED
            slew_time += 1  # add a second to be safe... offset will usually be a few arcseconds, so very fast
            time.sleep(slew_time)

            # Reset slope calculation before closing the loop or it might see
            # a huge amount of residual tilt from the end of the last exposure
            #ics.run("wfs", "expose")
            ics.close_loop()

        self.offset_last = offset
    
    # Tilt on ASM
    def get_asm_tilt(self):
        """Retrieves current tilt on the ASM.
        """
        # pyRTC has a command cap built in, so we shouldn't have
        ics = get_ics_proxy()
        if not ics.is_connected("wfc"):
            print("ASM not connected. Cannot check tilt.")
            return (0, 0)
        tip, tilt = ics.run("wfc", "getAverageTipTilt")
        return (tip, tilt)
    
    def offload_asm_tilt_to_tcs(self, tiptilt):
        """Offloads tilt from the ASM to the TCS if it exceeds a certain threshold.
        """
        tip, tilt = tiptilt
        dra, ddec = -1 * TT_OFFLOAD_GAIN * self.tt_to_radec @ np.array([tip, tilt])
        if abs(dra) > DRA_MAX or abs(ddec) > DDEC_MAX:
            print(f"Offload amount too large! Not sending to TCS: dra={dra}, ddec={ddec}")
        ddec *= -1
        dra_send = str( round(dra, 2) )
        ddec_send = str( round(ddec, 2) )
        # use pt.peak.inc to adjust telescope pointing (does not show up in total offset)
        result = subprocess.run(["t3io", "pt.peak.inc", dra_send, ddec_send], capture_output=True, text=True)
        output = result.stdout.strip()
        output = output.split(' ')
        if output[0] != "OK":
            print(f"t3io error when offloading tilt. Output: {output}")
        print(f"Offloading tilt to TCS: dra={dra_send}, ddec={ddec_send}")

    def show_current_tilt(self, tiptilt):
        #debug
        tip, tilt = tiptilt
        print(f"Current tilt - Tip: {tip}, Tilt: {tilt}")
    
    def is_wfs_snr_ok(self):
        """Returns True if the signal-to-noise ratio in the WFS is okay. 
        """
        # run estimate SNR but make sure to average over a few frames
        pass

    def offload_tilt_to_tcs(self):
        """Offloads tilt from the ASM to the TCS if it exceeds a certain threshold.
        """
        tilt = self.get_asm_tilt()
        

if __name__=='__main__':
    overseer = Overseer()
    overseer.set_last_offset_to_current()  # initialize the last offset to the current TCS offset at startup
    
    # Update the guidebox (subap masks) based on TCS offsets
    overseer.register_check(
        name="guidebox_offset",
        check_func=overseer.get_tcs_total_offset,
        callback_func=overseer.update_guidebox,
        frequency=10
    )

    # # Open the loop if slewing, and the loop is closed
    # overseer.register_check(
    #     name="open_if_slew",
    #     check_func=overseer.is_telescope_slewing,
    #     callback_func=overseer.open_loop_if_closed,
    #     frequency=10
    # )
    
    # DO NOT HAVE AS USER OFFSETS SINCE IT WILL MESS UP TCS POINTING!
    # Offloads tilt from the ASM to the TCS
    overseer.register_check(
        name="tilt_monitor",
        check_func=overseer.get_asm_tilt,
        callback_func=overseer.offload_asm_tilt_to_tcs,
        frequency=0.2
    )

    overseer._thread.join()  # keep main thread alive