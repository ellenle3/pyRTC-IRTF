import sys
import os
import json
import signal
from PyQt6.QtCore import QTimer, QEvent
from PyQt6.QtWidgets import QApplication, QWidget
from PyQt6 import uic
from PyQt6.QtGui import QIntValidator, QDoubleValidator, QColor, QTextCursor, QIcon

from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
#from IRTF.gui.pyrtcgui_setup import Ui_pyrtcGUI
from launchers import *

# Get the directory of the current Python file
BASE_DIR = Path(__file__).parent

MAX_LOG_LINES = 100  # max length of console log

class MainWindow(QWidget):
    def __init__(self):
        signal.signal(signal.SIGINT, self._on_ctrl_c) # Allow Ctrl-C to quit the app in terminal
        super().__init__()
        uic.loadUi(os.path.join(BASE_DIR, "pyrtc_felix_control_gui.ui"), self)
        # iconpath = "tropius.icns"
        # self.setWindowIcon(QIcon(str(iconpath)))

        self.panelConsole_display_text.setReadOnly(True)          # for console output

        # Before launching anything, try shutting down all existing components
        # in case a previous crash.
        shutdown_all()
        # dict to store component launchers
        self.components = {
            "wfs": None,
            "slopes": None,
            "wfc": None,
            "loop": None
        }
        self.update_status_camera("OFF")
        self.update_status_ASM("Not initialized.")
        self.update_status_loop("Not initialized.")

        self._connect_signals()

    def eventFilter(self, obj, event):
        # For clicking frame panels typically used for mechanisms
        if event.type() == QEvent.Type.MouseButtonPress:
            if obj == self.panelMech_Shutter:
                self.on_shutter_clicked()
            elif obj == self.panelMech_Cooler:
                self.on_cooler_clicked()
        return super().eventFilter(obj, event)
    
    def closeEvent(self, event):
        self._cleanup()
        event.accept()
    
    def _cleanup(self):
        print("Shutting down all components and exiting")
        self.log("Good night!", "blue")
        shutdown_all()
    
    def _on_ctrl_c(self, sig, frame):
        self._cleanup()
        sys.exit(0)

    def _connect_signals(self):
        # Connect signals to slots here

        # Top panel buttons
        self.gridPanelButtons_GO_button.clicked.connect(self.on_go_clicked)
        self.gridPanelButtons_STOP_button.clicked.connect(self.on_stop_clicked)
        self.gridPanelButtons_PANIC_button.clicked.connect(self.on_panic_clicked)
        self.gridPanelButtons_LogOut_button.clicked.connect(self.on_logout_clicked)

        # Changing camera tabs
        self.tabControls_AO_Camera.currentChanged.connect(self.on_ao_camera_tab_changed)
        self.cam_last_index = self.tabControls_AO_Camera.currentIndex()

        # IXON controls
        self.gridIXON_itime_entry.setValidator(QDoubleValidator(0.0, 600.0, 5))  # exposure time between 0 and 600 seconds with 5 decimal places
        self.gridIXON_coadd_entry.setValidator(QIntValidator(1, 1000))
        self.gridIXON_itime_entry.returnPressed.connect(self.on_ixon_itime_return_pressed)
        self.gridIXON_coadd_entry.returnPressed.connect(self.on_ixon_coadd_return_pressed)
        self.gridIXON_Array_button.clicked.connect(self.on_ixon_array_clicked)
        self.gridIXON_XYbinning_combo.currentTextChanged.connect(self.on_ixon_xybinning_changed)
        self.gridIXON_ReadOut_combo.currentTextChanged.connect(self.on_ixon_readout_changed)
        self.gridIXON_PreampGain_combo.currentTextChanged.connect(self.on_ixon_preampgain_changed)
        self.gridIXON_VSS_combo.currentTextChanged.connect(self.on_ixon_vss_changed)
        self.gridIXON_ROI_button.clicked.connect(self.on_ixon_roi_clicked)
        
        # SimCam controls
        self.gridSimCam_itime_entry.setValidator(QDoubleValidator(0.0, 30.0, 5)) 
        self.gridSimCam_Amplitude_entry.setValidator(QDoubleValidator(0.0, 100, 2))
        self.gridSimCam_SlopeNoise_entry.setValidator(QDoubleValidator(0.0, 10, 2))
        self.gridSimCam_lag_entry.setValidator(QIntValidator(0, 100))
        self.gridSimCam_itime_entry.returnPressed.connect(self.on_simcam_itime_return_pressed)
        self.gridSimCam_Array_button.clicked.connect(self.on_simcam_array_clicked)
        self.gridSimCam_XYbinning_combo.currentTextChanged.connect(self.on_simcam_xybinning_changed)
        self.gridSimCam_ROI_button.clicked.connect(self.on_simcam_roi_clicked)
        self.gridSimCam_Amplitude_entry.returnPressed.connect(self.on_simcam_amplitude_return_pressed)
        self.gridSimCam_SlopeNoise_entry.returnPressed.connect(self.on_simcam_slope_noise_return_pressed)
        self.gridSimCam_lag_entry.returnPressed.connect(self.on_simcam_lag_return_pressed)

        # AO params
        self.gridLoop_OpenLoop_button.clicked.connect(self.on_open_loop_clicked)
        self.gridLoop_CloseLoop_button.clicked.connect(self.on_close_loop_clicked)

        self.gridLoop_gain_entry.setValidator(QDoubleValidator(0.0, 1.0, 4))
        self.gridLoop_leak_entry.setValidator(QDoubleValidator(0.0, 1.0, 4))
        self.gridLoop_pbgain_entry.setValidator(QDoubleValidator(0.0, 1.0, 4))
        self.gridLoop_pbsoffgain_entry.setValidator(QDoubleValidator(0.0, 1.0, 4))
        self.gridLoop_gain_entry.returnPressed.connect(self.on_gain_return_pressed)
        self.gridLoop_leak_entry.returnPressed.connect(self.on_leak_return_pressed)
        self.gridLoop_pbgain_entry.returnPressed.connect(self.on_pbgain_return_pressed)
        self.gridLoop_pbsoffgain_entry.returnPressed.connect(self.on_pbsoffgain_return_pressed)
        self.gridLoop_NCPA_button.clicked.connect(self.on_ncpa_clicked)

        # Autosave
        self.tabAutosave.currentChanged.connect(self.on_autosave_tab_changed)
        self.gridAutoOn_Path_entry.returnPressed.connect(self.on_autosave_path_return_pressed)
        self.gridAutoOn_dir_filename_entry.returnPressed.connect(self.on_autosave_filename_return_pressed)
        self.gridAutoOn_dir_index_entry.returnPressed.connect(self.on_autosave_index_return_pressed)

        # Mechanism panels
        self.panelMech_Shutter.installEventFilter(self)
        self.panelMech_Cooler.installEventFilter(self)

    # -----------------
    # Top panel buttons
    # -----------------
    def on_go_clicked(self):
        if self.cam_last_index == 0:
            # No camera selected
            self.log("No camera selected", color="orange")
        else:
            self.components["wfs"].run("resume")
            self.log("GO - start acquisition")

    def on_stop_clicked(self):
        if self.cam_last_index == 0:
            # No camera selected
            self.log("No camera selected", color="orange")
        else:
            self.components["wfs"].run("pause")
            self.log("STOP - stop acquisition")

    def on_panic_clicked(self):
        self.log("PANIC! Opening the loop and resetting the system!", color="red")
    
    def on_logout_clicked(self):
        self.log("Shutting down all hardware components and exiting...")

    # -----------------
    # Status panel data
    # -----------------
    def update_status_camera(self, status):
        self.gridStatus_Camera_data.setText(status)
    
    def update_status_ASM(self, status):
        self.gridStatus_ASM_data.setText(status)

    def update_status_loop(self, status):
        self.gridStatus_Loop_data.setText(status)

    # ---------------
    # Camera controls
    # ---------------
    def on_ao_camera_tab_changed(self, index):
        print(f"AO Camera tab changed to index: {index}")
        # Index 0 = OFF, 1 = IXON (Andor), 2 = Simulator

        # First, turn off cameras if switching away from them
        if self.cam_last_index in [1, 2]:
            # Open the loop
            if self.components["wfs"] is not None:
                self.log("Turning off camera. Opening the loop...")
                self.components["wfs"] = None
                
            if self.cam_last_index == 1:
                self.log("Andor OFF")
            if self.cam_last_index == 2:
                try_shutdown(self.components["wfs"])
                self.log("SimCam OFF")
                try_shutdown(self.components["wfc"])
                self.log("DM simulator OFF")

        # Initialize new camera if switching to it
        if index == 1:
            self._start_andor()

        elif index == 2:
            self._start_simcam()
            
        self.cam_last_index = index

    def _start_simcam(self):
        self.log("Initializing SimCam")
        self.components["wfs"] = get_felixsim()
        self.components["wfs"].launch()
        self.components["wfs"].run("pause")  # Start with frames paused
        self.update_status_camera("Awaiting acquisition...")

        if self.components["wfc"] is not None:
            self.log("Shutting down existing DM. You will need to reinitialize it.",
                        color="orange")
            try_shutdown(self.components["wfc"])

        self.log("Initializing DM simulator")
        self.components["wfc"] = get_dmsim()
        get_dmsim().launch()

    def _start_andor(self):
        self.log("Initializing Andor")
        self.log("NOT IMPLEMENTED YET", "red")
        #self.components["wfs"] = get_andor()
        #self.components["wfs"].launch()
        #self.components["wfs"].run("pause")

    # Andor
    def on_ixon_itime_return_pressed(self):
        texpos = float(self.gridIXON_itime_entry.text())
        self.components["wfs"].run("setExposure", texpos)
    
    def on_ixon_coadd_return_pressed(self):
        coadds = int(self.gridIXON_coadd_entry.text())
        self.components["wfs"].run("setCoadds", coadds)

    def on_ixon_array_clicked(self):
        pass

    def on_ixon_xybinning_changed(self):
        binning = self.gridIXON_XYbinning_combo.currentIndex()
        self.log("Resetting shared memories as data size has changed. One moment...", "orange")
        self.components["wfs"].run("setBinning", binning)

    def on_ixon_readout_changed(self):
        pass

    def on_ixon_preampgain_changed(self):
        pass

    def on_ixon_vss_changed(self):
        pass

    def on_ixon_roi_clicked(self):
        pass
    
    # ---------
    # Simulator
    # ---------
    def on_simcam_itime_return_pressed(self):
        texpos = float(self.gridSimCam_itime_entry.text())
        self.components["wfs"].run("setExposure", texpos)

    def on_simcam_array_clicked(self):
        pass

    def on_simcam_xybinning_changed(self):
        binning = self.gridSimCam_XYbinning_combo.currentIndex()
        self.log("Resetting shared memories as data size has changed. One moment...", "orange")
        # Destroy data viewer
        reset_shms()
        # Open data viewer window again
        self.components["wfs"].run("setBinning", binning)

    def on_simcam_roi_clicked(self):
        pass

    def on_simcam_amplitude_return_pressed(self):
        amplitude = float(self.gridSimCam_Amplitude_entry.text())
        self.components["wfs"].run("setAmplitude", amplitude)

    def on_simcam_slope_noise_return_pressed(self):
        slope_noise = float(self.gridSimCam_SlopeNoise_entry.text())
        self.components["wfs"].run("setSlopeNoise", slope_noise)

    def on_simcam_lag_return_pressed(self):
        lag = int(self.gridSimCam_lag_entry.text())
        self.components["wfs"].run("setLag", lag)

    # -----------
    # Loop params
    # -----------
    def on_open_loop_clicked(self):
        pass

    def on_close_loop_clicked(self):
        pass

    def on_gain_return_pressed(self):
        pass
    
    def on_leak_return_pressed(self):
        pass

    def on_pbgain_return_pressed(self):
        pass

    def on_pbsoffgain_return_pressed(self):
        pass

    def on_ncpa_clicked(self):
        pass

    # --------
    # Autosave
    # --------
    def on_autosave_tab_changed(self, index):
        self.log(f"Autosave {'ON' if index == 1 else 'OFF'}")

    def on_autosave_path_return_pressed(self):
        pass

    def on_autosave_filename_return_pressed(self):
        pass

    def on_autosave_index_return_pressed(self):
        pass

    # ----------------
    # Mechanism panels
    # ----------------
    def on_shutter_clicked(self):
        print("Shutter panel clicked")

    def on_cooler_clicked(self):
        print("Cooled panel clicked")

    # -------
    # Console
    # -------

    def log(self, message, color="black"):
        self.panelConsole_display_text.setTextColor(QColor(color))
        self.panelConsole_display_text.append(message)
        self.panelConsole_display_text.setTextColor(QColor("black"))  # reset

        # Trim to MAX_LOG_LINES
        doc = self.panelConsole_display_text.document()
        while doc.blockCount() > MAX_LOG_LINES:
            cursor = QTextCursor(doc.begin())
            cursor.select(QTextCursor.SelectionType.BlockUnderCursor)
            cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock,
                                QTextCursor.MoveMode.KeepAnchor)
            cursor.deleteChar()
            cursor.deleteChar()  # removes newline

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())