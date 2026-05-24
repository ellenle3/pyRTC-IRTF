import sys
import os
import time
import signal
from PyQt6.QtCore import QTimer, QEvent, QThread, pyqtSignal
from PyQt6.QtWidgets import QApplication, QWidget
from PyQt6 import uic
from PyQt6.QtGui import QIntValidator, QDoubleValidator, QColor, QTextCursor, QIcon

from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
#from IRTF.gui.pyrtcgui_setup import Ui_pyrtcGUI
from gui_subwindows import *
from pyroics import ICS_URI_PATH

import Pyro5.api  # to talk to the ICS
from Pyro5.errors import CommunicationError

# Get the directory of the current Python file
BASE_DIR = Path(__file__).parent
IPC_PATH = BASE_DIR / "ipc_files.json"
MAX_LOG_LINES = 100  # max length of console log

def get_ics_proxy():
    # Each thread will need its own proxy for the ICS.
    with open(ICS_URI_PATH) as f:
        uri = f.read().strip()
    try:
        proxy = Pyro5.api.Proxy(uri)
        # Test the connection
        proxy._pyroBind()
    except CommunicationError:
        raise ConnectionError(f"Could not connect to ICS at {uri}. Is the ICS running?")
    
    return Pyro5.api.Proxy(uri)

