from PyQt6.QtWidgets import QDialog
from PyQt6 import uic
from PyQt6.QtGui import QIntValidator

from pathlib import Path
# Get the directory of the current Python file
BASE_DIR = Path(__file__).parent
IXON_TEMP_MIN = -120  # same as Felix XUI
IXON_TEMP_MAX = 20

class IXONControlsWindow(QDialog):
    def __init__(self, components, start_tab=0, parent=None):
        super().__init__(parent)
        uic.loadUi(BASE_DIR / "ixon_controls.ui", self)
        self.components = components
        self._connect_signals()
        self.tabIXON.setCurrentIndex(start_tab)

    def _connect_signals(self):
        self.gridCooler_SetPt_entry.setValidator(QIntValidator(IXON_TEMP_MIN, IXON_TEMP_MAX))
        self.gridCooler_SetPt_entry.returnPressed.connect(self.on_cooler_setpt_return_pressed)
        self.gridCooler_Mode_combo.currentTextChanged.connect(self.on_cooler_mode_changed)
        self.gridShutter_combo.currentTextChanged.connect(self.on_shutter_mode_changed)

    def on_cooler_setpt_return_pressed(self):
        temp = int(self.gridCooler_SetPt_entry.text())
        self.components["wfs"].run("setTemperature", temp)

    def on_cooler_mode_changed(self):
        mode = self.gridCooler_Mode_combo.currentText()
        if mode == "on":
            self.components["wfs"].run("startCooler")
        elif mode == "off":
            self.components["wfs"].run("stopCooler")

    def on_shutter_mode_changed(self):
        mode = self.gridShutter_combo.currentText()
        if mode == "closed":
            self.components["wfs"].run("closeShutter")
        elif mode == "open":
            self.components["wfs"].run("openShutter")