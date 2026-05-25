
import subprocess
from pyroics import get_ics_proxy


def Overseer():
    """Monitors components to make sure that they are in a safe and functional
    state.
    """
    def __init__(self):
        self.ics = get_ics_proxy()
        self.old_offset = (0, 0)
    
    def check_t3io_guidebox(self):
        """
        """
        result = subprocess.run(["t3io", "info", "OS"], capture_output=True, text=True)
        output = result.stdout.strip()
        output = output.split(' ')
        if output[0] != "OK":
            raise ConnectionError(f"t3io error. Output: {output}")
        
        # Format is OK TotalOS(ra dec) UserOS(ra dec enable) BeamOS(ra dec enable) ScanOS(ra dec) [all in arcsec]
        # We only care about the total offset
        total_offset = output[1].split(' ')
            
    def check_commands(self):
        """Monitors commands sent to ASM.
        """
        pass


if __name__=='__main__':
    overseer = Overseer()