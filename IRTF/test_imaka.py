import time
import matplotlib.pyplot as plt
import pyRTC.utils as utils
import numpy as np

from pyRTC.hardware.ImakaDM import ImakaDM

#FILE = open("/home/felix/src/pyrtc/IRTF/output.txt", "a")
FILE = open("/Users/ellenlee/Documents/pyRTC-IRTF/IRTF/output.txt", "a")

if __name__ == "__main__":
    try:
        conf = utils.read_yaml_file("config_felix.yaml")
        dm_conf = conf["wfc"]
        dm = ImakaDM(dm_conf)

        testcmd = np.zeros(dm.numActuators, dtype=np.float32)
        start = time.time()
        n = 100
        for i in range(n):
            dm.write(testcmd)
            dm.sendToHardware()
            FILE.write(dm.testval + "\n")
        end = time.time()
        FILE.write(f"Time for {n} commands: %f\n" % (end - start))
        FILE.write(f"Loop rate: %f Hz\n" % (n / (end - start)))

    finally:
        #FILE.write("aborting\n")
        del(dm)