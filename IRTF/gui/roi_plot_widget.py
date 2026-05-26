import numpy as np
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLineEdit, QComboBox
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qtagg import NavigationToolbar2QT as NavigationToolbar
from matplotlib.figure import Figure
from matplotlib.patches import Rectangle
from matplotlib.transforms import Affine2D

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
        
        layout.addWidget(self.toolbar) 
        layout.addWidget(self.canvas)
        self.setLayout(layout)
        
        # Internal State Variables
        self.roi_rect = None
        self.roi_handle = None
        self.mask_patches = []
        
        self.dragging = None  # None, 'roi', or 'mask'
        self.drag_offset_x = 0
        self.drag_offset_y = 0
        self.mask_drag_start_cx = 0
        self.mask_drag_start_cy = 0
        self.mask_drag_start_mouse_x = 0
        self.mask_drag_start_mouse_y = 0
        
        # Text entries from window
        self.entry_size = None
        self.entry_coords = None
        self.binning = None
        self.entry_mask_center = None
        self.entry_mask_size = None
        self.is_masks_valid_func = None
        self.mask_rotation = 0.0  # Constant float for rotation
        
        # Connect Matplotlib Mouse Events
        self.canvas.mpl_connect('button_press_event', self.on_press)
        self.canvas.mpl_connect('motion_notify_event', self.on_motion)
        self.canvas.mpl_connect('button_release_event', self.on_release)

    def link_window_data(self, size_edit: QLineEdit, pos_edit: QLineEdit, binning: int, 
                         mask_center_edit: QLineEdit = None, mask_size_combo: QComboBox = None, 
                         validation_func = None, mask_rotation: float = 0.0):
        """Hook up QLineEdits to this widget."""
        self.entry_size = size_edit
        self.entry_coords = pos_edit
        self.binning = binning
        self.entry_mask_center = mask_center_edit
        self.entry_mask_size = mask_size_combo
        self.is_masks_valid_func = validation_func
        self.mask_rotation = mask_rotation

    def parse_entries(self):
        size_text = self.entry_size.text().strip()
        pos_text = self.entry_coords.text().strip()
        width, height = [int(x) for x in size_text.split()]
        left, top = [int(x) for x in pos_text.split()]
        return width, height, left, top
    
    def set_image(self, image_data):
        """Displays the previous image and initializes the plot."""
        self.ax.clear()
        self.ax.axis('off')  
        self.ax.imshow(image_data, cmap='gray', origin='upper', aspect='equal')
        
        # Wiping the axes clears patches, so reset references 
        self.roi_rect = None
        self.roi_handle = None
        self.mask_patches = []
        
        self.canvas.draw()

    def draw_roi_from_text(self):
        """Reads the text entries and draws/updates the pink rectangle and masks."""
        if not all([self.entry_size, self.entry_coords, self.binning]):
            return

        try:
            width, height, left, top = self.parse_entries()
        except ValueError:
            return

        # Restore original integer mapping math perfectly!
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

        # Dynamic, scalable corner handle for easy ROI drag priority
        handle_w = max(5, width * 0.15)
        handle_h = max(5, height * 0.15)
        if self.roi_handle is None:
            self.roi_handle = Rectangle((left, top), handle_w, handle_h, 
                                        linewidth=1, edgecolor='deeppink', facecolor='deeppink', alpha=0.6)
            self.ax.add_patch(self.roi_handle)
        else:
            self.roi_handle.set_xy((left, top))
            self.roi_handle.set_width(handle_w)
            self.roi_handle.set_height(handle_h)
            
        # Draw Masks
        if self.entry_mask_center and self.entry_mask_size:
            try:
                cx, cy = [int(x) for x in self.entry_mask_center.text().split()]
                mask_size = int(self.entry_mask_size.currentText())
                
                mask_size_binned = mask_size / self.binning
                half_mask_binned = mask_size_binned / 2.0
                
                # Center coordinates
                roi_center_x_binned = left + (width / 2.0)
                roi_center_y_binned = top + (height / 2.0)
                
                mask_center_x_binned = roi_center_x_binned + (cx / self.binning)
                mask_center_y_binned = roi_center_y_binned + (cy / self.binning)

                quadrant_coords = [
                    (mask_center_x_binned - half_mask_binned, mask_center_y_binned - half_mask_binned), # Upper Left
                    (mask_center_x_binned - half_mask_binned, mask_center_y_binned),                    # Lower Left
                    (mask_center_x_binned, mask_center_y_binned - half_mask_binned),                    # Upper Right
                    (mask_center_x_binned, mask_center_y_binned)                                        # Lower Right
                ]
                quadrant_colors = [
                    (0.9, 0.1, 0.1, 0.35),  # Red
                    (0.1, 0.1, 0.9, 0.35),  # Blue
                    (0.1, 0.9, 0.1, 0.35),  # Green
                    (0.9, 0.9, 0.1, 0.35)   # Yellow
                ]

                # Create a rotation transform around the center point of the 4 patches
                rotation_transform = Affine2D().rotate_deg_around(
                    mask_center_x_binned, mask_center_y_binned, self.mask_rotation
                ) + self.ax.transData

                if not self.mask_patches:
                    for i in range(4):
                        patch = Rectangle(quadrant_coords[i], half_mask_binned, half_mask_binned,
                                          linewidth=1, edgecolor='white', facecolor=quadrant_colors[i],
                                          transform=rotation_transform)
                        self.ax.add_patch(patch)
                        self.mask_patches.append(patch)
                else:
                    for i in range(4):
                        self.mask_patches[i].set_xy(quadrant_coords[i])
                        self.mask_patches[i].set_width(half_mask_binned)
                        self.mask_patches[i].set_height(half_mask_binned)
                        self.mask_patches[i].set_transform(rotation_transform)
            except ValueError:
                pass

        self.canvas.draw_idle()

    # --- Drag and Drop Logic ---

    def on_press(self, event):
        if self.toolbar.mode != '' or event.inaxes != self.ax or self.roi_rect is None:
            return

        # 1. Did they explicitly click the ROI Handle?
        if self.roi_handle and self.roi_handle.contains(event)[0]:
            self.dragging = 'roi'
            self._set_entries_enabled(False)
            x, y = self.roi_rect.get_xy()
            self.drag_offset_x = x - event.xdata
            self.drag_offset_y = y - event.ydata
            return

        # 2. Did they click inside a mask quadrant?
        # Matplotlib's "contains" seamlessly handles the Affine2D rotation transform!
        if self.mask_patches:
            for patch in self.mask_patches:
                if patch.contains(event)[0]:
                    self.dragging = 'mask'
                    self._set_entries_enabled(False)
                    self.mask_drag_start_mouse_x = event.xdata
                    self.mask_drag_start_mouse_y = event.ydata
                    try:
                        cx, cy = [int(x) for x in self.entry_mask_center.text().split()]
                        self.mask_drag_start_cx = cx
                        self.mask_drag_start_cy = cy
                    except ValueError:
                        self.dragging = None
                    return

        # 3. Did they click anywhere else inside the main ROI body?
        if self.roi_rect.contains(event)[0]:
            self.dragging = 'roi'
            self._set_entries_enabled(False)
            x, y = self.roi_rect.get_xy()
            self.drag_offset_x = x - event.xdata
            self.drag_offset_y = y - event.ydata

    def on_motion(self, event):
        if not self.dragging or event.inaxes != self.ax:
            return
            
        if self.dragging == 'roi':
            new_x = event.xdata + self.drag_offset_x
            new_y = event.ydata + self.drag_offset_y
            self.roi_rect.set_xy((new_x, new_y))
            
            if self.roi_handle:
                self.roi_handle.set_xy((new_x, new_y))
            
            self.canvas.draw_idle()
            
        elif self.dragging == 'mask':
            dx_unbinned = int(round((event.xdata - self.mask_drag_start_mouse_x) * self.binning))
            dy_unbinned = int(round((event.ydata - self.mask_drag_start_mouse_y) * self.binning))
            
            target_cx = self.mask_drag_start_cx + dx_unbinned
            target_cy = self.mask_drag_start_cy + dy_unbinned
            
            try:
                roi_w, roi_h, _, _ = self.parse_entries()
                mask_size = int(self.entry_mask_size.currentText())
                
                is_valid, _ = self.is_masks_valid_func(mask_size, target_cx, target_cy, roi_w, roi_h)
                if is_valid:
                    self.entry_mask_center.setText(f"{target_cx} {target_cy}")
                    self.draw_roi_from_text()
            except ValueError:
                pass

    def on_release(self, event):
        if not self.dragging:
            return
            
        current_drag = self.dragging
        self.dragging = None
        self._set_entries_enabled(True)
        
        if current_drag == 'roi':
            x, y = self.roi_rect.get_xy()
            
            binned_x = int(round(x))
            binned_y = int(round(y))
            new_left = max(1, (binned_x * self.binning) + 1)
            new_top = max(1, (binned_y * self.binning) + 1)
            
            self.entry_coords.setText(f"{new_left} {new_top}")
            self.draw_roi_from_text()
            
        elif current_drag == 'mask':
            self.draw_roi_from_text()

    def _set_entries_enabled(self, state):
        if self.entry_size and self.entry_coords:
            self.entry_size.setEnabled(state)
            self.entry_coords.setEnabled(state)
            if self.entry_mask_center:
                self.entry_mask_center.setEnabled(state)
                self.entry_mask_size.setEnabled(state)
