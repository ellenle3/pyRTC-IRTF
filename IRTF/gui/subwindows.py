import os
from PyQt6.QtWidgets import QDialog, QFileDialog
from PyQt6 import uic
from PyQt6.QtGui import QIntValidator, QDoubleValidator
from PyQt6.QtCore import Qt

from pyRTC.Pipeline import initExistingShm
from gui_utils import *
from pathlib import Path
from roi_plot_widget import ROIPlotWidget
# Get the directory of the current Python file
BASE_DIR = Path(__file__).parent
IXON_TEMP_MIN = -120  # same as Felix XUI
IXON_TEMP_MAX = 20
ROI_MIN_SIZE = 16  # minimum ROI size to draw subap masks

class IXONControlsWindow(QDialog):
    def __init__(self, start_tab=0, parent=None):
        super().__init__(parent)
        uic.loadUi(os.path.join(BASE_DIR, "qtui", "ixon_controls.ui"), self)
        self.main_window = parent
        self.ics = self.main_window.ics
        self._connect_signals()
        self.tabIXON.setCurrentIndex(start_tab)

        if self.ics.get_component_class("wfs") != "AndorWFS":
            self.setEnabled(False)
            self.main_window.log("IXON controls disabled (not using Andor)", color="red")

    def _connect_signals(self):
        self.gridCooler_SetPt_entry.setValidator(QIntValidator(IXON_TEMP_MIN, IXON_TEMP_MAX))
        self.gridCooler_SetPt_entry.returnPressed.connect(self.on_cooler_setpt_return_pressed)
        self.gridCooler_Mode_combo.currentTextChanged.connect(self.on_cooler_mode_changed)
        self.gridShutter_combo.currentTextChanged.connect(self.on_shutter_mode_changed)

    def on_cooler_setpt_return_pressed(self):
        temp = int(self.gridCooler_SetPt_entry.text())
        self.ics.run("wfs", "setTemperature", temp)

    def on_cooler_mode_changed(self):
        mode = self.gridCooler_Mode_combo.currentText()
        if mode == "on":
            self.ics.run("wfs", "startCooler")
        elif mode == "off":
            self.ics.run("wfs", "stopCooler")

    def on_shutter_mode_changed(self):
        mode = self.gridShutter_combo.currentText()
        if mode == "closed":
            self.ics.run("wfs", "closeShutter")
        elif mode == "open":
            self.ics.run("wfs", "openShutter")

