# main.py
import sys
import os
import signal
import numpy as np
from PyQt6 import uic
from PyQt6.QtWidgets import QApplication, QWidget, QMessageBox
from PyQt6.QtCore import QTimer, QEvent, QThread, pyqtSignal
from PyQt6.QtGui import QIntValidator, QDoubleValidator, QColor, QTextCursor, QIcon
from workers import *
from mplfeliximage import MplFelixImage  

sys.path.append('..')
import scripts as sc
from pyRTC import clear_shms

# hard coded to work with FELIX camera (and other IRTF Andor cameras)
# see the method AndorWFS.showAvailableReadout(), which provides this dict
ANDOR_CAPABILITIES = { 
            'HSSpeeds': [17.0, 10.0, 5.0, 1.0],
            'VSSpeeds': [0.3, 0.5, 0.9, 1.7, 3.3],
            'VSSpeedRecommended': {'index': 4, 'speed': 3.3},
            'AmpModes': ['ElectronMultiplying', 'Conventional']
        }
MAX_LOG_LINES = 100  # max length of console log

class MainWindow(QWidget):

    def __init__(self):
        super().__init__()

        uic.loadUi("simplegui.ui", self)
        # Connect to the ICS through Pyro
        self.pyro_worker_ics = PyroQueueWorker(proxy_type="ics")
        self.pyro_worker_ics.start()
        self.ics = AsyncICSProxy(self)
        self.pyro_worker_overseer = PyroQueueWorker(proxy_type="overseer")
        self.pyro_worker_overseer.start()
        self.overseer = AsyncOverseerProxy(self)

        self.textEditMsg.setReadOnly(True)
        self._connect_signals()
        self.update_status("STOPPED", "red")
        self.disable_controls()
    
    def disable_controls(self):
        self.containerInteract.setEnabled(False)

    def enable_controls(self):
        self.containerInteract.setEnabled(True)

    def call_ics(self, fn, callback=None, error_callback=None):
        """Funnel all macro requests straight into the secure background thread queue."""
        return self.pyro_worker_ics.submit_blocking_task(fn)

    def call_overseer(self, fn, callback=None, error_callback=None):
        """Funnel all macro requests straight into the secure background thread queue."""
        return self.pyro_worker_overseer.submit_blocking_task(fn)

    def _connect_signals(self):
        self.buttonGo.clicked.connect(self.on_go_clicked)
        self.buttonSync.clicked.connect(self.on_sync_clicked)
        self.buttonStop.clicked.connect(self.on_stop_clicked)
        self.buttonPause.clicked.connect(self.on_pause_clicked)
        self.buttonItimeAuto.clicked.connect(self.set_exposure_active_optics)
        self.mplFelixImage.coords_clicked.connect(self.on_image_clicked)
        self.checkGuide.toggled.connect(self.on_guide_toggled)
        self.checkASMFreeze.toggled.connect(self.on_asm_freeze_toggled)
        self.buttonASMFlatten.clicked.connect(self.on_asm_flatten_clicked)
        self.buttonClearSHMs.clicked.connect(self.on_clear_shms_clicked)
    
        coadds_validator = QIntValidator(1, 100, self)
        self.entryCoadds.setValidator(coadds_validator)
        itime_validator = QDoubleValidator(0.001, 1000.0, 3, self)
        itime_validator.setNotation(QDoubleValidator.Notation.StandardNotation)
        self.entryItime.setValidator(itime_validator)
        self.entryCoadds.returnPressed.connect(lambda: self.on_coadds_return_pressed(self.entryCoadds))
        self.entryItime.returnPressed.connect(lambda: self.on_itime_return_pressed(self.entryItime))

    def log(self, message, color="black"):
        self.textEditMsg.setTextColor(QColor(color))
        self.textEditMsg.append(message)
        self.textEditMsg.setTextColor(QColor("black"))  # reset

        # Trim to MAX_LOG_LINES
        doc = self.textEditMsg.document()
        while doc.blockCount() > MAX_LOG_LINES:
            cursor = QTextCursor(doc.begin())
            cursor.select(QTextCursor.SelectionType.BlockUnderCursor)
            cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock,
                                QTextCursor.MoveMode.KeepAnchor)
            cursor.deleteChar()
            cursor.deleteChar()  # removes newline

    def update_status(self, status, color):
        self.labelStatusMsg.setText(status)
        self.labelStatusMsg.setStyleSheet(f"color: {color}; font-weight: bold;")
            
    def on_itime_return_pressed(self, entry):
        itime = float(entry.text())
        self.ics.run("wfs", "setExposure", itime)
        self.log(f"Set itime to {itime:.2f} seconds.")

    def on_coadds_return_pressed(self, entry):
        coadds = int(entry.text())
        self.ics.set("wfs", "coadds", coadds)
        self.log(f"Set coadds to {coadds}.")

    def on_image_clicked(self, x, y):
        if not self.ics.is_connected("slopes"):
            self.log("Slopes process not running. Will not set masks.")
            return
        if self.ics.is_closed_loop():
            self.log("Loop is closed. Will not set masks.")
            return
        x = int(x)
        y = int(y)
        self.log(f"Setting masks: {x}, {y}")
        self.ics.run("slopes", "makeSubApMasks", -y, x)

    def on_sync_clicked(self):
        self.update_status("Syncing...", "blue")
        if self.ics.is_connected("wfs"):
            self.log("Already connected to Andor")
            self.launch_remaining_components()
        else:
            self.log("Starting camera")
            # init_simcam() disables controls and connects self.worker.done to self._enable_camera
            self.init_simcam()


    def on_go_clicked(self):
        sc.set_focus_reference()  # update base focus value
        self.ics.close_loop()
        self.overseer.enable_guidebox_offset_check()
        self.log("Closing the loop")
        self.update_status("Running", "green")

    def on_stop_clicked(self):
        self.overseer.disable_guidebox_offset_check()
        self.ics.stop_all()
        self.ics.run("wfc", "flatten")
        time.sleep(0.5)
        self.ics.shutdown_all()
        self.log("Quitting all components and relinquishing Andor")
        self.update_status("STOPPED", "red")
        self.disable_controls()

    def on_pause_clicked(self):
        self.ics.open_loop()
        self.ics.run("loop", "stop")
        self.overseer.disable_guidebox_offset_check()
        self.update_status("LOOP PAUSED. Acquiring images...", "orange")
        self.log("Pausing the loop. ASM will not be updated.")

    def on_guide_toggled(self, checked):
        if checked:
            self.ics.run("loop", "enableTipTilt", True)
        else:
            self.ics.run("loop", "enableTipTilt", False)

    def on_asm_freeze_toggled(self, checked):
        if checked:
            self.ics.run("wfc", "stop")
            self.log("Freezing the ASM")
        else:
            self.ics.run("wfc", "start")
            self.log("Unfreezing the ASM")
            self.update_status("Running", "green")

    def on_asm_flatten_clicked(self):
        self.ics.run("wfc", "flatten")
        self.log("Flattening the ASM")

    def on_clear_shms_clicked(self):
        dialog = QMessageBox(self)
        dialog.setWindowTitle("Clear Shared Memories")
        dialog.setText("Clearing shared memories will reset the system. Proceed?")
        dialog.setIcon(QMessageBox.Icon.Warning)
        
        dialog.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        dialog.setDefaultButton(QMessageBox.StandardButton.No)

        result = dialog.exec()

        if result == QMessageBox.StandardButton.Yes:
            self.log("Resetting SHMs and resetting")
            self.ics.run("wfs", "stop")
            self.ics.run("loop", "stop")
            self.mplFelixImage.reset_widget_and_clear_shm()
            self.on_stop_clicked()  # stop all processes

    # Andor camera helpers
    def init_andor(self):
        # Check if Andor SDK is installed
        try:
            import pyAndorSDK2
        except ImportError:
            self.log("Andor SDK not found", "red")
            self.update_status("STOPPED", "red")
            return

        # changes to the GUI must happen in the main thread to avoid seg fault,
        # so wait until after the worker is done to set options and defaults
        self.worker = IXONInitWorker("IXON")
        self.worker.log_signal.connect(self.log)
        self.worker.status_cam_signal.connect(self.update_status)
        self.worker.done.connect(self._enable_camera)  # re-enable window when done
        self.disable_controls()
        self.worker.start()

    def init_simcam(self):
        self.worker = SimCamInitWorker("SimCam")
        self.worker.log_signal.connect(self.log)
        self.worker.done.connect(self._enable_camera)  # re-enable window when done
        self.disable_controls()
        self.worker.start()

    def _enable_camera(self):
        if not self.ics.is_connected("wfs"):
            # Failed to init.
            self.log("Failed to start camera", "red")
            self.on_stop_clicked()
            self.update_status("STOPPED", "red")
            self.disable_controls()
            return

        self.set_exposure_active_optics()
        self.update_status("Ready! Acquiring images...", "orange")
        self.enable_controls()
        self.set_exposure_active_optics()
        self.launch_remaining_components()

    def launch_remaining_components(self):
        if self.ics.is_connected("slopes"):
            self.log("Already connected to slopes")
        else:
            self.log("Starting slopes")
            self.ics.launch("SlopesProcess")

        if self.ics.is_connected("loop"):
            self.log("Already connected to loop")
        else:
            self.log("Starting loop")
            self.ics.launch("Loop")

        self.update_status("Ready! Acquiring images...", "orange")
        self.ics.start_all()
        self.enable_controls()

    def set_exposure_active_optics(self):
        t, coadd = sc.texpos_active_optics()
        self.entryItime.setText(f"{t:.2f}")
        self.on_itime_return_pressed(self.entryItime)
        self.entryCoadds.setText(str(int(coadd)))
        self.on_coadds_return_pressed(self.entryCoadds)

def cleanup():
    app.quit()

def exception_hook(exctype, value, traceback):
    """Catches any unhandled crashes in the main thread or subwindows 
    and instantly kills the process tree before it deadlocks.
    """
    sys.__excepthook__(exctype, value, traceback)
    print("\nUncaught exception in GUI thread. Force quitting process tree...")
    sys.stdout.flush()
    os._exit(1) # Severe but necessary to prevent unkillable background processes

sys.excepthook = exception_hook

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