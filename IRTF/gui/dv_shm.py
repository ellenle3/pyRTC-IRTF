import sys
import time
import signal  # Added to catch system exit interrupts
import numpy as np
from multiprocessing import shared_memory
from multiprocessing.shared_memory import SharedMemory
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget, QPushButton
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from pyRTC.Pipeline import ImageSHM
from pyRTC.utils import *
import matplotlib.colors as mcolors
from matplotlib.colors import LogNorm, Normalize
import matplotlib
import os

def read_shared_memory(shm_arr):
    return np.copy(shm_arr)

class RealTimeView(QMainWindow):
    def __init__(self, shm_name, fps, static_vmin=None, static_vmax=None):
        super().__init__()

        self.shm_name = shm_name
        self.fps = fps
        self.old_count = 0
        self.old_time = 0
        self.static_vmin = static_vmin
        self.static_vmax = static_vmax
        self.vmax = static_vmax
        self.vmin = static_vmin
        self.log = False

        # State management
        self.shm_connected = False
        self.shm = None
        self.metadata = None
        
        # Heartbeat & Pause Tracking
        self.last_heartbeat_time = time.time()
        self.timeout_seconds = 2.5 
        self.pause_start_time = None  # Tracks how long we have been frozen

        self.setWindowTitle(f'{shm_name} - PyRTC Viewer')
        self.setGeometry(100, 100, 800, 600)

        central_widget = QWidget(self)
        self.setCentralWidget(central_widget)

        # Create Matplotlib Figure and Axes
        self.figure = Figure(figsize=(8, 8), tight_layout=True)
        self.axes = self.figure.add_subplot(111)
        self.axes.axis('off') 
        
        # Normalized coordinates (0.5, 0.5) keeps text perfectly centered on launch
        self.fpsText = self.axes.text(0.5, 0.5, 'WAITING FOR SHM...', 
                                      fontsize=14, ha='center', va='center', 
                                      color='r', transform=self.axes.transAxes)

        self.im = None
        self.cbar = None

        self.logButton = QPushButton('Toggle Log Colorbar')
        self.logButton.clicked.connect(self.toggleLog)

        # Create Matplotlib canvas
        self.canvas = FigureCanvas(self.figure)
        central_layout = QVBoxLayout(central_widget)
        central_layout.addWidget(self.canvas)
        central_layout.addWidget(self.logButton)

        # Start timer loop at 1-second intervals initially
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_loop)
        self.timer.start(1000)

    def try_connect(self):
        """Attempts to look for and bind to system SHM files."""
        try:
            try:
                meta_check = SharedMemory(name=self.shm_name + "_meta")
                meta_check.close()
                main_check = SharedMemory(name=self.shm_name)
                main_check.close()
            except FileNotFoundError:
                return False 

            self.metadata = ImageSHM(self.shm_name+"_meta", (ImageSHM.METADATA_SIZE,), np.float64, consumer=True)
            metadata = self.metadata.read_noblock()
            shm_width, shm_height = int(metadata[4]), int(metadata[5])
            
            if shm_width <= 0 or shm_height <= 0:
                self.cleanup_shm()
                return False
            
            shm_dtype = float_to_dtype(metadata[3])
            self.shm = ImageSHM(self.shm_name, (shm_width, shm_height), shm_dtype, consumer=True)
            frame = self.shm.read_noblock()
            
            # Check if dimensions changed to see if we actually need an expensive axis reset
            dimensions_changed = True
            if self.im is not None:
                if hasattr(self.im, 'get_array'):
                    if self.im.get_array().shape == (shm_height, shm_width):
                        dimensions_changed = False

            if dimensions_changed:
                if self.cbar is not None:
                    try: self.cbar.remove()
                    except: pass
                    self.cbar = None

                self.axes.clear()
                self.axes.axis('on')
                
                aspect = None
                ASPECTCAP = 10
                if shm_width/shm_height < 1/ASPECTCAP or shm_width/shm_height > ASPECTCAP:
                    aspect = "auto"

                self.updateVminVmax(frame)
                self.im = self.axes.imshow(frame, cmap='inferno', interpolation='nearest', aspect=aspect,
                                           origin='upper', vmin=self.vmin, vmax=self.vmax)
                
                # Position text layout consistently relative to the graph frame bounds
                self.fpsText = self.axes.text(0.5, 1.02, 'CONNECTED', 
                                              fontsize=13, ha='center', va='bottom', 
                                              color='g', transform=self.axes.transAxes)

                self.LinearNorm = self.im.norm
                self.cbar = self.figure.colorbar(self.im, ax=self.axes)
            else:
                # Retain structural framework; update raw data matrices to eliminate view flickering
                self.updateVminVmax(frame)
                self.im.set_data(frame)
                self.im.set_clim(self.vmin, self.vmax)
                if self.cbar:
                    self.cbar.update_normal(self.im)
                if not self.fpsText or self.fpsText not in self.axes.texts:
                    self.fpsText = self.axes.text(0.5, 1.02, 'CONNECTED', 
                                                  fontsize=13, ha='center', va='bottom', 
                                                  color='g', transform=self.axes.transAxes)

            if self.log:
                self.im.set_norm(LogNorm(vmin=1e-2, vmax=1))
            else:
                self.im.set_norm(self.LinearNorm)

            self.canvas.draw()

            self.old_count = metadata[0]
            self.old_time = metadata[1]
            
            self.last_heartbeat_time = time.time()
            self.shm_connected = True
            return True
            
        except Exception:
            self.cleanup_shm()
            return False

    def cleanup_shm(self):
        if self.metadata:
            try: self.metadata.close()
            except: pass
            self.metadata = None
        if self.shm:
            try: self.shm.close()
            except: pass
            self.shm = None

    def update_loop(self):
        if not self.shm_connected:
            if self.try_connect():
                return
            else:
                # Connection missing or broken entirely. Increment counter on the current view.
                if self.pause_start_time is None:
                    self.pause_start_time = time.time()
                elapsed = int(time.time() - self.pause_start_time)
                
                if self.fpsText:
                    if self.im is None:
                        self.fpsText.set_text(f"WAITING FOR SHM...\n({elapsed}s)")
                    else:
                        self.fpsText.set_text(f"PAUSED\nSHM paused for {elapsed} seconds...")
                    self.fpsText.set_color('r')
                self.canvas.draw()
                return

        # Connected State Handling
        try:
            metadata = self.metadata.read_noblock()
            frame = self.shm.read_noblock()
            if not isinstance(frame, np.ndarray):
                raise ValueError()
        except Exception:
            # Memory space drops out completely underneath the process execution layer
            if self.pause_start_time is None:
                self.pause_start_time = time.time()
            self.shm_connected = False
            self.cleanup_shm()
            
            elapsed = int(time.time() - self.pause_start_time)
            if self.fpsText:
                self.fpsText.set_text(f"PAUSED\nSHM paused for {elapsed} seconds...")
                self.fpsText.set_color('r')
            self.canvas.draw()
            self.timer.setInterval(200)  # check for SHM reconnection more frequently during active pause states
            return

        new_count = metadata[0]
        new_time = metadata[1]

        if new_count != self.old_count:
            # Active Stream processing
            self.pause_start_time = None
            self.last_heartbeat_time = time.time()
            
            if new_time > self.old_time:
                speed_fps = np.round((new_count - self.old_count)/(new_time - self.old_time), 2)
                status_text = f"{speed_fps} FPS"
            else:
                status_text = "CONNECTED"
            
            if self.fpsText:
                self.fpsText.set_text(status_text)
                self.fpsText.set_color('g')
            
            self.updateVminVmax(frame)
            self.im.set_data(frame)
            self.im.set_clim(self.vmin, self.vmax)
            if self.cbar:
                self.cbar.update_normal(self.im)
            self.canvas.draw()
            
            self.timer.setInterval(1000 // self.fps)
        else:
            # Frame counter matches completely (Producer writes are idling)
            if self.pause_start_time is None:
                self.pause_start_time = time.time()
            
            elapsed = int(time.time() - self.pause_start_time)
            if self.fpsText:
                self.fpsText.set_text(f"PAUSED\nSHM paused for {elapsed} seconds...")
                self.fpsText.set_color('r')
            self.canvas.draw()

            # Guard against zombie pointers. Drop file descriptors if frozen past threshold window.
            if time.time() - self.last_heartbeat_time > self.timeout_seconds:
                self.shm_connected = False
                self.cleanup_shm()
                self.timer.setInterval(200)
        
        self.old_count = new_count
        self.old_time = new_time

    def updateVminVmax(self, frame):
        vmin, vmax = np.min(frame), np.max(frame)
        if self.log:
            vmin, vmax = max(vmin, vmax/1e3), max(1e-2, vmax)
        self.vmin, self.vmax = vmin, vmax
        if self.static_vmax is not None:
            self.vmax = self.static_vmax
        if self.static_vmin is not None:
            self.vmin = self.static_vmin

    def toggleLog(self):
        self.log = not self.log
        if self.im:
            if self.log:
                self.im.set_norm(LogNorm(vmin=1e-2, vmax=1))
            else:
                self.im.set_norm(self.LinearNorm)
            self.canvas.draw()

    def closeEvent(self, event):
        self.cleanup_shm()
        event.accept()

if __name__ == '__main__':
    # Fix: Direct system handler override allows Terminal Ctrl+C sequence to end execution instantly
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    
    pid = os.getpid()
    set_affinity(0) 

    app = QApplication(sys.argv)
    if len(sys.argv) < 2:
        print("Usage: python viewer.py <shm_name> [static_vmin] [static_vmax]")
        sys.exit(1)
        
    shm_name = sys.argv[1]
    static_vmin = float(sys.argv[2]) if len(sys.argv) > 2 else None
    static_vmax = float(sys.argv[3]) if len(sys.argv) > 4 else None

    view = RealTimeView(shm_name, 30, 
                        static_vmin=static_vmin,
                        static_vmax=static_vmax)

    view.show()
    sys.exit(app.exec_())