class AOCalsWindow(QDialog):
    def __init__(self, start_tab=0, parent=None):
        super().__init__(parent)
        uic.loadUi(os.path.join(BASE_DIR, "qtui", "aocals.ui"), self)
        self.main_window = parent
        self.ics = self.main_window.ics
        self._connect_signals()
        self.tabCals.setCurrentIndex(start_tab)

        if not self.ics.is_connected("loop"):
            self.setEnabled(False)
            self.main_window.log("AO cals disabled - loop is unavailable", color="red")

        if not self.ics.is_connected("slopes"):
            self.setEnabled(False)
            self.main_window.log("AO cals disabled - slopes is unavailable", color="red")

        slider_min = -1
        slider_max = 1
        scale = 100
        self.slider_linkers = [
            SliderEditLinker(self.gridTune_tip_slider, self.gridTune_tip_entry, slider_min, slider_max, scale=scale),
            SliderEditLinker(self.gridTune_tilt_slider, self.gridTune_tilt_entry, slider_min, slider_max, scale=scale),
            SliderEditLinker(self.gridTune_focus_slider, self.gridTune_focus_entry, slider_min, slider_max, scale=scale),
            SliderEditLinker(self.gridTune_a1_slider, self.gridTune_a1_entry, slider_min, slider_max, scale=scale),
            SliderEditLinker(self.gridTune_a2_slider, self.gridTune_a2_entry, slider_min, slider_max, scale=scale),
            SliderEditLinker(self.gridTune_c1_slider, self.gridTune_c1_entry, slider_min, slider_max, scale=scale),
            SliderEditLinker(self.gridTune_c2_slider, self.gridTune_c2_entry, slider_min, slider_max, scale=scale),
        ]

    def _connect_signals(self):
        self.gridImat_theor_file.returnPressed.connect(lambda: self.on_imat_file_return_pressed(is_theor=True))
        self.gridImat_theor_file_button.clicked.connect(lambda: self.on_imat_file_button_clicked(is_theor=True))
        self.gridImat_synth_file.returnPressed.connect(lambda: self.on_imat_file_return_pressed(is_theor=False))
        self.gridImat_synth_file_button.clicked.connect(lambda: self.on_imat_file_button_clicked(is_theor=False))
        self.gridImatMethod_combo.currentTextChanged.connect(self.on_imat_method_changed)
        self.gridImatParams_pokeAmp_entry.setValidator(QDoubleValidator(0.0, 2.0, 4))
        self.gridImatParams_pokeAmp_entry.returnPressed.connect(self.on_imat_pokeAmp_changed)
        self.gridImatParams_numItersIM_entry.setValidator(QIntValidator(1, 10000))
        self.gridImatParams_numItersIM_entry.returnPressed.connect(self.on_imat_numItersIM_changed)

        self.gridCoords_targetRA_entry.returnPressed.connect(lambda: self.on_coords_RA_return_pressed(is_target=True))
        self.gridCoords_targetDec_entry.returnPressed.connect(lambda: self.on_coords_dec_return_pressed(is_target=True))
        self.gridCoords_guideRA_entry.returnPressed.connect(lambda: self.on_coords_RA_return_pressed(is_target=False))
        self.gridCoords_guideDec_entry.returnPressed.connect(lambda: self.on_coords_dec_return_pressed(is_target=False))
        self.updateAutoOffsets_button.clicked.connect(self.on_update_auto_offsets_clicked)
        self.updateUserOffsets_button.clicked.connect(self.on_update_user_offsets_clicked)
        self.resetAllOffsets_button.clicked.connect(self.on_reset_all_offsets_clicked)

    def update_theor_imat_file(self, filepath):
        basename = Path(filepath).name
        self.gridImat_theor_file.setText(basename) # set gui text to just the filename, not full path
        self.main_window.log(f"Loaded theoretical imat from {filepath}")
        self.main_window.ao_cals["imat"]["theor_file"] = filepath

    def update_synth_imat_file(self, filepath):
        basename = Path(filepath).name
        self.gridImat_synth_file.setText(basename) # set gui text to just the filename, not full path
        self.main_window.log(f"Loaded synthetic imat from {filepath}")
        self.main_window.ao_cals["imat"]["synth_file"] = filepath

    def on_imat_file_return_pressed(self, is_theor):
        filepath = self.gridImat_theor_file.text()
        if not Path(filepath).is_file():
            self.main_window.log(f"File not found: {filepath}", color="red")
            return
        if not filepath.endswith(".npy"):
            self.main_window.log(f"Invalid file type: {filepath}. Must be .npy", color="red")
            return
        if is_theor:
            self.update_theor_imat_file(filepath)
        else:
            self.update_synth_imat_file(filepath)
        
    def on_imat_file_button_clicked(self, is_theor):
        filepath, _ = QFileDialog.getOpenFileName(parent=self,
                                                  caption="Select theor imat file",
                                                  directory="",
                                                  filter="npy files (*.npy)",
                                                  options=QFileDialog.Option.DontUseNativeDialog)
        if filepath:
            if is_theor:
                self.update_theor_imat_file(filepath)
            else:
                self.update_synth_imat_file(filepath)

    def on_imat_method_changed(self):
        method = self.gridImatMethod_combo.currentText()
        self.main_window.ao_cals["imat"]["method"] = method
        self.main_window.log(f"Set imat method to {method}")

    def on_imat_pokeAmp_changed(self):
        pokeAmp = float(self.gridImatParams_pokeAmp_entry.text())
        self.main_window.ao_cals["imat"]["pokeAmp"] = pokeAmp
        self.main_window.log(f"Set imat poke amplitude to {pokeAmp}")

    def on_imat_numItersIM_changed(self):
        numItersIM = int(self.gridImatParams_numItersIM_entry.text())
        self.main_window.ao_cals["imat"]["numItersIM"] = numItersIM
        self.main_window.log(f"Set imat numItersIM to {numItersIM}")
    
    def on_coords_RA_return_pressed(self, is_target):
        label = "target" if is_target else "guide"
        entry = self.gridCoords_targetRA_entry if is_target else self.gridCoords_guideRA

        ra = entry.text()
        try:
            result = parse_and_validate_ra(ra)
        except ValueError as e:
            self.main_window.log(f"Invalid {label} RA: {e}", color="red")
            entry.setText("")
            return
        self.main_window.ao_cals["ncpa"][f"ra_{label}"] = ra
        self.main_window.log(f"Set {label} RA to {ra}")

    def on_coords_dec_return_pressed(self, is_target):
        label = "target" if is_target else "guide"
        entry = self.gridCoords_targetDec_entry if is_target else self.gridCoords_guideDec

        dec = entry.text()
        try:
            result = parse_and_validate_dec(dec)
        except ValueError as e:
            self.main_window.log(f"Invalid {label} Dec: {e}", color="red")
            entry.setText("")
            return
        self.main_window.ao_cals["ncpa"][f"dec_{label}"] = dec
        self.main_window.log(f"Set {label} Dec to {dec}")

    def on_update_auto_offsets_clicked(self):
        ra_target = self.main_window.ao_cals["ncpa"]["ra_target"]
        dec_target = self.main_window.ao_cals["ncpa"]["dec_target"]
        ra_guide = self.main_window.ao_cals["ncpa"]["ra_guide"]
        dec_guide = self.main_window.ao_cals["ncpa"]["dec_guide"]

        try:
            auto_offsets = calc_ncpa_lookup(ra_target, dec_target, ra_guide, dec_guide)
        except ValueError as e:
            self.main_window.log(f"Failed to parse coordinates.", color="red")
            return

        self.main_window.ao_cals["ncpa"]["auto_offsets"] = auto_offsets
        self.main_window.log(f"Updated auto slope offsets: {auto_offsets:.2f} arcseconds")

    def on_update_user_offsets_clicked(self):
        self.values = [linker.value() for linker in self.slider_linkers]
        self.main_window.ao_cals["ncpa"]["user_offsets"] = self.values
        self.main_window.log(f"Updated user slope offsets: {self.values}")

    def on_reset_all_offsets_clicked(self):
        self.main_window.ao_cals["ncpa"]["auto_offsets"] = [0, 0, 0, 0, 0, 0, 0]
        self.main_window.ao_cals["ncpa"]["user_offsets"] = [0, 0, 0, 0, 0, 0, 0]
        for linker in self.slider_linkers:
            linker.set_value(0.0)
        self.main_window.log("Reset all slope offsets to 0")

