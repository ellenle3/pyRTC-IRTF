import time
import numpy as np
from multiprocessing.shared_memory import SharedMemory
from pyRTC.Pipeline import ImageSHM

class SHMConnectionManager:
    def __init__(self, main_name, meta_name, shape, dtype, timeout_seconds=2.5, is_consumer=True):
        self.main_name = main_name
        self.meta_name = meta_name
        self.shape = shape
        self.dtype = dtype
        self.timeout_seconds = timeout_seconds
        self.is_consumer = is_consumer

        # Core Handles
        self.shm = None
        self.metadata = None
        self.connected = False

        # Internal Clocks
        self.last_heartbeat_time = time.time()
        self.pause_start_time = None
        self.old_count = -1

    def try_connect(self):
        """Pre-flight checks and safely binds to existing SHM streams."""
        if self.connected:
            return True
        try:
            # 1. OS check to ensure files exist
            m_check = SharedMemory(name=self.meta_name)
            m_check.close()
            d_check = SharedMemory(name=self.main_name)
            d_check.close()

            # 2. Bind to structures
            # Using keyword 'consumer' if required, keeping compatible with your pyRTC setup
            self.metadata = ImageSHM(self.meta_name, (ImageSHM.METADATA_SIZE,), np.float64, consumer=self.is_consumer)
            self.shm = ImageSHM(self.main_name, self.shape, self.dtype, consumer=self.is_consumer)
            
            # Flush initial tracking state
            meta = self.metadata.read_noblock()
            self.old_count = meta[0]
            self.last_heartbeat_time = time.time()
            self.pause_start_time = None
            self.connected = True
            return True
        except Exception:
            self.disconnect()
            return False

    def check_heartbeat(self, current_count):
        """Monitors frames to manage zombie-mapping disconnect triggers."""
        if current_count != self.old_count:
            self.old_count = current_count
            self.last_heartbeat_time = time.time()
            self.pause_start_time = None
            return True # Active frame change
        else:
            if self.pause_start_time is None:
                self.pause_start_time = time.time()
            # If frozen past threshold timeline, kill zombie hooks
            if time.time() - self.last_heartbeat_time > self.timeout_seconds:
                self.disconnect()
            return False

    def disconnect(self):
        """Silently tears down descriptors while preserving frozen UI data arrays."""
        self.connected = False
        if self.metadata:
            try: self.metadata.close()
            except: pass
            self.metadata = None
        if self.shm:
            try: self.shm.close()
            except: pass
            self.shm = None
        if self.pause_start_time is None:
            self.pause_start_time = time.time()

    def get_pause_duration(self):
        if self.pause_start_time is None:
            return 0
        return int(time.time() - self.pause_start_time)