class MainWindow(QWidget):
    def __init__(self):
        signal.signal(signal.SIGINT, self._on_ctrl_c) # Allow Ctrl-C to quit the app in terminal
        super().__init__()
        uic.loadUi(os.path.join(BASE_DIR, "pyrtc_felix_control_gui.ui"), self)
        # iconpath = "tropius.icns"
        # self.setWindowIcon(QIcon(str(iconpath)))

        self.panelConsole_display_text.setReadOnly(True)          # for console output

        # Connect to the ICS through Pyro
        self.ics = get_ics_proxy()

        # Before launching anything, try shutting down all existing components
        # in case a previous crash.
        # self.update_status_camera("Disconnected")
        # self.update_status_ASM("Disconnected")
        # self.update_status_loop("Disconnected")

        self._connect_signals()

    def eventFilter(self, obj, event):
        # For clicking frame panels typically used for mechanisms
        if event.type() == QEvent.Type.MouseButtonPress:
            if self.is_IXON_enabled:
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
        self.ics.shutdown_all()
    
    def _on_ctrl_c(self, sig, frame):
        self._cleanup()
        sys.exit(0)

    def _connect_signals(self):
        # Connect signals to slots here

        # Top panel buttons
        self.gridPanelButtons_GO_button.clicked.connect(self.on_go_clicked)
        self.gridPanelButtons_STOP_button.clicked.connect(self.on_stop_clicked)
        self.gridPanelButtons_PANIC_button.clicked.connect(self.on_panic_clicked)
        self.gridPanelButtons_ShutDown_button.clicked.connect(self.on_shutdown_clicked)

        # Changing camera tabs
        self.cam_last_index = self.tabControls_AO_Camera.currentIndex()
        self.tabControls_AO_Camera.currentChanged.connect(self.on_ao_camera_tab_changed)
        
        # IXON controls
        self.gridIXON_itime_entry.setValidator(QDoubleValidator(0.0, 600.0, 5))  # exposure time between 0 and 600 seconds with 5 decimal places
        self.gridIXON_coadd_entry.setValidator(QIntValidator(1, 1000))
        self.gridIXON_itime_entry.returnPressed.connect(lambda: self.on_itime_return_pressed(self.gridIXON_itime_entry))
        self.gridIXON_coadd_entry.returnPressed.connect(self.on_ixon_coadd_return_pressed)
        self.gridIXON_Array_button.clicked.connect(self.on_ixon_array_clicked)
        self.gridIXON_XYbinning_combo.currentTextChanged.connect(lambda: self.on_xybinning_changed(self.gridIXON_XYbinning_combo))
        self.gridIXON_ReadOut_combo.currentTextChanged.connect(self.on_ixon_readout_changed)
        self.gridIXON_PreampGain_combo.currentTextChanged.connect(self.on_ixon_preampgain_changed)
        self.gridIXON_VSS_combo.currentTextChanged.connect(self.on_ixon_vss_changed)
        self.gridIXON_ROI_button.clicked.connect(self.on_ixon_roi_clicked)
        
        # SimCam controls
        self.gridSimCam_itime_entry.setValidator(QDoubleValidator(0.0, 30.0, 5)) 
        self.gridSimCam_Amplitude_entry.setValidator(QDoubleValidator(0.0, 100, 2))
        self.gridSimCam_SlopeNoise_entry.setValidator(QDoubleValidator(0.0, 2, 2))
        self.gridSimCam_lag_entry.setValidator(QIntValidator(0, 100))
        self.gridSimCam_itime_entry.returnPressed.connect(lambda: self.on_itime_return_pressed(self.gridSimCam_itime_entry))
        self.gridSimCam_Array_button.clicked.connect(self.on_simcam_array_clicked)
        self.gridSimCam_XYbinning_combo.currentTextChanged.connect(lambda: self.on_xybinning_changed(self.gridSimCam_XYbinning_combo))
        self.gridSimCam_ROI_button.clicked.connect(self.on_simcam_roi_clicked)
        self.gridSimCam_Amplitude_entry.returnPressed.connect(self.on_simcam_amplitude_return_pressed)
        self.gridSimCam_SlopeNoise_entry.returnPressed.connect(self.on_simcam_slope_noise_return_pressed)
        self.gridSimCam_lag_entry.returnPressed.connect(self.on_simcam_lag_return_pressed)

        # AO params
        self.AO_last_index = self.tabLoopParams.currentIndex()
        self.tabLoopParams.currentChanged.connect(self.on_loop_params_tab_changed)
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
        self.gridLoop_imat_button.clicked.connect(self.on_imat_clicked)
        self.gridLoop_pause_radio.toggled.connect(self.on_pause_radio_toggled)

        # Autosave
        self.tabAutosave.currentChanged.connect(self.on_autosave_tab_changed)
        self.gridAutoOn_Path_entry.returnPressed.connect(self.on_autosave_path_return_pressed)
        self.gridAutoOn_dir_filename_entry.returnPressed.connect(self.on_autosave_filename_return_pressed)
        self.gridAutoOn_dir_index_entry.returnPressed.connect(self.on_autosave_index_return_pressed)

        # Mechanism panels
        self.panelMech_Shutter.installEventFilter(self)
        self.panelMech_Cooler.installEventFilter(self)
        # deactivate these panels until we have a camera connected
        self.is_IXON_enabled = False

        # Setup tab
        # self.gridComponents_ASM_init_button.clicked.connect(self._init_ASM)
        # self.gridComponents_ASM_stop_button.clicked.connect(self._stop_ASM)
        # self.gridComponents_slopes_init_button.clicked.connect(self._init_slopes)
        # self.gridComponents_slopes_stop_button.clicked.connect(self._stop_slopes)
        # self.gridComponents_loop_init_button.clicked.connect(self._init_loop)
        # self.gridComponents_loop_stop_button.clicked.connect(self._stop_loop)
        self.kill_button.clicked.connect(self.ics.shutdown_all)

    # -----------------
    # Top panel buttons
    # -----------------
    def on_go_clicked(self):
        if self.cam_last_index == 0:
            # No camera selected
            self.log("No camera selected", color="orange")
        else:
            self.ics.run("wfs", "start")
            self.log("GO - start acquisition")
            self.update_status_camera("Acquisition in progress")

    def on_stop_clicked(self):
        if self.cam_last_index == 0:
            # No camera selected
            self.log("No camera selected", color="orange")
        else:
            self.ics.run("wfs", "stop")
            self.log("STOP - stop acquisition")
            self.update_status_camera("Acquisition paused")
            
    def on_panic_clicked(self):
        self.log("PANIC! Opening the loop and resetting the system!", color="red")
    
    def on_shutdown_clicked(self):
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
        # Index 0 = OFF, 1 = IXON (Andor), 2 = Simulator

        # First, turn off cameras if switching away from them
        if self.cam_last_index in [1, 2]:
            self.update_status_camera("Shutting down")
            # Open the loop
            if self.ics.is_connected("loop"):
                self.log("Opening the loop and pausing.")
                self.ics.run("loop", "setGain", 0)
                self.ics.run("loop", "stop")
                self.update_status_loop("Paused")

            self.ics.shutdown("wfs")
            self.update_status_camera("Disconnected")
                
            if self.cam_last_index == 1:
                self.log("Andor OFF")
                self.is_IXON_enabled = False
                self.ics.shutdown("wfs")
            else:
                self.log("SimCam OFF")
                self.ics.shutdown("wfc")
                self.log("SimASM OFF")
                self.update_status_ASM("Disconnected")
                        
        # Initialize new camera if switching to it
        if index == 1:
            self.worker = IXONInitWorker("IXON", self._start_ixon)
            self.worker.log_signal.connect(self.log)
            self.worker.status_cam_signal.connect(self.update_status_camera)
            self.worker.done.connect(self._enable_window)  # re-enable window when done
            self._disable_window()
            self.worker.start()

        elif index == 2:
            self.worker = SimCamInitWorker("SimCam")
            self.worker.log_signal.connect(self.log)
            self.worker.status_cam_signal.connect(self.update_status_camera)
            self.worker.status_ASM_signal.connect(self.update_status_ASM)
            self.worker.done.connect(self._enable_window)  # re-enable window when done
            self._disable_window()
            self.worker.start()
            
        self.cam_last_index = index

    def _disable_window(self):
        self.setEnabled(False)
        self.gridPanelButtons_PANIC_button.setEnabled(True)  # Emergency open loop always available

    def _enable_window(self):
        self.setEnabled(True)

    # Shared functions

    def on_itime_return_pressed(self, entry):
        texpos = float(entry.text())
        self.ics.run("wfs", "setExposure", texpos)
        self.log("itime " + str(texpos))

    def on_xybinning_changed(self, combo):
        binning = combo.currentIndex()
        self.log("Resetting shared memories as data size has changed. One moment...", "orange")
        # Destroy data viewer
        #reset_shms()
        # Open data viewer window again
        #self.ics.run("wfs", "setBinning", binning)

    # IXON
    def _start_ixon(self):
        self.ics.launch("wfs", "AndorWFS")
        self.ics.run("wfs", "stop")

        # Initialize readout options
        capabilities = self.ics.run("wfs", "getCapabilities")
    
        # Make the capabilities list with the same convention as the Felix XUI:
        # amplifier_channel_hsspeed
        print(capabilities)
        print(capabilities["AmpModes"])
        cvidx = capabilities["AmpModes"].index("Conventional")

        self.IXON_ReadOut_Options = {}
        self.gridIXON_ReadOut_combo.clear()
        for hi, hsspeed in enumerate(capabilities["HSSpeeds"]):
            hsspeed_str = str( int(hsspeed) ).zfill(2)
            key = f"CV_16bit_{hsspeed_str}MHz"
            self.IXON_ReadOut_Options[key] = {
                "hi": hi,
                "ADChannel": 0, # 16 bit
                "amplifier": cvidx # only use CV
            }
            self.gridIXON_ReadOut_combo.addItem([key])

        self.IXON_VSSpeed_Options = {}
        self.gridIXON_VSS_combo.clear()
        for vi, vsspeed in enumerate(capabilities["VSSpeeds"]):
            vsspeed_str = str( int(vsspeed*1000) )
            key = f"{vsspeed_str}ns"
            self.IXON_VSSpeed_Options[key] = {
                "vi": vi
            }
            self.gridIXON_VSS_combo.addItem(key)

        # Set to default values
        # default_readout = "CV_16bit_17MHz"
        # default_vss = "500ns"

        # self.gridIXON_ReadOut_combo.setCurrentText(default_readout)
        # self.gridIXON_VSS_combo.setCurrentText(default_vss)

        self.is_IXON_enabled = True

    def on_ixon_coadd_return_pressed(self):
        coadds = int(self.gridIXON_coadd_entry.text())
        self.ics.run("wfs", "setCoadds", coadds)
        self.log("coadds " + str(coadds))

    def on_ixon_array_clicked(self):
        pass

    def on_ixon_readout_changed(self):
        key = self.gridIXON_ReadOut_combo.currentText()
        options = self.IXON_ReadOut_Options[key]
        self.ics.run("wfs", "setReadout", options["hi"], None, options["ADChannel"], options["amplifier"])
        self.log("Readout mode " + key)

    def on_ixon_preampgain_changed(self):
        pass

    def on_ixon_vss_changed(self):
        key = self.gridIXON_VSS_combo.currentText()
        options = self.IXON_VSSpeed_Options[key]
        self.ics.run("wfs", "setVSSpeed", options["vi"])
        self.log("Vertical shift speed " + key)

    def on_ixon_roi_clicked(self):
        pass
    
    # SimCam
    def on_simcam_array_clicked(self):
        pass

    def on_simcam_roi_clicked(self):
        pass

    def on_simcam_amplitude_return_pressed(self):
        amplitude = float(self.gridSimCam_Amplitude_entry.text())
        self.ics.run("wfs", "setAmplitude", amplitude)
        self.log("Amplitude " + str(amplitude))

    def on_simcam_slope_noise_return_pressed(self):
        slope_noise = float(self.gridSimCam_SlopeNoise_entry.text())
        self.ics.run("wfs", "setSlopeNoise", slope_noise)
        self.log("Slope noise " + str(slope_noise))

    def on_simcam_lag_return_pressed(self):
        lag = int(self.gridSimCam_lag_entry.text())
        self.ics.run("wfs", "setLag", lag)
        self.log("Lag " + str(lag))

    def reset_wfs_shm_only(self):
        # Pause the WFS camera

        # Reset WFS component and relaunch the SHM
        
        # Reset Slopes process
        
        # If loop exists, reset only the wfsInfo component
        pass

    # -----------
    # Loop params
    # -----------
    def on_loop_params_tab_changed(self, index):
        # Index 0 = Off, 1 = Basic, 2 = Expert

        # Turn off AO
        if index == 0:
            self.update_status_loop("Shutting down")

            if self.ics.is_connected("loop"):
                self.log("Opening the loop")
                self.ics.run("loop", "setGain", 0)
                self.ics.shutdown("loop")
                self.log("Loop OFF")
            else:
                self.log("Loop is already disconnected...?", "orange")

            if self.ics.is_connected("slopes"):
                self.ics.shutdown("slopes")
                self.log("Slopes OFF")
            else:
                self.log("Slopes is already disconnected...?", "orange")

            if self.cam_last_index != 2:  # check if not simulator
                if self.ics.is_connected("wfc"):
                    self.log("Flattening the ASM.")
                    self.ics.run("wfc", "flatten")
                    self.ics.shutdown("wfc")
                    self.log("ASM OFF")
                    self.update_status_ASM("Disconnected")
                else:
                    self.log("ASM is already disconnected...?", "orange")

            if self.ics.is_connected("tel"):
                self.ics.shutdown("tel")
                self.log("Telemetry stream OFF")
            else:
                self.log("Telemetry is already disconnected...?", "orange")

            self.update_status_loop("Disconnected")
                            
        # Turn on AO if it was off before
        elif index in [1, 2] and self.AO_last_index == 0:
            if not self.ics.is_connected("wfs"):
                self.log("Please select a camera before starting the loop.", color="red")
                self.tabLoopParams.setCurrentIndex(0)  # switch back to Off tab
                return
            self.worker = LoopInitWorker("Loop")
            self.worker.log_signal.connect(self.log)
            self.worker.status_ASM_signal.connect(self.update_status_ASM)
            self.worker.status_loop_signal.connect(self.update_status_loop)
            self.worker.done.connect(self._enable_window)  # re-enable window when done
            self._disable_window()
            self.worker.start()

        self.AO_last_index = index

    def on_open_loop_clicked(self):
        self.ics.run("loop", "setGain", 0)
        self.ics.run("loop", "leakyGain", 0.99)
        self.log("open loop")

    def on_close_loop_clicked(self):
        self.ics.run("loop", "setGain", 0.15)
        self.ics.run("loop", "leakyGain", 1.0)
        self.log("close loop")

    def on_gain_return_pressed(self):
        gain = float(self.gridLoop_gain_entry.text())
        self.ics.run("loop", "setGain", gain)
        self.log("gain " + str(gain))

    def on_leak_return_pressed(self):
        leak = float(self.gridLoop_leak_entry.text())
        self.ics.run("loop", "leakyGain", 1-leak)
        self.log("leak " + str(leak))

    def on_pbgain_return_pressed(self):
        pbgain = float(self.gridLoop_pbgain_entry.text())
        self.ics.run("loop", "pbgain", pbgain)
        self.log("pbgain " + str(pbgain))

    def on_pbsoffgain_return_pressed(self):
        self.log("pbsoff not implemented yet", "red")

    def on_ncpa_clicked(self):
        pass

    def on_imat_clicked(self):
        pass

    def on_pause_radio_toggled(self, checked):
        if checked:
            # In case we want to pause the loop without stopping the camera...
            self.ics.run("loop", "stop")
            self.log("Loop paused.")
            self.update_status_loop("Paused")
        else:
            self.ics.run("loop", "start")
            self.log("Loop resumed.")
            self.update_status_loop("Running")

    # --------
    # Autosave
    # --------
    def on_autosave_tab_changed(self, index):
        if index == 1:
            if not self.ics.is_connected("tel"):
                self.log("Telemetry stream is not running. Please start the loop first.", "red")
                self.tabAutosave.setCurrentIndex(0)  # switch back to Off tab
                return

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
        window = IXONControlsWindow(ics=self.ics, start_tab=0, parent=self)
        window.show()

    def on_cooler_clicked(self):
        window = IXONControlsWindow(ics=self.ics, start_tab=1, parent=self)
        window.show()

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


