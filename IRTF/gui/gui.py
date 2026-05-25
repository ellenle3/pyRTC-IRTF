import sys
import os
import signal
from PyQt6.QtCore import QTimer, QEvent, QThread, pyqtSignal
from PyQt6.QtWidgets import QApplication, QWidget
from PyQt6 import uic
from PyQt6.QtGui import QIntValidator, QDoubleValidator, QColor, QTextCursor, QIcon

from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
#from IRTF.gui.pyrtcgui_setup import Ui_pyrtcGUI
from subwindows import *
from workers import *

# Get the directory of the current Python file
BASE_DIR = Path(__file__).parent
IPC_PATH = BASE_DIR / "ipc_files.json"
MAX_LOG_LINES = 100  # max length of console log

# hard coded to work with FELIX camera (and other IRTF Andor cameras)
# see the method AndorWFS.showAvailableReadout(), which provides this dict
ANDOR_CAPABILITIES = { 
            'HSSpeeds': [17.0, 10.0, 5.0, 1.0],
            'VSSpeeds': [0.3, 0.5, 0.9, 1.7, 3.3],
            'VSSpeedRecommended': {'index': 4, 'speed': 3.3},
            'AmpModes': ['ElectronMultiplying', 'Conventional']
        }

# PROBABLY RESET SHMS ON STARTUP UNLESS DISABLED IN GUI CONFIG
# GUI CONFIG SHOULD ALSO STORE DEFAULTS, AND OPTIONS LIKE "SHUTDOWN ON QUIT"
# TO PERSIST ACROSS SESSIONS.

