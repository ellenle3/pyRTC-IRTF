import sys
import numpy as np
from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget, QPushButton
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from pyRTC.Pipeline import ImageSHM
from pyRTC.utils import *
import matplotlib.pyplot as plt
from matplotlib.colors import LogNorm
import matplotlib.patheffects as path_effects
import matplotlib.cm as cm

def read_shared_memory(shm_arr):
    return np.copy(shm_arr)

class RealTimeSubApsView(QMainWindow):
    def __init__(self, fps, static_vmin=None, static_vmax=None):
        super().__init__()

        self.old_count = 0
        self.old_time = 0
        self.static_vmin = static_vmin
        self.static_vmax = static_vmax
        self.vmax = static_vmax
        self.vmin = static_vmin
        self.log = False

        shm_name = "wfs"
        self.metadata = ImageSHM(shm_name+"_meta", (ImageSHM.METADATA_SIZE,), np.float64)
        metadata = self.metadata.read_noblock()
        shm_width, shm_height = int(metadata[4]), int(metadata[5])

        shm_height = max(1, shm_height)
        shm_width = max(1, shm_width)

        shm_dtype = float_to_dtype(metadata[3])
        self.shm = ImageSHM(shm_name, (shm_width, shm_height), shm_dtype)

        # Subaperture masks from shared memory
        self.masks = ImageSHM("subApMasks", (4, shm_width, shm_height), '>i8')

        self.setWindowTitle(f'{shm_name} - PyRTC WFS Viewer')
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
        self.im = self.axes.imshow(frame, cmap='gray', interpolation='nearest',
                                   aspect=aspect, origin='upper',
                                   vmin=self.vmin, vmax=self.vmax)

        self.fpsText = self.axes.text(frame.shape[1]//2, int(1.15*frame.shape[0]),
                                      'PAUSED', fontsize=18,
                                      ha='center', va='bottom', color='g')

        self.LinearNorm = self.im.norm
        self.cbar = self.figure.colorbar(self.im, ax=self.axes)

        self.logButton = QPushButton('Toggle Log Colorbar')
        self.logButton.clicked.connect(self.toggleLog)

        # Matplotlib canvas
        self.canvas = FigureCanvas(self.figure)
        central_layout = QVBoxLayout(central_widget)
        central_layout.addWidget(self.canvas)
        central_layout.addWidget(self.logButton)

        # Keep references to overlays so we can remove/update
        self.mask_overlays = []

        self.update_view()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_view)
        self.timer.start(1000 // fps)

    import matplotlib.patheffects as path_effects

    def update_view(self):
        frame = self.shm.read_noblock()
        metadata = self.metadata.read_noblock()
        new_count = metadata[0]
        new_time = metadata[1]
        if new_time > self.old_time:
            speed_fps = np.round((new_count - self.old_count) / (new_time - self.old_time), 2)
            speed_fps = str(speed_fps) + "FPS"
        else:
            speed_fps = 'PAUSED'

        self.old_count = new_count
        self.old_time = new_time

        if isinstance(frame, np.ndarray):
            self.updateVminVmax(frame)
            self.fpsText.set_text(str(speed_fps))
            self.im.set_data(frame)
            self.im.set_clim(self.vmin, self.vmax)
            self.cbar.update_normal(self.im)

            # remove old overlays
            for coll in list(self.axes.collections):
                coll.remove()
            for txt in getattr(self, "_mask_labels", []):
                txt.remove()
            self._mask_labels = []

            try:
                masks = self.masks.read_noblock()
                cmap = cm.get_cmap('tab10', masks.shape[0])  # distinct colors

                for i in range(masks.shape[0]):
                    mask = masks[i]
                    if np.any(mask):
                        # colored transparent overlay
                        self.axes.contourf(
                            mask, levels=[0.5, 1],
                            colors=[cmap(i)],
                            alpha=0.3
                        )
                        # contour outline
                        self.axes.contour(
                            mask, levels=[0.5],
                            colors=[cmap(i)], linewidths=0.8
                        )
                        # label
                        y, x = np.nonzero(mask)
                        cx, cy = np.mean(x), np.mean(y)
                        txt = self.axes.text(
                            cx, cy - 5, str(i + 1),
                            color='white', fontsize=10, weight='bold',
                            ha='center', va='bottom',
                            path_effects=[path_effects.Stroke(linewidth=2, foreground='black'),
                                          path_effects.Normal()]
                        )
                        self._mask_labels.append(txt)

            except Exception:
                pass  # no masks available yet

            self.canvas.draw()

    def updateVminVmax(self, frame):
        vmin, vmax = np.min(frame), np.max(frame)
        if self.log:
            vmin, vmax = max(vmin, vmax / 1e3), max(1e-2, vmax)
        self.vmin, self.vmax = vmin, vmax
        if self.static_vmax is not None:
            self.vmax = self.static_vmax
        if self.static_vmin is not None:
            self.vmin = self.static_vmin

    def toggleLog(self):
        self.log = not self.log
        if self.log:
            self.im.set_norm(LogNorm(vmin=1e-2, vmax=1))
        else:
            self.im.set_norm(self.LinearNorm)
        return

    def closeEvent(self, event):
        self.shm.close()
        self.masks.close()
        event.accept()

if __name__ == '__main__':
    pid = os.getpid()
    set_affinity(0)

    app = QApplication(sys.argv)
    static_vmin = None
    static_vmax = None

    if len(sys.argv) > 1:
        static_vmin = sys.argv[1]
    if len(sys.argv) > 2:
        static_vmax = sys.argv[2]

    view = RealTimeSubApsView(30,
                           static_vmin=static_vmin,
                           static_vmax=static_vmax)

    view.show()
    sys.exit(app.exec_())