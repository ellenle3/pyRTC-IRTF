import sys
import numpy as np
import os
import signal
from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget, QPushButton
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from matplotlib.colors import LogNorm
from astropy.io import fits
from pyRTC.Pipeline import ImageSHM
from pyRTC.utils import *

# Import the helper
from shm_manager import SHMConnectionManager

class IRTFASM1RealTimeView(QMainWindow):
    def __init__(self, shm_name, fps, F, static_vmin=None, static_vmax=None):
        super().__init__()

        self.F = F  
        self.fps = fps
        self.shm_name = shm_name
        self.old_time = 0
        self.static_vmin = static_vmin
        self.static_vmax = static_vmax
        self.vmax_surf = static_vmax
        self.vmin_surf = static_vmin
        self.vmin_c = -0.3
        self.vmax_c = 0.3
        self.log = False

        # Read meta layout size once safely on initialization block
        init_meta = ImageSHM(shm_name + "_meta", (ImageSHM.METADATA_SIZE,), np.float64)
        metadata = init_meta.read_noblock()
        shm_width, shm_height = int(metadata[4]), int(metadata[5])
        shm_dtype = float_to_dtype(metadata[3])
        init_meta.close()

        if shm_width != 6 and shm_height != 6:
            raise ValueError(f"Expected ASM commands (6, 6), got ({shm_width}, {shm_height})")

        # Initialize Connection Manager Helper
        self.mgr = SHMConnectionManager(
            main_name=shm_name,
            meta_name=shm_name + "_meta",
            shape=(shm_width, shm_height),
            dtype=shm_dtype
        )

        self.setWindowTitle(f'{shm_name} - PyRTC ASM Viewer')
        self.setGeometry(100, 100, 1200, 600)

        central_widget = QWidget(self)
        self.setCentralWidget(central_widget)

        self.figure = Figure(figsize=(10, 5), tight_layout=True)
        self.ax_cmds = self.figure.add_subplot(121)  
        self.ax_surf = self.figure.add_subplot(122)  

        c0 = np.zeros(36)
        surf0 = np.dot(self.F, c0)

        # Plot positions
        x, y = np.empty(36), np.empty(36)
        ring_idx, radius = [6, 18, 36], [1, 2, 3]
        theta_offset = [2*np.pi/3, 2*np.pi/3 - 0.6, 2*np.pi/3 - 0.8]
        j1 = 0
        for i in range(3):
            j2, r = ring_idx[i], radius[i]
            thetas = np.arange(0, 2*np.pi, 2*np.pi/(j2-j1)) + theta_offset[i]
            x[j1:j2], y[j1:j2] = r * np.cos(thetas), r * np.sin(thetas)
            j1 = j2

        self.cmd_scatter = self.ax_cmds.scatter(x, y, c=c0, s=500, cmap='seismic')
        
        self.value_texts = []
        self.id_texts = []
        for i, z1 in enumerate(c0):
            txt = self.ax_cmds.annotate(f'{z1:.3f}', (x[i]+0.15, y[i]+0.15))
            self.value_texts.append(txt)
            offset = -0.18 if i > 9 else -0.12
            idtxt = self.ax_cmds.annotate('a' + str(i), (x[i]+offset, y[i]-0.08), c='white')
            self.id_texts.append(idtxt)

        self.ax_cmds.set_xlim(-3.8, 3.8)
        self.ax_cmds.set_ylim(-3.6, 3.6)
        self.ax_cmds.set_title("Normalized actuator commands", fontsize=12)
        self.cbar_cmds = self.figure.colorbar(self.cmd_scatter, ax=self.ax_cmds)

        self.im = self.ax_surf.imshow(surf0, cmap="inferno", origin="upper")
        self.ax_surf.set_title("Surface (RMS microns)", fontsize=12)
        
        # TransAxes keeps text centered and static even if graph changes size
        self.fpsText = self.ax_surf.text(0.5, 1.02, "WAITING FOR SHM...",
                                         fontsize=12, ha="center", va="bottom",
                                         color="r", transform=self.ax_surf.transAxes)
        self.LinearNorm = self.im.norm
        self.cbar = self.figure.colorbar(self.im, ax=self.ax_surf)

        self.logButton = QPushButton("Toggle Log Colorbar")
        self.logButton.clicked.connect(self.toggleLog)

        self.canvas = FigureCanvas(self.figure)
        layout = QVBoxLayout(central_widget)
        layout.addWidget(self.canvas)
        layout.addWidget(self.logButton)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_view)
        self.timer.start(1000 // fps)

    def update_view(self):
        if not self.mgr.connected:
            if not self.mgr.try_connect():
                elapsed = self.mgr.get_pause_duration()
                self.fpsText.set_text(f"WAITING FOR SHM...\n({elapsed}s)")
                self.fpsText.set_color('r')
                self.canvas.draw()
                self.timer.setInterval(200) # Check fast in background
                return
            else:
                self.timer.setInterval(1000 // self.fps)

        try:
            c = self.mgr.shm.read_noblock()
            metadata = self.mgr.metadata.read_noblock()
            if c is None or metadata is None: raise ValueError()
            c = c.flatten()
        except Exception:
            self.mgr.disconnect()
            self.timer.setInterval(200)
            return

        new_count, new_time = metadata[0], metadata[1]
        is_active = self.mgr.check_heartbeat(new_count)

        if is_active:
            if new_time > self.old_time:
                speed_fps = np.round((new_count - self.mgr.old_count) / (new_time - self.old_time), 2)
                status_text = f"{speed_fps} FPS"
            else:
                status_text = "CONNECTED"
            self.fpsText.set_color('g')
            
            # Process Active Matrix Data
            surf = np.dot(self.F, c)
            self.vmin_c, self.vmax_c = self.getVminVmax(c)
            self.cmd_scatter.set_clim(self.vmin_c, self.vmax_c)
            self.cmd_scatter.set_array(c)

            for i, txt in enumerate(self.value_texts):
                txt.set_text(f'{c[i]:.3f}')

            self.vmin_surf, self.vmax_surf = self.getVminVmax(surf)
            self.im.set_data(surf)
            self.im.set_clim(self.vmin_surf, self.vmax_surf)     
            self.cbar.update_normal(self.im)
        else:
            elapsed = self.mgr.get_pause_duration()
            status_text = f"PAUSED\nSHM paused for {elapsed} seconds..."
            self.fpsText.set_color('r')

        self.fpsText.set_text(status_text)
        self.old_time = new_time
        self.canvas.draw()

    def getVminVmax(self, frame):
        vmin, vmax = np.nanmin(frame), np.nanmax(frame)
        if self.log:
            vmin, vmax = max(vmin, vmax / 1e3), max(1e-2, vmax)
        return vmin, vmax

    def toggleLog(self):
        self.log = not self.log
        if self.log:
            self.im.set_norm(LogNorm(vmin=1e-2, vmax=1))
        else:
            self.im.set_norm(self.LinearNorm)
        self.canvas.draw()

    def closeEvent(self, event):
        self.mgr.disconnect()
        event.accept()

if __name__ == "__main__":
    # Fix: Catch Ctrl+C interruptions in shell terminal window
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    
    pid = os.getpid()
    set_affinity(0)

    app = QApplication(sys.argv)
    static_vmin = float(sys.argv[1]) if len(sys.argv) > 1 else None
    static_vmax = float(sys.argv[2]) if len(sys.argv) > 2 else None

    script_dir = os.path.dirname(os.path.abspath(__file__))
    F = fits.getdata(os.path.join(script_dir, "irtf-1_infl_func_20250404b.fits"))

    view = IRTFASM1RealTimeView("wfc2D", fps=30, F=F,
                                static_vmin=static_vmin,
                                static_vmax=static_vmax)
    view.show()
    sys.exit(app.exec_())