class IXONInitWorker(QThread):
    log_signal = pyqtSignal(str, str)
    status_cam_signal = pyqtSignal(str)
    done = pyqtSignal(str)  # pass back name so caller knows which finished

    def __init__(self, name, init_function, log=None):
        super().__init__()
        self.name = name
        self.init_function = init_function
        self.log = log

    def run(self):
        self.status_cam_signal.emit("Initializing IXON")
        self.log_signal.emit("Connecting to Andor camera...", "blue")
        self.init_function()
        self.status_cam_signal.emit("Ready for acquisition")
        self.done.emit(self.name)

class SimCamInitWorker(QThread):
    log_signal = pyqtSignal(str, str)
    status_cam_signal = pyqtSignal(str)
    status_ASM_signal = pyqtSignal(str)
    done = pyqtSignal(str)  # pass back name so caller knows which finished

    def __init__(self, name, log=None):
        super().__init__()
        self.name = name
        self.log = log

    def run(self):
        ics = get_ics_proxy()  # New proxy has to go in the run thread, not main

        # Simulated ASM first since SimCam depends on ASM slope shared memory to
        # inject a fake signal into the simulator.
        self.status_ASM_signal.emit("Initializing SimASM")
        self.log_signal.emit("Connecting to ASM simulator...", "blue")

        if ics.is_connected("wfc"):
            self.log_signal.emit("Stopping the ASM. You will need to re-initialize the hardware.", "red")
            ics.shutdown("wfc")
        
        ics.launch("wfc", "DMsim")
        self.status_ASM_signal.emit("SimASM connected")
        
        # SimCam (simulated Felix)
        self.status_cam_signal.emit("Initializing SimCam")
        self.log_signal.emit("Connecting to Felix simulator...", "blue")
        ics.launch("wfs", "FELIXsim")
        ics.run("wfs", "stop")
        self.status_cam_signal.emit("Ready for acquisition")

        self.done.emit(self.name)

