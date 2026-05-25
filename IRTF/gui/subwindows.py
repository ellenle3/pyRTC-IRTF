from PyQt6.QtWidgets import QDialog, QFileDialog
from PyQt6 import uic
from PyQt6.QtGui import QIntValidator, QDoubleValidator

from macros import *
from pathlib import Path
# Get the directory of the current Python file
BASE_DIR = Path(__file__).parent
IXON_TEMP_MIN = -120  # same as Felix XUI
IXON_TEMP_MAX = 20

class IXONControlsWindow(QDialog):
    def __init__(self, start_tab=0, parent=None):
        super().__init__(parent)
        uic.loadUi(BASE_DIR / "ixon_controls.ui", self)
        self.ics = parent.ics
        self._connect_signals()
        self.tabIXON.setCurrentIndex(start_tab)

        if self.ics.get_component_class("wfs") != "AndorWFS":
            self.setEnabled = False
            self.parent.log("IXON controls disabled (not using Andor)", color="red")

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
        uic.loadUi(BASE_DIR / "aocals.ui", self)
        self.ics = parent.ics
        self._connect_signals()
        self.tabCals.setCurrentIndex(start_tab)

        if not self.ics.is_connected("loop"):
            self.setEnabled = False
            self.parent.log("AO cals disabled - loop is unavailable", color="red")

        if not self.ics.is_connected("slopes"):
            self.setEnabled = False
            self.parent.log("AO cals disabled - slopes is unavailable", color="red")

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
        self.parent.log(f"Loaded theoretical imat from {filepath}")
        self.parent.ao_cals["imat"]["theor_file"] = filepath

    def update_synth_imat_file(self, filepath):
        basename = Path(filepath).name
        self.gridImat_synth_file.setText(basename) # set gui text to just the filename, not full path
        self.parent.log(f"Loaded synthetic imat from {filepath}")
        self.parent.ao_cals["imat"]["synth_file"] = filepath

    def on_imat_file_return_pressed(self, is_theor):
        filepath = self.gridImat_theor_file.text()
        if not Path(filepath).is_file():
            self.parent.log(f"File not found: {filepath}", color="red")
            return
        if not filepath.endswith(".npy"):
            self.parent.log(f"Invalid file type: {filepath}. Must be .npy", color="red")
            return
        if is_theor:
            self.update_theor_imat_file(filepath)
        else:
            self.update_synth_imat_file(filepath)
        
    def on_imat_file_button_clicked(self, is_theor):
        filepath, _ = QFileDialog.getOpenFileName(parent=self,
                                                  caption="Select theor imat file",
                                                  directory="",
                                                  filter="npy files (*.npy)")
        if filepath:
            if is_theor:
                self.update_theor_imat_file(filepath)
            else:
                self.update_synth_imat_file(filepath)

    def on_imat_method_changed(self):
        method = self.gridImatMethod_combo.currentText()
        self.parent.ao_cals["imat"]["method"] = method
        self.parent.log(f"Set imat method to {method}")

    def on_imat_pokeAmp_changed(self):
        pokeAmp = float(self.gridImatParams_pokeAmp_entry.text())
        self.parent.ao_cals["imat"]["pokeAmp"] = pokeAmp
        self.parent.log(f"Set imat poke amplitude to {pokeAmp}")

    def on_imat_numItersIM_changed(self):
        numItersIM = int(self.gridImatParams_numItersIM_entry.text())
        self.parent.ao_cals["imat"]["numItersIM"] = numItersIM
        self.parent.log(f"Set imat numItersIM to {numItersIM}")
    
    def on_coords_RA_return_pressed(self, is_target):
        label = "target" if is_target else "guide"
        entry = self.gridCoords_targetRA_entry if is_target else self.gridCoords_guideRA

        ra = entry.text()
        try:
            result = parse_and_validate_ra(ra)
        except ValueError as e:
            self.parent.log(f"Invalid {label} RA: {e}", color="red")
            entry.setText("")
            return
        self.parent.ao_cals["ncpa"][f"ra_{label}"] = ra
        self.parent.log(f"Set {label} RA to {ra}")

    def on_coords_dec_return_pressed(self, is_target):
        label = "target" if is_target else "guide"
        entry = self.gridCoords_targetDec_entry if is_target else self.gridCoords_guideDec

        dec = entry.text()
        try:
            result = parse_and_validate_dec(dec)
        except ValueError as e:
            self.parent.log(f"Invalid {label} Dec: {e}", color="red")
            entry.setText("")
            return
        self.parent.ao_cals["ncpa"][f"dec_{label}"] = dec
        self.parent.log(f"Set {label} Dec to {dec}")

    def on_update_auto_offsets_clicked(self):
        ra_target = self.parent.ao_cals["ncpa"]["ra_target"]
        dec_target = self.parent.ao_cals["ncpa"]["dec_target"]
        ra_guide = self.parent.ao_cals["ncpa"]["ra_guide"]
        dec_guide = self.parent.ao_cals["ncpa"]["dec_guide"]

        try:
            auto_offsets = calc_ncpa_lookup(ra_target, dec_target, ra_guide, dec_guide)
        except ValueError as e:
            self.parent.log(f"Failed to parse coordinates.", color="red")
            return

        self.parent.ao_cals["ncpa"]["auto_offsets"] = auto_offsets
        self.parent.log(f"Updated auto slope offsets: {auto_offsets:.2f} arcseconds")

    def on_update_user_offsets_clicked(self):
        self.values = [linker.value() for linker in self.slider_linkers]
        self.parent.ao_cals["ncpa"]["user_offsets"] = self.values
        self.parent.log(f"Updated user slope offsets: {self.values}")

    def on_reset_all_offsets_clicked(self):
        self.parent.ao_cals["ncpa"]["auto_offsets"] = [0, 0, 0, 0, 0, 0, 0]
        self.parent.ao_cals["ncpa"]["user_offsets"] = [0, 0, 0, 0, 0, 0, 0]
        for linker in self.slider_linkers:
            linker.set_value(0.0)
        self.parent.log("Reset all slope offsets to 0")
class SliderEditLinker:
    """Links an existing QSlider and QLineEdit from Designer."""

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