class ROIWindow(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        uic.loadUi(os.path.join(BASE_DIR, "qtui", "roi_selector.ui"), self)
        self.main_window = parent
        self.ics = self.main_window.ics

        if not self.ics.is_connected("wfs"):
            self.setEnabled(False)
            self.main_window.log("WFS is not connected.", color="red")
            return
        
        # Stop the WFS and force one exposure so the SHM is not empty
        self.main_window.ics.run("wfs", "stop")
        self.main_window.ics.run("wfs", "expose")

        self._connect_signals()

        # Camera setup - read current ROI and get a single image.
        width = self.ics.get("wfs", "roiWidth")
        height = self.ics.get("wfs", "roiHeight")
        left = self.ics.get("wfs", "roiLeft")
        top = self.ics.get("wfs", "roiTop")
        self.init_roi = [width, height, left, top]
        if width < 16 or height < 16:
            self.main_window.log(f"Current ROI is too small ({width}x{height}). Must be at least {ROI_MIN_SIZE}x{ROI_MIN_SIZE}", color="red")
            self.setEnabled(False)
            return

        self.binning = self.ics.get("wfs", "binning")
        self.xmax = self.ics.get("wfs", "xmax")     # max ROI sizes
        self.ymax = self.ics.get("wfs", "ymax")

        self.wfs_shm, self.image_shape, self.image_dtype = initExistingShm("wfs")
        image = self.wfs_shm.read_noblock(SAFE=True, GPU=False)
        # Pad to full frame, filling in zeros wherever is not covered by the 
        # current ROI
        image = pad_roi_to_full_frame(image, self.xmax, self.ymax, self.binning, *self.init_roi)
        
        # Information that the main window will read
        self.last_valid_roi = []
        self.roi_to_main_window = ""
        self.subapmasks_center = [0, 0] 
        self.subapmasks_size = 1
        self._set_roi_defaults()     # Set the above params
        self._set_masks_defaults()

        self.roi_mpl.link_window_data(
            self.gridROI_size_width_entry, 
            self.gridROI_size_pos_entry,
            self.binning
        )
        self.roi_mpl.set_image(image)
        self.roi_mpl.draw_roi_from_text()

    def _set_roi_defaults(self):
        # default size of the roi is either 128 or the max size that fits in the
        # current ROI (set before this window was opened)
        default_size = min(128, self.init_roi[0], self.init_roi[1])
        self.gridROI_size_width_entry.setText(f"{default_size} {default_size}")
        
        # Put in the center of the image
        default_left = 1 + (self.xmax - default_size) // 2
        default_top = 1 + (self.ymax - default_size) // 2
        self.gridROI_size_pos_entry.setText(f"{default_left} {default_top}")

        # Update params to send to main window
        self.last_valid_roi = [default_size, default_size, default_left, default_top]
        self.roi_to_main_window = f"{self.last_valid_roi[0]} {self.last_valid_roi[1]} {self.last_valid_roi[2]} {self.last_valid_roi[3]}"

    def _set_masks_defaults(self):
        # Center in the middle of the ROI, try to make 64x64 (or whatever fits in the ROI)...
        # Center coords are relative to the center of the ROI that will be drawn
        # by the user, not the full frame.
        self.subapmasks_center = [0, 0]  # cx, cy
        self.subapmasks_size = min(64, self.init_roi[0], self.init_roi[1])
        self.gridMasks_center_entry.setText(f"{self.subapmasks_center[0]} {self.subapmasks_center[1]}")
        self.gridMasks_size_combo.setCurrentText(str(self.subapmasks_size))

    def _connect_signals(self):
        self.gridROI_size_width_entry.setValidator(validator_2int())  # two space delimited ints only
        self.gridROI_size_pos_entry.setValidator(validator_2int())   
        # For when the user types into the boxes
        self.gridROI_size_width_entry.returnPressed.connect(self.on_roisize_text_changed)
        self.gridROI_size_pos_entry.returnPressed.connect(self.on_roipos_text_changed)
        # Listen for any changes by the click and drag code
        self.gridROI_size_width_entry.textChanged.connect(self.sync_memory_from_ui)
        self.gridROI_size_pos_entry.textChanged.connect(self.sync_memory_from_ui)
        self.gridROITitle_reset_button.clicked.connect(self.on_reset_roi_clicked)
        self.done_button.clicked.connect(self.on_done_clicked)

        self.gridMasks_center_entry.setValidator(validator_2int())
        self.gridMasks_size_combo.currentTextChanged.connect(self.on_masks_size_changed)
        self.gridMasks_center_entry.returnPressed.connect(self.on_masks_center_changed)
        self.gridMasksTitle_reset_button.clicked.connect(self.on_reset_masks_clicked)

    def sync_memory_from_ui(self):
        """
        Silently updates last_valid_roi whenever the UI text changes to a valid integer set
        (e.g., when the user drags the ROI box). This ensures our 'revert' backup is always fresh.
        """
        try:
            # Using split() with no arguments handles variable space padding robustly
            width, height = [int(x) for x in self.gridROI_size_width_entry.text().split()]
            left, top = [int(x) for x in self.gridROI_size_pos_entry.text().split()]
            
            new_roi = [width, height, left, top]
            is_valid, _ = is_roi_valid(self.xmax, self.ymax, self.binning, *new_roi)
            if is_valid:
                self.last_valid_roi = new_roi
        except ValueError:
            pass

    # Subap ask controls
    def on_masks_size_changed(self):
        size = int(self.gridMasks_size_combo.currentText())
        self.subapmasks_size = size
        self.roi_mpl.update_subap_masks(self.subapmasks_center, self.subapmasks_size)

    def on_masks_center_changed(self):
        try:
            # validator should prevent this, but just in case... allow graceful
            # exit of the GUI
            cx, cy = [int(x) for x in self.gridMasks_center_entry.text().split()]
        except ValueError:
            return
        
        is_valid, error_message = is_masks_valid(cx, cy, self.subapmasks_size,
                                                 self.last_valid_roi[0], self.last_valid_roi[1])
        if not is_valid:
            self.main_window.log(f"Invalid subap mask center: {error_message}", color="red")
            # Revert to last valid center
            self.gridMasks_center_entry.blockSignals(True)
            self.gridMasks_center_entry.setText(f"{self.subapmasks_center[0]} {self.subapmasks_center[1]}")
            self.gridMasks_center_entry.blockSignals(False)
            return
        
        self.subapmasks_center = [cx, cy]
        #self.roi_mpl.update_subap_masks(self.subapmasks_center, self.subapmasks_size)
    
    # ROI controls
    def on_reset_roi_clicked(self):
        self._set_roi_defaults()
        self.roi_mpl.draw_roi_from_text()

    def on_roisize_text_changed(self):
        entry = self.gridROI_size_width_entry
        try:
            values = [int(x) for x in entry.text().split()]
            # Safely capture current position coordinates from the live GUI
            pos_values = [int(x) for x in self.gridROI_size_pos_entry.text().split()]
            new_roi = [values[0], values[1], pos_values[0], pos_values[1]]
        except ValueError:
            return

        is_valid, error_message = is_roi_valid(self.xmax, self.ymax, self.binning, *new_roi)
        if not is_valid:
            self.main_window.log(f"Invalid ROI: {error_message}", color="red")
            entry.blockSignals(True)
            entry.setText(f"{self.last_valid_roi[0]} {self.last_valid_roi[1]}")
            entry.blockSignals(False)
            return
        
        self.last_valid_roi = new_roi
        self.plot_widget.draw_roi_from_text()

    def on_roipos_text_changed(self):
        entry = self.gridROI_size_pos_entry
        try:
            values = [int(x) for x in entry.text().split()]
            # Safely capture current size coordinates from the live GUI
            size_values = [int(x) for x in self.gridROI_size_width_entry.text().split()]
            new_roi = [size_values[0], size_values[1], values[0], values[1]]
        except ValueError:
            return

        is_valid, error_message = is_roi_valid(self.xmax, self.ymax, self.binning, *new_roi)
        if not is_valid:
            self.main_window.log(f"Invalid ROI: {error_message}", color="red")
            # Block signals to prevent triggering infinite
            entry.blockSignals(True)
            entry.setText(f"{self.last_valid_roi[2]} {self.last_valid_roi[3]}")
            entry.blockSignals(False)
            return
        
        self.last_valid_roi = new_roi
        self.plot_widget.draw_roi_from_text()

    def on_done_clicked(self):
        try:
            width, height = [int(x) for x in self.gridROI_size_width_entry.text().split()]
            left, top = [int(x) for x in self.gridROI_size_pos_entry.text().split()]
        except ValueError:
            self.main_window.log("Cannot save: entry fields contain unparseable values.", color="red")
            return

        new_roi = [width, height, left, top]
        is_valid, error_message = is_roi_valid(self.xmax, self.ymax, self.binning, *new_roi)
        if not is_valid:
            self.main_window.log(f"Cannot save invalid ROI: {error_message}", color="red")
            return

        self.roi_to_main_window = f"{width} {height} {left} {top}"
        self.accept()

class SliderEditLinker:
    """Links an existing QSlider and QLineEdit."""

    def __init__(self, slider, edit, minimum, maximum, scale=100):
        self._slider = slider
        self._edit = edit
        self._min = minimum
        self._max = maximum
        self._scale = scale
        self._blocking = False

        slider.setMinimum(int(minimum * scale))
        slider.setMaximum(int(maximum * scale))

        slider.valueChanged.connect(self._slider_changed)
        edit.returnPressed.connect(self._edit_changed)

        self.set_value(minimum)

    def _slider_changed(self, int_val):
        if self._blocking:
            return
        val = int_val / self._scale
        self._blocking = True
        self._edit.setText(f"{val:+.2f}")  # e.g. +0.50, -1.23
        self._blocking = False

    def _edit_changed(self):
        if self._blocking:
            return
        try:
            val = float(self._edit.text())
        except ValueError:
            self._edit.setText(f"{self.value():+.2f}")
            return
        self.set_value(val)

    def value(self):
        return self._slider.value() / self._scale

    def set_value(self, val):
        val = max(self._min, min(self._max, val))
        self._blocking = True
        self._slider.setValue(int(val * self._scale))
        self._edit.setText(f"{val:+.2f}")
        self._blocking = False