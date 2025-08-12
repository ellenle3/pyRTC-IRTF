import time
import matplotlib.pyplot as plt
import pyRTC.utils as utils
import numpy as np

from pyRTC.hardware.ImakaDM import ImakaDM

FILE = open("/home/felix/src/pyrtc/IRTF/output.txt", "a")

if __name__ == "__main__":
    try:
        conf = utils.read_yaml_file("config_felix.yaml")
        dm_conf = conf["wfc"]
        dm = ImakaDM(dm_conf)

        dm.csclient("imaka set.nave 3000")

    finally:
        FILE.write("aborting\n")
        del(dm)