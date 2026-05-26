import sys
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLineEdit
from matplotlib.figure import Figure
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qtagg import NavigationToolbar2QT as NavigationToolbar
from matplotlib.patches import Rectangle

class ROIPlotWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # 1. Matplotlib setup - configured to use 100% of the canvas space
        self.figure = Figure()
        self.canvas = FigureCanvas(self.figure)
        self.toolbar = NavigationToolbar(self.canvas, self)
        self.ax = self.figure.add_subplot(111)
        
        # Strip all whitespace padding inside the Matplotlib figure
        self.figure.subplots_adjust(left=0, right=1, bottom=0, top=1)
        
        # 2. Layout setup - stripped of all GUI margins and spacing
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # Note: If you want *strictly* the image, comment out the next line to hide the toolbar
        layout.addWidget(self.toolbar) 
        layout.addWidget(self.canvas)
        self.setLayout(layout)
        
        # Internal State Variables
        self.roi_rect = None
        self.dragging = False
        self.drag_offset_x = 0
        self.drag_offset_y = 0
        
        # Text entries from window
        self.entry_size = None
        self.entry_coords = None
        self.binning = None
        
        # Connect Matplotlib Mouse Events
        self.canvas.mpl_connect('button_press_event', self.on_press)
        self.canvas.mpl_connect('motion_notify_event', self.on_motion)
        self.canvas.mpl_connect('button_release_event', self.on_release)

    def link_window_data(self, size_edit: QLineEdit, pos_edit: QLineEdit, binning: int):
        """Hook up QLineEdits to this widget."""
        self.entry_size = size_edit
        self.entry_coords = pos_edit
        self.binning = binning

    def parse_entries(self):
        size_text = self.entry_size.text().strip()
        pos_text = self.entry_coords.text().strip()
        width, height = size_text.split(" ")  # Assuming format "width height"
        left, top = pos_text.split(" ")       # Assuming format "left top"
        return int(width), int(height), int(left), int(top)
    
    def set_image(self, image_data):
        """Displays the previous image and initializes the plot."""
        self.ax.clear()
        self.ax.axis('off')  
        self.ax.imshow(image_data, cmap='gray', origin='upper', aspect='equal')
        self.canvas.draw()

    def draw_roi_from_text(self):
        """Reads the text entries and draws/updates the pink rectangle."""
        if not all([self.entry_size, self.entry_coords, self.binning]):
            return

        width, height, left, top = self.parse_entries()
        left = left - 1        # Convert from Andor's 1-based indexing to 0
        top = top - 1
        left //= self.binning  # Apply binning factor
        top //= self.binning
        width //= self.binning
        height //= self.binning

        if self.roi_rect is None:
            self.roi_rect = Rectangle((left, top), width, height, 
                                      linewidth=2, edgecolor='pink', facecolor='none')
            self.ax.add_patch(self.roi_rect)
        else:
            self.roi_rect.set_xy((left, top))
            self.roi_rect.set_width(width)
            self.roi_rect.set_height(height)
            
        self.canvas.draw_idle()

    # --- Drag and Drop Logic ---

    def on_press(self, event):
        if self.toolbar.mode != '' or event.inaxes != self.ax or self.roi_rect is None:
            return

        contains, _ = self.roi_rect.contains(event)
        if contains:
            self.dragging = True
            self._set_entries_enabled(False)
            
            x, y = self.roi_rect.get_xy()
            self.drag_offset_x = x - event.xdata
            self.drag_offset_y = y - event.ydata

    def on_motion(self, event):
        if not self.dragging or event.inaxes != self.ax:
            return
            
        new_x = event.xdata + self.drag_offset_x
        new_y = event.ydata + self.drag_offset_y
        self.roi_rect.set_xy((new_x, new_y))
        self.canvas.draw_idle()

    def on_release(self, event):
        if not self.dragging:
            return
            
        self.dragging = False
        self._set_entries_enabled(True)
        
        # FIX: Explicitly get the x and y coordinates from the rectangle object
        x, y = self.roi_rect.get_xy()
        
        # Expand back to unbinned coordinates and add 1 for Andor's indexing
        binned_x = int(round(x))
        binned_y = int(round(y))
        new_left = max(1, (binned_x * self.binning) + 1)
        new_top = max(1, (binned_y * self.binning) + 1)
        
        self.entry_coords.setText(f"{new_left} {new_top}")
        
        # Redraw to snap the visual rectangle to the rounded integer coordinates
        self.draw_roi_from_text()

    def _set_entries_enabled(self, state):
        if self.entry_size and self.entry_coords:
            self.entry_size.setEnabled(state)
            self.entry_coords.setEnabled(state)


## ALSO IN SlopesProcess.py. REMOVE IT FROM HERE WHEN REFACTORING.
def quadrant_masks(N, angle_deg=0.0):
    """
    Generate 4 quadrant masks for an NxN image with optional axis rotation. Used
    to generate Felix subap masks.

    Parameters
    ----------
    N : int
        Image size (NxN).
    angle_deg : float
        Rotation angle in degrees (counterclockwise).

    Returns
    -------
    masks : np.ndarray
        Array of shape (4, N, N) with dtype '>i8'.
        Order: [upper-left, lower-left, upper-right, lower-right].
    """
    # Grid of pixel centers
    y, x = np.meshgrid(np.arange(N), np.arange(N), indexing='ij')
    cx, cy = (N - 1) / 2.0, (N - 1) / 2.0
    x = x - cx
    y = y - cy

    # Rotate coordinates
    theta = np.deg2rad(angle_deg)
    xr =  x * np.cos(theta) + y * np.sin(theta)
    yr = -x * np.sin(theta) + y * np.cos(theta)

    # Allocate
    masks = np.zeros((4, N, N), dtype=">i8")

    # Quadrants (strict inequalities)
    masks[0] = (xr < 0) & (yr > 0)    # upper left
    masks[1] = (xr < 0) & (yr < 0)    # lower left
    masks[2] = (xr > 0) & (yr > 0)    # upper right
    masks[3] = (xr > 0) & (yr < 0)    # lower right

    # Axis tie-break rules
    masks[1] |= (xr <= 0) & (yr == 0)   # left side y=0
    masks[3] |= (xr >  0) & (yr == 0)   # right side y=0

    return masks
