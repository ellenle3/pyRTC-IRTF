"""These worker classes exist to prevent the GUI from hanging itself if it
encounters an error.
"""
import time
import signal
from PyQt6.QtCore import QTimer, QEvent, QThread, pyqtSignal

from IRTF.gui.pyroics import get_ics_proxy


class SimCamInitWorker(QThread):
    log_signal = pyqtSignal(str, str)
    status_cam_signal = pyqtSignal(str)
    status_ASM_signal = pyqtSignal(str)
    done = pyqtSignal(str)  # pass back name so caller knows which finished

    def __init__(self, name, log=None):
        super().__init__()
        self.name = name
        self.log = log

    def run(self):
        ics = get_ics_proxy()  # New proxy has to go in the run thread, not main

        # Simulated ASM first since SimCam depends on ASM slope shared memory to
        # inject a fake signal into the simulator.
        self.status_ASM_signal.emit("Initializing SimASM")
        self.log_signal.emit("Connecting to ASM simulator...", "blue")

        if ics.is_connected("wfc"):
            # Give it a moment to finish any current operations
            self.log_signal.emit("Stopping the ASM. You will need to re-initialize the hardware.", "red")
            ics.shutdown("wfc")
        
        ics.launch("IRTFASMSimulator")
        self.status_ASM_signal.emit("SimASM connected")
        
        # SimCam (simulated Felix)
        self.status_cam_signal.emit("Initializing SimCam")
        self.log_signal.emit("Connecting to Felix simulator...", "blue")
        ics.launch("FELIXSimulator")
        ics.run("wfs", "stop")
        self.status_cam_signal.emit("Ready for acquisition")
        self.done.emit(self.name)

class LoopInitWorker(QThread):
    # Class to launch DM, slopes, and loop processes.
    log_signal = pyqtSignal(str, str)
    status_ASM_signal = pyqtSignal(str)
    status_loop_signal = pyqtSignal(str)
    done = pyqtSignal(str)  # pass back name so caller knows which finished

    def __init__(self, name):
        super().__init__()
        self.name = name

    def run(self):
        ics = get_ics_proxy()  # New proxy has to go in the run thread, not main

        # Start the ASM first, but skip if the simulator is running.
        if not ics.is_connected("wfc"):
            self.status_ASM_signal.emit("Initializing IRTF-ASM-1")
            self.log_signal.emit("Connecting to the ASM. Please wait...", "blue")

            ics.launch("ImakaDM")
            ics.run("wfc", "start")
            self.status_ASM_signal.emit("IRTF-ASM-1 connected")        

        # Next is the slopes process, which will calculate the slopes based
        # on the camera data.
        self.status_loop_signal.emit("Initializing")
        self.log_signal.emit("Starting slopes process...", "blue")
        ics.launch("SlopesProcess")
        ics.run("slopes", "start")

        # AO loop process comes at the end since it needs the shared memories of
        # the other components.
        self.log_signal.emit("Starting loop process...", "blue")
        ics.launch("Loop")
        ics.run("loop", "setGain", 0)  # Always start with loop open
        ics.run("loop", "start")

        # Also plug in the telemetry stream
        ics.launch("ImakaTelemetry")
        ics.run("tel", "start")

        self.status_loop_signal.emit("Running")
        self.done.emit(self.name)

class ICSStatusWorker(QThread):
    # Updates the status panel routinely
    status_cam_signal = pyqtSignal(str)
    status_ASM_signal = pyqtSignal(str)
    status_loop_signal = pyqtSignal(str)
    status_ICS_signal =  pyqtSignal(str)

    def __init__(self, poll_interval=2):
        super().__init__()
        self.poll_interval = poll_interval
        self.running = True

    def run(self):
        ics = get_ics_proxy()  # New proxy has to go in the run thread, not main
        while self.running:
            # Camera status
            if ics.is_connected("wfs"):
                self.status_cam_signal.emit("Connected")
            else:
                self.status_cam_signal.emit("Disconnected")

            # ASM status
            if ics.is_connected("wfc"):
                self.status_ASM_signal.emit("Connected")
            else:
                self.status_ASM_signal.emit("Disconnected")

            # Loop status
            if ics.is_connected("loop"):
                loop_running = ics.run("loop", "isRunning")
                if loop_running:
                    self.status_loop_signal.emit("Running")
                else:
                    self.status_loop_signal.emit("Paused")
            else:
                self.status_loop_signal.emit("Disconnected")

            # ICS status
            self.status_ICS_signal.emit("Connected")

            time.sleep(self.poll_interval)

class PyroWorker(QThread):
    # Used to call the ICS. Avoids uninterruptible threads that require a system
    # reboot to eliminate.
    result_ready = pyqtSignal(object)
    error_occurred = pyqtSignal(str)

    def __init__(self, fn):
        super().__init__()
        self.fn = fn

    def run(self):
        try:
            self.result_ready.emit(self.fn(get_ics_proxy()))
        except Exception as e:
            self.error_occurred.emit(str(e))

class AsyncICSProxy:
    # This exists to be used as a slot-in replacement of the normal ICS proxy.
    def __init__(self, window):
        self._window = window

    def __getattr__(self, name):
        def call(*args, callback=None, error_callback=None):
            self._window.call_ics(
                lambda p: getattr(p, name)(*args),
                callback=callback,
                error_callback=error_callback
            )
        return call