class MainWindow(QWidget):
    def __init__(self):
        signal.signal(signal.SIGINT, self._on_ctrl_c) # Allow Ctrl-C to quit the app in terminal
        super().__init__()
        uic.loadUi(os.path.join(BASE_DIR, "pyrtc_felix_control.ui"), self)
        # iconpath = "tropius.icns"
        # self.setWindowIcon(QIcon(str(iconpath)))

        self.panelConsole_display_text.setReadOnly(True)          # for console output

        # Connect to the ICS through Pyro
        self.pyro_worker = PyroQueueWorker()
        self.pyro_worker.start()
        self.ics = AsyncICSProxy(self)

        self.is_shutdown_on_close = False

        # Before launching anything, try shutting down all existing components
        # in case a previous crash.
        # self.update_status_camera("Disconnected")
        # self.update_status_ASM("Disconnected")
        # self.update_status_loop("Disconnected")

        self.ao_cals = {
            "imat": {
                "theor_file": None,
                "synth_file": None,
                "method": None,
                "pokeAmp": None,
                "numItersIM": None
            },
            "ncpa": {
                "ra_target": None,
                "dec_target": None,
                "ra_guide": None,
                "dec_guide": None,
                "auto_offsets": [0, 0, 0, 0, 0, 0, 0],
                "user_offsets": [0, 0, 0, 0, 0, 0, 0]
            }

        }
        self.old_array_input = None  # Store the last ROI in case the camera was toggled on and off

        self._connect_signals()
        self.tabControls_AO_Camera.setCurrentIndex(0)  # start with everything off
        self.tabLoopParams.setCurrentIndex(0)
    
    def call_ics(self, fn, callback=None, error_callback=None):
        """Funnel all macro requests straight into the secure background thread queue."""
        return self.pyro_worker.submit_blocking_task(fn)

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
        self.log("Good night!", "blue")

        print("Shutting down all components and exiting")
        self.reset_SHMs()
    
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
        self.gridIXON_Array_button.clicked.connect(lambda: self.on_array_clicked(self.gridIXON_Array_entry))
        self.gridIXON_XYbinning_combo.currentTextChanged.connect(lambda: self.on_xybinning_changed(self.gridIXON_XYbinning_combo))
        self.gridIXON_ReadOut_combo.currentTextChanged.connect(self.on_ixon_readout_changed)
        self.gridIXON_PreampGain_combo.currentTextChanged.connect(self.on_ixon_preampgain_changed)
        self.gridIXON_VSS_combo.currentTextChanged.connect(self.on_ixon_vss_changed)
        #self.gridIXON_ROI_button.clicked.connect(self.on_ixon_roi_clicked)
        self.gridIXON_dark_button.clicked.connect(self.on_dark_clicked)
        
        # SimCam controls
        self.gridSimCam_itime_entry.setValidator(QDoubleValidator(0.0, 30.0, 5)) 
        self.gridSimCam_Amplitude_entry.setValidator(QDoubleValidator(0.0, 100, 2))
        self.gridSimCam_SlopeNoise_entry.setValidator(QDoubleValidator(0.0, 2, 2))
        self.gridSimCam_lag_entry.setValidator(QIntValidator(0, 100))
        self.gridSimCam_itime_entry.returnPressed.connect(lambda: self.on_itime_return_pressed(self.gridSimCam_itime_entry))
        self.gridSimCam_Array_button.clicked.connect(lambda: self.on_array_clicked(self.gridSimCam_Array_entry))
        self.gridSimCam_XYbinning_combo.currentTextChanged.connect(lambda: self.on_xybinning_changed(self.gridSimCam_XYbinning_combo))
        #self.gridSimCam_ROI_button.clicked.connect(self.on_simcam_roi_clicked)
        self.gridSimCam_Amplitude_entry.returnPressed.connect(self.on_simcam_amplitude_return_pressed)
        self.gridSimCam_SlopeNoise_entry.returnPressed.connect(self.on_simcam_slope_noise_return_pressed)
        self.gridSimCam_lag_entry.returnPressed.connect(self.on_simcam_lag_return_pressed)
        self.gridSimCam_dark_button.clicked.connect(self.on_dark_clicked)

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
        self.resetSHMs_button.clicked.connect(self.reset_SHMs)
        self.shutdownOnClose_radio.toggled.connect(self.on_shutdown_on_close_toggled)

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
        # Add function to ICS to abort everything and open the loop immediately...?
        # how to implement htis
        if self.ics.is_connected("loop"):
            self.ics.run("loop", "setGain", 0)
            self.ics.run("loop", "stop")
        else:
            self.log("Loop is not running...?", "orange")
        if self.ics.is_connected("wfc"):
            self.ics.run("wfc", "flatten")
        if self.ics.is_connected("wfs"):
            self.ics.run("wfs", "stop")
    
    def on_shutdown_clicked(self):
        self.log("Shutting down all hardware components")
        self.ics.shutdown_all()

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

            # Reset WFS SHMs to prevent issues if the ROI is changed to a different
            # default size upon startup
            self.log("Clearing WFS shared memories")
            self.ics.reset_wfs_shms()

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
            # Check if Andor SDK is installed
            try:
                import pyAndorSDK2
            except ImportError:
                self.log("Andor SDK not found.", "red")
                self.tabControls_AO_Camera.setCurrentIndex(0)  # switch back to OFF tab
                return
            self.worker = IXONInitWorker("IXON", self._set_ixon_defaults)
            self.worker.log_signal.connect(self.log)
            self.worker.status_cam_signal.connect(self.update_status_camera)
            self.worker.done.connect(self._set_ixon_defaults_and_enable)  # re-enable window when done
            self._disable_window()
            self.worker.start()

        elif index == 2:
            self.worker = SimCamInitWorker("SimCam", self._set_simcam_defaults)
            self.worker.log_signal.connect(self.log)
            self.worker.status_cam_signal.connect(self.update_status_camera)
            self.worker.status_ASM_signal.connect(self.update_status_ASM)
            self.worker.done.connect(self._set_simcam_defaults_and_enable) # re-enable window when done
            self._disable_window()
            self.worker.start()
            
        self.cam_last_index = index

    def _disable_window(self):
        self.setEnabled(False)
        self.gridPanelButtons_PANIC_button.setEnabled(True)  # Emergency open loop always available

    def _set_ixon_defaults_and_enable(self):
        # changes to the GUI must happen in the main thread to avoid seg fault,
        # so wait until afte the worker is done to set options and defaults
        self._set_ixon_capabilities()
        self._set_ixon_defaults()
        self.is_IXON_enabled = True
        self.setEnabled(True)
    
    def _set_simcam_defaults_and_enable(self):
        self._set_simcam_defaults()
        self.setEnabled(True)

    # Shared functions

    def on_itime_return_pressed(self, entry):
        texpos = float(entry.text())
        self.ics.run("wfs", "setExposure", texpos)
        self.log("itime " + str(texpos))

    def on_array_clicked(self, entry):
        values = [int(x) for x in entry.text().split()]
        if len(values) != 4:
            self.log("ROI must be defined by 4 integers: width, height, left, top", color="red")
            return
        width, height, left, top = values
        if width <= 0 or height <= 0:
            self.log("Width and height must be positive integers", color="red")
            return
        self.log("Resetting shared memories as data size has changed. One moment...", "orange")
        ret = self.ics.run("wfs", "setRoi", (width, height, left, top))
        if ret == -1:
            self.log("Error setting ROI. Please check the values and try again.", color="red")
        else:
            self.old_array_input = entry.text()  # to recycle if the camera is turned on and off
            self.log("ROI set to " + entry.text())

    def on_xybinning_changed(self, combo):
        binning = int(combo.currentText())
        self.log("Resetting shared memories as data size has changed. One moment...", "orange")
        self.ics.run("wfs", "setBinning", binning)

    def on_dark_clicked(self):
        self.log("Taking dark")
        self.ics.run("wfs", "takeDark")

    # IXON    
    def _set_ixon_capabilities(self):
        # Make the read out capabilities list with the same convention as the Felix
        # XUI: amplifier_channel_hsspeed
        cvidx = ANDOR_CAPABILITIES["AmpModes"].index("Conventional")

        self.IXON_ReadOut_Options = {}
        self.gridIXON_ReadOut_combo.clear()
        for hi, hsspeed in enumerate(ANDOR_CAPABILITIES["HSSpeeds"]):
            hsspeed_str = str( int(hsspeed) ).zfill(2)
            key = f"CV_16bit_{hsspeed_str}MHz"
            self.IXON_ReadOut_Options[key] = {
                "hi": hi,
                "ADChannel": 0, # 16 bit
                "amplifier": cvidx # only use CV
            }
            self.gridIXON_ReadOut_combo.addItem(key)

        self.IXON_VSSpeed_Options = {}
        self.gridIXON_VSS_combo.clear()
        for vi, vsspeed in enumerate(ANDOR_CAPABILITIES["VSSpeeds"]):
            vsspeed_str = str( int(vsspeed*1000) )
            key = f"{vsspeed_str}ns"
            self.IXON_VSSpeed_Options[key] = {
                "vi": vi
            }
            self.gridIXON_VSS_combo.addItem(key)

        # Not implemented - set to 1 option
        self.gridIXON_PreampGain_combo.addItem("1")

    def _set_ixon_defaults(self):
        self.gridIXON_itime_entry.setText("1.0")
        self.on_itime_return_pressed(self.gridIXON_itime_entry)
        self.gridIXON_coadd_entry.setText("1")
        self.on_ixon_coadd_return_pressed()
        if self.old_array_input is not None:
            array_input = self.old_array_input
        else:
            array_input = "512 512 1 1"
        self.gridIXON_Array_entry.setText(array_input)
        self.on_array_clicked(self.gridIXON_Array_entry)
        self.gridIXON_XYbinning_combo.setCurrentIndex(0)  # set to 1
        self.on_xybinning_changed(self.gridIXON_XYbinning_combo)
        self.gridIXON_ReadOut_combo.setCurrentIndex(0)  # 17 MHz CV 16 bit
        self.on_ixon_readout_changed()
        self.gridIXON_PreampGain_combo.setCurrentIndex(0)  # set to 1
        self.on_ixon_preampgain_changed()
        self.gridIXON_VSS_combo.setCurrentIndex(1)  # set to 500 ns
        self.on_ixon_vss_changed()

    def on_ixon_coadd_return_pressed(self):
        coadds = int(self.gridIXON_coadd_entry.text())
        self.ics.set("wfs", "coadds", coadds)
        self.log("coadds " + str(coadds))

    def on_ixon_readout_changed(self):
        key = self.gridIXON_ReadOut_combo.currentText()
        options = self.IXON_ReadOut_Options[key]
        self.ics.run("wfs", "setReadout", options["hi"], None, options["ADChannel"], options["amplifier"])
        self.log("Readout mode " + key)

    def on_ixon_preampgain_changed(self):
        self.log("Preamp gain not implemented yet. (sorry)", "gray")

    def on_ixon_vss_changed(self):
        key = self.gridIXON_VSS_combo.currentText()
        vi = self.IXON_VSSpeed_Options[key]["vi"]
        self.ics.run("wfs", "setVSSpeed", vi)
        self.log("Vertical shift speed " + key)
    
    # SimCam
    def _set_simcam_defaults(self):
        self.gridSimCam_itime_entry.setText("0.005")
        self.on_itime_return_pressed(self.gridSimCam_itime_entry)
        if self.old_array_input is not None:
            array_input = self.old_array_input
        else:
            array_input = "512 512 0 0"
        self.gridSimCam_Array_entry.setText(array_input)
        self.on_array_clicked(self.gridSimCam_Array_entry)
        self.gridSimCam_XYbinning_combo.setCurrentIndex(0)  # set to 1
        self.on_xybinning_changed(self.gridSimCam_XYbinning_combo)
        self.gridSimCam_Amplitude_entry.setText("30.0")
        self.on_simcam_amplitude_return_pressed()
        self.gridSimCam_SlopeNoise_entry.setText("0.0")
        self.on_simcam_slope_noise_return_pressed()
        self.gridSimCam_lag_entry.setText("0")
        self.on_simcam_lag_return_pressed()
        
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
        self.ics.set("loop", "leakyGain", 0.01)
        self.log("open loop")

    def on_close_loop_clicked(self):
        self.ics.run("loop", "setGain", 0.15)
        self.ics.set("loop", "leakyGain", 0.0)
        self.log("close loop")

    def on_gain_return_pressed(self):
        gain = float(self.gridLoop_gain_entry.text())
        self.ics.run("loop", "setGain", gain)
        self.log("gain " + str(gain))

    def on_leak_return_pressed(self):
        leak = float(self.gridLoop_leak_entry.text())
        self.ics.set("loop", "leakyGain", 1-leak)
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
        window = IXONControlsWindow(start_tab=0, parent=self)
        window.show()

    def on_cooler_clicked(self):
        window = IXONControlsWindow(start_tab=1, parent=self)
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

    # ---------
    # Setup tab
    # ---------
    def reset_SHMs(self):
        self.log("Shutting down all components and resetting SHMs.", "orange")
        self.ics.shutdown_all()
        self.ics.reset_shms()
        # switch tabs back to off
        self.tabControls_AO_Camera.setCurrentIndex(0)
        self.tabLoopParams.setCurrentIndex(0)
    
    def on_shutdown_on_close_toggled(self, checked):
        self.is_shutdown_on_close = checked
        self.log(f"Shutdown on close {'enabled' if checked else 'disabled'}")

    
def cleanup():
    app.quit()

if __name__ == "__main__":
    app = QApplication(sys.argv)

    # Let Python process signals every second - allows ctrl C to kill
    timer = QTimer()
    timer.start(1000)
    timer.timeout.connect(lambda: None)

    signal.signal(signal.SIGINT, lambda *_: app.quit())

    window = MainWindow()
    window.show()
    sys.exit(app.exec())