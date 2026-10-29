import numpy as np
from multiprocessing.shared_memory import SharedMemory
from PyQt6.QtWidgets import QWidget, QVBoxLayout
from PyQt6.QtCore import pyqtSignal, QTimer, QSize
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qtagg import NavigationToolbar2QT as NavigationToolbar
from matplotlib.figure import Figure
import matplotlib.cm as cm
import matplotlib.patheffects as path_effects
import matplotlib.patches as patches

from pyRTC.Pipeline import ImageSHM
from pyRTC.utils import float_to_dtype
from pyRTC import clear_shms
from workers import *

FLIP = True

class MplFelixImage(QWidget):
    coords_clicked = pyqtSignal(float, float)

    def __init__(self, parent=None, fps=30, static_vmin=None, static_vmax=None):
        super().__init__(parent)

        self.fps = fps
        self.static_vmin = static_vmin
        self.static_vmax = static_vmax
        self.vmax = static_vmax
        self.vmin = static_vmin
        
        self.shm_name = "wfs"
        self.shm_connected = False
        
        # State variables for objects created after connection
        self.metadata = None
        self.shm = None
        self.masks = None
        self.im = None
        self.shm_width = 1
        self.shm_height = 1

        # Create Matplotlib Figure (Starts empty)
        self.figure = Figure()
        self.axes = self.figure.add_axes([0, 0, 1, 1])
        self.axes.axis('off')
        
        self.stale_outline = patches.Rectangle(
            (0, 0), 1, 1, transform=self.axes.transAxes, 
            facecolor='none', edgecolor='darkred', linewidth=4, zorder=100, visible=False
        )
        self.axes.add_patch(self.stale_outline)

        self.stale_text = self.axes.text(
            0.02, 0.98, "STALE", color='white', fontsize=14,
            transform=self.axes.transAxes, ha='left', va='top', zorder=101, visible=False,
            path_effects=[path_effects.withStroke(linewidth=3, foreground='black')]
        )

        # Matplotlib canvas and UI layout
        self.canvas = FigureCanvas(self.figure)
        self.toolbar = NavigationToolbar(self.canvas, self)
        self.toolbar.setIconSize(QSize(20, 20))
        self.toolbar.setStyleSheet("""
            QToolButton {
                background-color: transparent;
                border: 1px solid transparent;
                border-radius: 4px;
                padding: 3px;
                margin: 1px;
            }
            QToolButton:hover {
                 background-color: #788b9e;
                 border: 1px solid #c0c0c0; 
            }
            QToolButton:checked {
                background-color: #b3d7ff;
                border: 1px solid #0055ff; 
            }
            QToolButton:pressed {
                background-color: #80bfff; 
                border: 1px solid #1c4577;
            }
        """)

        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.canvas)
        layout.addWidget(self.toolbar)  # Places the toolbar at the bottom
        self.setLayout(layout)

        self._mask_labels = []
        self.last_clicked_coords = None
        self.canvas.mpl_connect('button_press_event', self.on_click)

        # Poll WFS to see if it is connected
        # If not, then show STALE indicators. Show on startup.
        self.pyro_worker_ics = PyroQueueWorker(proxy_type="ics")
        self.pyro_worker_ics.start()
        self.ics = AsyncICSProxy(self)
        self.stale_outline.set_visible(True)
        self.stale_text.set_visible(True)
        self.canvas.draw_idle()

        # 1. Timer to check for main SHM existence (once per second)
        self.init_timer = QTimer(self)
        self.init_timer.timeout.connect(self.check_and_init_shm)
        self.init_timer.start(1000)

        # 2. Timer for actual frame updates (started after connection)
        self.update_timer = QTimer(self)
        self.update_timer.timeout.connect(self.update_view)
        
        # 3. Timer to check the stale condition
        self.condition_timer = QTimer(self)
        self.condition_timer.timeout.connect(self.evaluate_stale_condition)
        self.condition_timer.start(1000)


    def call_ics(self, fn, callback=None, error_callback=None):
        """Funnel all macro requests straight into the secure background thread queue."""
        return self.pyro_worker_ics.submit_blocking_task(fn)

    def reset_widget_and_clear_shm(self):
        """Resets the widget to startup state and clears the underlying shared memory."""
        # 1. Halt the view timers so they don't try to read while we destroy
        self.update_timer.stop()
        self.init_timer.stop()

        # 2. Close local Python handles safely
        if self.shm:
            self.shm.close()
            self.shm = None
        if self.metadata:
            self.metadata.close()
            self.metadata = None
        if self.masks:
            self.masks.close()
            self.masks = None
            
        self.shm_connected = False

        # 3. Clear shared memories before starting timer
        shm_names = ["wfs", "wfsRaw", "wfc", "wfc2D", "wfcShape", "signal",
                     "signal2D", "psfShort", "psfLong", "wfsInfo", "loop",
                     "refSlopes", "subApMasks", "cmat", "m2c",
                     "simInjectedSlopes"]
        clear_shms(shm_names)

        # 4. Clean up the plot without destroying the axes or STALE patches
        if self.im is not None:
            self.im.remove()
            self.im = None
            
        for coll in list(self.axes.collections):
            coll.remove()
        for txt in self._mask_labels:
            txt.remove()
        self._mask_labels = []
        
        # 5. Force the STALE display to trigger immediately 
        self.stale_outline.set_visible(True)
        self.stale_text.set_visible(True)
        self.canvas.draw_idle()

        # probe for shared memory existence
        self.init_timer.start(1000)

    def evaluate_stale_condition(self):
        """Checks the condition and toggles the STALE indicators visibility."""
        is_stale = not self.ics.is_connected(self.shm_name)
        
        if self.stale_outline.get_visible() != is_stale:
            self.stale_outline.set_visible(is_stale)
            self.stale_text.set_visible(is_stale)
            self.canvas.draw_idle()

    def check_and_init_shm(self):
        """Probes the OS to see if the main shared memory exists before wrapping it."""
        try:
            m_check = SharedMemory(name=f"{self.shm_name}_meta")
            m_check.close()
            d_check = SharedMemory(name=self.shm_name)
            d_check.close()
        except FileNotFoundError:
            return
        except Exception:
            return

        # --- Main SHM exists! Initialize it ---
        self.init_timer.stop()

        self.metadata = ImageSHM(self.shm_name+"_meta", (ImageSHM.METADATA_SIZE,), np.float64, consumer=True)
        metadata = self.metadata.read_noblock()
        
        self.shm_width = max(1, int(metadata[4]))
        self.shm_height = max(1, int(metadata[5]))
        shm_dtype = float_to_dtype(metadata[3])

        self.shm = ImageSHM(self.shm_name, (self.shm_width, self.shm_height), shm_dtype, consumer=True)
        
        # Try to connect to masks immediately if they exist
        self.try_connect_masks()

        # Initial frame grab to setup the matplotlib imshow object
        frame = self.shm.read_noblock()
        if FLIP:
            frame = np.rot90(frame, k=1)
        frame -= np.nanmin(frame)

        aspect = None
        ASPECTCAP = 10
        if self.shm_width/self.shm_height < 1/ASPECTCAP or self.shm_width/self.shm_height > ASPECTCAP:
            aspect = "auto"

        self.updateVminVmax(frame)
        self.im = self.axes.imshow(frame, cmap='gray', interpolation='nearest',
                                   aspect=aspect, origin='upper',
                                   vmin=self.vmin, vmax=self.vmax)

        self.shm_connected = True
        self.canvas.draw_idle()

        # Start the continuous update loop
        self.update_timer.start(1000 // self.fps)

    def try_connect_masks(self):
        """Safely checks the OS for subApMasks memory and connects if it exists."""
        if self.masks is not None:
            return True # Already connected
            
        try:
            mask_check = SharedMemory(name="subApMasks")
            mask_check.close()
            self.masks = ImageSHM("subApMasks", (4, self.shm_width, self.shm_height), '>i8', consumer=True)
            return True
        except FileNotFoundError:
            return False
        except Exception:
            return False

    def update_view(self):
        if not self.shm_connected:
            return

        frame = self.shm.read_noblock()
        if FLIP:
            frame = np.rot90(frame, k=1)
        frame -= np.nanmin(frame)

        if isinstance(frame, np.ndarray):
            self.updateVminVmax(frame)
            self.im.set_data(frame)
            self.im.set_clim(self.vmin, self.vmax)

            # Remove old overlays (this deletes contour collections but leaves patches and text alone)
            for coll in list(self.axes.collections):
                coll.remove()
            for txt in self._mask_labels:
                txt.remove()
            self._mask_labels = []

            # Try to connect to masks if we haven't successfully done so yet
            self.try_connect_masks()

            # Apply masks if connected
            if self.masks is not None:
                try:
                    masks = self.masks.read_noblock()  
                    if FLIP:         
                        for i in range(masks.shape[0]):
                            masks[i] = np.rot90(masks[i], k=1)     
                    cmap = cm.get_cmap('tab10', masks.shape[0])

                    for i in range(masks.shape[0]):
                        mask = masks[i]
                        if np.any(mask):
                            self.axes.contourf(
                                mask, levels=[0.5, 1],
                                colors=[cmap(i)],
                                alpha=0.3
                            )
                            self.axes.contour(
                                mask, levels=[0.5],
                                colors=[cmap(i)], linewidths=0.8
                            )
                            y, x = np.nonzero(mask)
                            cx, cy = np.mean(x), np.mean(y)
                except Exception:
                    pass

            self.canvas.draw_idle()

    def updateVminVmax(self, frame):
        vmin, vmax = np.min(frame), np.max(frame)
        self.vmin, self.vmax = vmin, vmax
        if self.static_vmax is not None:
            self.vmax = self.static_vmax
        if self.static_vmin is not None:
            self.vmin = self.static_vmin

    def on_click(self, event):
        # Ignore clicks if they are meant for the toolbar (e.g., zooming/panning)
        if self.toolbar.mode != '':
            return
            
        if event.inaxes is not None:
            x, y = event.xdata, event.ydata
            x -= self.shm_width // 2
            y -= self.shm_height // 2
            x = int(round(x))
            y = int(round(y))
            self.last_clicked_coords = (x, y)
            self.coords_clicked.emit(x, y)

    def closeEvent(self, event):
        self.init_timer.stop()
        self.update_timer.stop()
        self.condition_timer.stop()
        if self.shm:
            self.shm.close()
        if self.metadata:
            self.metadata.close()
        if self.masks:
            self.masks.close()
        super().closeEvent(event)