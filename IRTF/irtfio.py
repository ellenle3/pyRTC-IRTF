"""Helper functions for communication with the TCS and Felix POM.
"""

import subprocess

def run_t3io(command, *args):
    result = subprocess.run(["t3io", command, *args], capture_output=True, text=True)
    output = result.stdout.strip()
    output = output.split(' ')
    if output[0] != "OK":
        raise ConnectionError(f"t3io error. Output: {output}")
    return output

def is_telescope_slewing():
    """Checks if the telescope is currently slewing by querying t3io.
    """
    output = run_t3io("info", "sm")    
    is_slew = (output[1] == "slew")
    est_time = int(output[2])  # estimated time remaining in seconds, if slewing
                                # 0 otherwise
    return is_slew, est_time

def get_tcs_nonsidereal_rate():
    output = run_t3io("info", "NS")
    ns_rra, ns_rdec = (float(output[1]), float(output[2]))
    return ns_rra, ns_rdec  # rra = rate ra, rdec = rate dec in arcsec/s

def get_tcs_total_offset():
    """Retrieves the current guide box offsets from t3io.
    """
    output = run_t3io("info", "OS")
    # Format is OK TotalOS(ra dec) UserOS(ra dec enable) BeamOS(ra dec enable) ScanOS(ra dec) [all in arcsec]
    # We only care about the total offset
    offset_new = (float(output[1]), float(output[2]))
    return offset_new

def get_felix_xyoffset():
    result = subprocess.run(["/usr/local/bin/felixio", "-h", "felix", "xystage.getoffset"], capture_output=True, text=True)
    output = result.stdout.strip()
    output = ' '.join( output.split() )
    output = output.split()
    if output[0] != "OK":
        raise ConnectionError(f"felixio error. Output: {output}")
    
    dew = float(output[1])  # delta east-west, in arcseconds
    dns = float(output[2])  # north-south
    return dew, dns