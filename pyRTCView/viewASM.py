import sys
import numpy as np
from multiprocessing import shared_memory
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget, QPushButton
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from pyRTC.Pipeline import ImageSHM
from pyRTC.utils import *
import matplotlib.pyplot as plt
from matplotlib.colors import LogNorm, Normalize
import matplotlib
import os

def read_shared_memory(shm_arr):
    return np.copy(shm_arr)

class RealTimeView(QMainWindow):
    def __init__(self, shm_name, fps, static_vmin=None, static_vmax=None):
        super().__init__()

        self.old_count = 0
        self.old_time = 0
        self.static_vmin = static_vmin
        self.static_vmax = static_vmax
        self.vmax = static_vmax
        self.vmin = static_vmin
        self.log = False

        self.metadata = ImageSHM(shm_name+"_meta", (ImageSHM.METADATA_SIZE,), np.float64)
        metadata = self.metadata.read_noblock()
        shm_width, shm_height = int(metadata[4]),  int(metadata[5])

        shm_height = max(1,shm_height)
        shm_width = max(1,shm_width)

        shm_dtype = float_to_dtype(metadata[3])
        self.shm = ImageSHM(shm_name, (shm_width, shm_height), shm_dtype)
        
        self.setWindowTitle(f'{shm_name} - PyRTC Viewer')
        self.setGeometry(100, 100, 800, 600)

        central_widget = QWidget(self)
        self.setCentralWidget(central_widget)

        # Create Matplotlib Figure and Axes
        self.figure = Figure(figsize=(8, 8), tight_layout=True)
        self.axes = self.figure.add_subplot(111)

        frame = self.shm.read_noblock()

        aspect = None
        ASPECTCAP = 10
        if shm_width/shm_height < 1/ASPECTCAP or shm_width/shm_height > ASPECTCAP:
            aspect = "auto"

        self.updateVminVmax(frame)
        self.im = self.axes.imshow(frame, cmap='inferno', interpolation='nearest', aspect=aspect,
                                origin='upper',vmin = self.vmin, vmax = self.vmax)
        
        self.fpsText = self.axes.text(frame.shape[1]//2,int(1.15*frame.shape[0]), 'PAUSED', fontsize=18, ha='center', va='bottom', color = 'g')

        self.LinearNorm = self.im.norm
        self.cbar = self.figure.colorbar(self.im, ax=self.axes)

        self.logButton = QPushButton('Toggle Log Colorbar')
        self.logButton.clicked.connect(self.toggleLog)

        # plt.colorbar()
        # Create Matplotlib canvas
        self.canvas = FigureCanvas(self.figure)
        central_layout = QVBoxLayout(central_widget)
        central_layout.addWidget(self.canvas)
        central_layout.addWidget(self.logButton)

        self.update_view()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_view)
        self.timer.start(1000 //fps)

    def update_view(self):
        # try:
        frame = self.shm.read_noblock()
        metadata = self.metadata.read_noblock()
        new_count = metadata[0]
        new_time = metadata[1]
        if new_time > self.old_time:
            speed_fps = np.round((new_count - self.old_count)/(new_time- self.old_time),2)
            speed_fps = str(speed_fps) + "FPS"
        else:
            speed_fps = 'PAUSED'

        self.old_count = new_count
        self.old_time = new_time
        if isinstance(frame,np.ndarray):
            self.updateVminVmax(frame)
            
            self.fpsText.set_text(str(speed_fps))
            # print(vmin,vmax)
            self.im.set_data(frame)

            self.im.set_clim(self.vmin, self.vmax)

            self.cbar.update_normal(self.im)  

            self.canvas.draw()

    def updateVminVmax(self, frame):

        vmin, vmax = np.min(frame), np.max(frame)
        if self.log:
            vmin, vmax = max(vmin,vmax/1e3), max(1e-2, vmax)
        self.vmin, self.vmax = vmin, vmax
        if self.static_vmax is not None:
            self.vmax = self.static_vmax
        if self.static_vmin is not None:
            self.vmin = self.static_vmin

    def toggleLog(self):
        self.log = not self.log
        if self.log:
            self.im.set_norm(LogNorm(vmin = 1e-2, vmax =  1))
        else:
            self.im.set_norm(self.LinearNorm)
        return

    def closeEvent(self, event):
        # Code to execute when the window is closed
        self.shm.close()
        event.accept()

if __name__ == '__main__':
    pid = os.getpid()
    set_affinity(0) 

    app = QApplication(sys.argv)
    shm_name = sys.argv[1]
    static_vmin = None
    static_vmax = None

    if len(sys.argv) > 2:
        static_vmin = sys.argv[2]
    if len(sys.argv) > 3:
        static_vmax = sys.argv[3]

    view = RealTimeView(shm_name, 30, 
                        static_vmin = static_vmin,
                        static_vmax = static_vmax)

    view.show()
    sys.exit(app.exec_())



def plot_cmds_irtfasm1(c: NDArray, F: NDArray) -> NDArray:
    """Plots actuator commands and the resulting surface shape for IRTF-ASM-1.

    Parameters
    ----------
    c: nd_array of size 36
        Actuator commands.
    F: nd_array of size (dx, dy, 36)
        Influence functions for the 36 actuators. The dimensions dx, dy corresponds
        to the size of the surface measurement (e.g., dx = dy = 47 for the HASO WFS).

    Returns
    -------
    out: nd_array of size (dx, dy)
        The projected surface shape. Units are the same as the surface measurements
        for the influence functions.
    """
    fig, axs = plt.subplots(nrows=1, ncols=2, figsize=(10,5))
    # Plot actuator commands on a circle
    x = np.empty(36)
    y = np.empty(36)
    z = c.copy()
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
    axs[0].scatter(x, y, c=z, s=500, cmap='seismic')
    # Put text labels for each actuator
    for i, z1 in enumerate(z):
        axs[0].annotate('{:.3f}'.format(z1), (x[i]+0.15, y[i]+0.15))
        if i > 9:
            axs[0].annotate('a' + str(i), (x[i]-0.18, y[i]-0.08), c='white')
        else:
            axs[0].annotate('a' + str(i), (x[i]-0.12, y[i]-0.08), c='white')
    axs[0].set_xlim(-3.8, 3.8)
    axs[0].set_ylim(-3.6, 3.6)
    axs[0].set_title("Normalized actuator commands", fontsize=12)
    plt.colorbar(im)
    plt.tight_layout()
    plt.show()
