from PyQt6.QtWidgets import QDialog
from PyQt6 import uic
from PyQt6.QtGui import QIntValidator

from pathlib import Path
# Get the directory of the current Python file
BASE_DIR = Path(__file__).parent
IXON_TEMP_MIN = -120  # same as Felix XUI
IXON_TEMP_MAX = 20

class IXONControlsWindow(QDialog):
    def __init__(self, ics, start_tab=0, parent=None):
        super().__init__(parent)
        uic.loadUi(BASE_DIR / "ixon_controls.ui", self)
        self.ics = ics
        self._connect_signals()
        self.tabIXON.setCurrentIndex(start_tab)

        if ics.components["wfs"]["type"] != "AndorWFS":
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