class LoopInitWorker(QThread):
    # Class to launch DM, slopes, and loop processes.
    log_signal = pyqtSignal(str, str)
    status_ASM_signal = pyqtSignal(str)
    status_loop_signal = pyqtSignal(str)
    done = pyqtSignal(str)  # pass back name so caller knows which finished

    def __init__(self, name):
        super().__init__()
        self.name = name

    def run(self):
        ics = get_ics_proxy()  # New proxy has to go in the run thread, not main

        # Start the ASM first, but skip if the simulator is running.
        if not ics.is_connected("wfc"):
            self.status_ASM_signal.emit("Initializing IRTF-ASM-1")
            self.log_signal.emit("Connecting to the ASM. Please wait...", "blue")

            ics.launch("wfc", "ImakaDM")
            ics.run("wfc", "start")
            self.status_ASM_signal.emit("IRTF-ASM-1 connected")        

        # Next is the slopes process, which will calculate the slopes based
        # on the camera data.
        self.status_loop_signal.emit("Initializing")
        self.log_signal.emit("Starting slopes process...", "blue")
        ics.launch("slopes", "SlopesProcess")
        ics.run("slopes", "start")

        # AO loop process comes at the end since it needs the shared memories of
        # the other components.
        self.log_signal.emit("Starting loop process...", "blue")
        ics.launch("loop", "Loop")
        ics.run("loop", "setGain", 0)  # Always start with loop open
        ics.run("loop", "start")

        # Also plug in the telemetry stream
        ics.launch("tel", "ImakaTelemetry")
        ics.run("tel", "start")

        self.status_loop_signal.emit("Running")
        self.done.emit(self.name)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())