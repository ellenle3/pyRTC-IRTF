import sys
import numpy as np
import os
from multiprocessing import shared_memory
from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget, QPushButton
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from matplotlib.colors import LogNorm
from astropy.io import fits
from pyRTC.Pipeline import ImageSHM
from pyRTC.utils import *


class IRTFASM1RealTimeView(QMainWindow):
    def __init__(self, shm_name, fps, F, static_vmin=None, static_vmax=None):
        super().__init__()

        self.F = F  # influence functions, shape (dx, dy, 36)

        self.old_count = 0
        self.old_time = 0
        self.static_vmin = static_vmin
        self.static_vmax = static_vmax
        self.vmax_surf = static_vmax
        self.vmin_surf = static_vmin
        self.vmin_c = -0.3
        self.vmax_c = 0.3
        self.log = False

        # Read metadata for ASM commands
        self.metadata = ImageSHM(shm_name + "_meta", (ImageSHM.METADATA_SIZE,), np.float64)
        metadata = self.metadata.read_noblock()
        shm_width, shm_height = int(metadata[4]), int(metadata[5])
        if shm_width != 6 and shm_height != 6:
            raise ValueError(f"Expected ASM commands to be (6, 6), but got ({shm_width}, {shm_height})")

        shm_height = max(1, shm_height)
        shm_width = max(1, shm_width)

        shm_dtype = float_to_dtype(metadata[3])
        self.shm = ImageSHM(shm_name, (shm_width, shm_height), shm_dtype)

        self.setWindowTitle(f'{shm_name} - PyRTC ASM Viewer')
        self.setGeometry(100, 100, 1200, 600)

        central_widget = QWidget(self)
        self.setCentralWidget(central_widget)

        # Create Matplotlib Figure and two Axes
        self.figure = Figure(figsize=(10, 5), tight_layout=True)
        self.ax_cmds = self.figure.add_subplot(121)  # left - actuator commands
        self.ax_surf = self.figure.add_subplot(122)  # right - surface

        # Initial data
        c0 = self.shm.read_noblock()
        c0 = c0.flatten() if c0 is not None else None
        if c0 is None:
            c0 = np.zeros(36)
        surf0 = np.dot(self.F, c0)

        # Plot actuator commands (scatter)
        x = np.empty(36)
        y = np.empty(36)
        ring_idx = [6, 18, 36]
        radius = [1, 2, 3]
        theta_offset = [2*np.pi/3, 2*np.pi/3 - 0.6, 2*np.pi/3 - 0.8]
        j1 = 0
        # Find the (x, y) coordinates for each point on the scatter plot that will
        # represent an actuator
        for i in range(3):
            j2 = ring_idx[i]
            r = radius[i]
            thetas = np.arange(0, 2*np.pi, 2*np.pi/(j2-j1))
            thetas += theta_offset[i]
            x[j1:j2] = r * np.cos(thetas)
            y[j1:j2] = r * np.sin(thetas)
            j1 = j2
        self.cmd_scatter = self.ax_cmds.scatter(x, y, c=c0, s=500, cmap='seismic')
        # In __init__(), after creating scatter:
        self.value_texts = []  # store numeric labels
        self.id_texts = []     # store actuator IDs
        for i, z1 in enumerate(c0):
            txt = self.ax_cmds.annotate(f'{z1:.3f}', (x[i]+0.15, y[i]+0.15))
            self.value_texts.append(txt)
            if i > 9:
                idtxt = self.ax_cmds.annotate('a' + str(i), (x[i]-0.18, y[i]-0.08), c='white')
            else:
                idtxt = self.ax_cmds.annotate('a' + str(i), (x[i]-0.12, y[i]-0.08), c='white')
        self.id_texts.append(idtxt)

        self.ax_cmds.set_xlim(-3.8, 3.8)
        self.ax_cmds.set_ylim(-3.6, 3.6)
        self.ax_cmds.set_title("Normalized actuator commands", fontsize=12)
        self.cbar_cmds = self.figure.colorbar(self.cmd_scatter, ax=self.ax_cmds)

        # Plot surface
        self.im = self.ax_surf.imshow(surf0, cmap="inferno", origin="upper")
        self.ax_surf.set_title("Surface (RMS microns)", fontsize=12)
        self.fpsText = self.ax_surf.text(
            surf0.shape[1] // 2,
            int(1.15 * surf0.shape[0]),
            "PAUSED",
            fontsize=12,
            ha="center",
            va="bottom",
            color="g",
        )
        self.LinearNorm = self.im.norm
        self.cbar = self.figure.colorbar(self.im, ax=self.ax_surf)

        # Log button
        self.logButton = QPushButton("Toggle Log Colorbar")
        self.logButton.clicked.connect(self.toggleLog)

        # Canvas
        self.canvas = FigureCanvas(self.figure)
        layout = QVBoxLayout(central_widget)
        layout.addWidget(self.canvas)
        layout.addWidget(self.logButton)

        # Start updates
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_view)
        self.timer.start(1000 // fps)

    def update_view(self):
        c = self.shm.read_noblock()
        c = c.flatten() if c is not None else None
        if c is None:
            return

        metadata = self.metadata.read_noblock()
        new_count = metadata[0]
        new_time = metadata[1]
        if new_time > self.old_time:
            speed_fps = np.round((new_count - self.old_count) / (new_time - self.old_time), 2)
            speed_fps = str(speed_fps) + " FPS"
        else:
            speed_fps = "PAUSED"

        self.old_count = new_count
        self.old_time = new_time

        # Compute surface from actuator commands
        surf = np.dot(self.F, c)

        # Update scatter colors
        self.vmin_c, self.vmax_c = self.getVminVmax(c)
        self.cmd_scatter.set_clim(self.vmin_c, self.vmax_c)
        self.cmd_scatter.set_array(c)

        # Update numeric labels
        for i, txt in enumerate(self.value_texts):
            txt.set_text(f'{c[i]:.3f}')

        # Update surface
        self.vmin_surf, self.vmax_surf = self.getVminVmax(surf)
        self.im.set_data(surf)
        self.im.set_clim(self.vmin_surf, self.vmax_surf)     
        self.fpsText.set_text(speed_fps)
        self.cbar.update_normal(self.im)

        self.canvas.draw()

    def getVminVmax(self, frame):
        vmin, vmax = np.nanmin(frame), np.nanmax(frame)
        if self.log:
            vmin, vmax = max(vmin, vmax / 1e3), max(1e-2, vmax)
        # if self.static_vmax is not None:
        #     vmax = self.static_vmax
        # if self.static_vmin is not None:
        #     vmin = self.static_vmin

        return vmin, vmax

    def toggleLog(self):
        self.log = not self.log
        if self.log:
            self.im.set_norm(LogNorm(vmin=1e-2, vmax=1))
        else:
            self.im.set_norm(self.LinearNorm)

    def closeEvent(self, event):
        self.shm.close()
        event.accept()


if __name__ == "__main__":
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