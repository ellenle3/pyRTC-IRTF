import sys
import numpy as np
import signal
import os
from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget, QPushButton
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from pyRTC.Pipeline import ImageSHM
from pyRTC.utils import *
import matplotlib.colors as mcolors
from matplotlib.colors import LogNorm
import matplotlib.patheffects as path_effects
import matplotlib.cm as cm

# Import the helper
from shm_manager import SHMConnectionManager

class RealTimeSubApsView(QMainWindow):
    def __init__(self, fps, static_vmin=None, static_vmax=None):
        super().__init__()

        self.fps = fps
        self.old_time = 0
        self.static_vmin = static_vmin
        self.static_vmax = static_vmax
        self.vmax = static_vmax
        self.vmin = static_vmin
        self.log = False
        self._mask_labels = []

        shm_name = "wfs"
        init_meta = ImageSHM(shm_name+"_meta", (ImageSHM.METADATA_SIZE,), np.float64)
        metadata = init_meta.read_noblock()
        shm_width, shm_height = int(metadata[4]), int(metadata[5])
        shm_dtype = float_to_dtype(metadata[3])
        init_meta.close()

        # Dynamic structural managers 
        self.mgr = SHMConnectionManager(
            main_name=shm_name,
            meta_name=shm_name+"_meta",
            shape=(shm_width, shm_height),
            dtype=shm_dtype
        )
        
        # Subaperture configuration tracking array
        self.masks_shm = None

        self.setWindowTitle(f'{shm_name} - PyRTC WFS Viewer')
        self.setGeometry(100, 100, 800, 600)

        central_widget = QWidget(self)
        self.setCentralWidget(central_widget)

        self.figure = Figure(figsize=(8, 8), tight_layout=True)
        self.axes = self.figure.add_subplot(111)

        frame0 = np.zeros((shm_height, shm_width))
        aspect = "auto" if (shm_width/shm_height < 0.1 or shm_width/shm_height > 10) else None

        self.im = self.axes.imshow(frame0, cmap='gray', interpolation='nearest',
                                   aspect=aspect, origin='upper',
                                   vmin=self.static_vmin or 0, vmax=self.static_vmax or 1)

        self.fpsText = self.axes.text(0.5, 1.02, 'WAITING FOR SHM...', fontsize=14,
                                      ha='center', va='bottom', color='r', 
                                      transform=self.axes.transAxes)

        self.LinearNorm = self.im.norm
        self.cbar = self.figure.colorbar(self.im, ax=self.axes)

        self.logButton = QPushButton('Toggle Log Colorbar')
        self.logButton.clicked.connect(self.toggleLog)

        self.canvas = FigureCanvas(self.figure)
        central_layout = QVBoxLayout(central_widget)
        central_layout.addWidget(self.canvas)
        central_layout.addWidget(self.logButton)

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
                self.timer.setInterval(200)
                return
            else:
                # Connected: Rebuild standalone mask pointers
                try:
                    self.masks_shm = ImageSHM("subApMasks", (4, self.mgr.shape[0], self.mgr.shape[1]), '>i8')
                except:
                    self.masks_shm = None
                self.timer.setInterval(1000 // self.fps)

        try:
            frame = self.mgr.shm.read_noblock()
            metadata = self.mgr.metadata.read_noblock()
            if frame is None or metadata is None: raise ValueError()
        except Exception:
            self.mgr.disconnect()
            if self.masks_shm:
                try: self.masks_shm.close()
                except: pass
                self.masks_shm = None
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

            self.updateVminVmax(frame)
            self.im.set_data(frame)
            self.im.set_clim(self.vmin, self.vmax)
            self.cbar.update_normal(self.im)

            # Re-draw layout overlays dynamically
            for coll in list(self.axes.collections):
                coll.remove()
            for txt in self._mask_labels:
                txt.remove()
            self._mask_labels = []

            if self.masks_shm:
                try:
                    masks = self.masks_shm.read_noblock()
                    cmap = cm.get_cmap('tab10', masks.shape[0])
                    for i in range(masks.shape[0]):
                        mask = masks[i]
                        if np.any(mask):
                            self.axes.contourf(mask, levels=[0.5, 1], colors=[cmap(i)], alpha=0.3)
                            self.axes.contour(mask, levels=[0.5], colors=[cmap(i)], linewidths=0.8)
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
                    pass
        else:
            elapsed = self.mgr.get_pause_duration()
            status_text = f"PAUSED\nSHM paused for {elapsed} seconds..."
            self.fpsText.set_color('r')

        self.fpsText.set_text(status_text)
        self.old_time = new_time
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
        self.canvas.draw()

    def closeEvent(self, event):
        self.mgr.disconnect()
        if self.masks_shm:
            try: self.masks_shm.close()
            except: pass
        event.accept()

if __name__ == '__main__':
    # Fix: Catch Ctrl+C system kills inside standard terminal loops
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    
    pid = os.getpid()
    set_affinity(0)

    app = QApplication(sys.argv)
    static_vmin = None
    static_vmax = None

    if len(sys.argv) > 1:
        static_vmin = float(sys.argv[1])
    if len(sys.argv) > 2:
        static_vmax = float(sys.argv[2])

    view = RealTimeSubApsView(30,
                           static_vmin=static_vmin,
                           static_vmax=static_vmax)

    view.show()
    sys.exit(app.exec_())