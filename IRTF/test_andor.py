import time
import matplotlib.pyplot as plt
import pyRTC.utils as utils
import numpy as np

from pyRTC.hardware.AndorWFS import AndorWFS

FILE = open("/home/felix/src/pyrtc/IRTF/output.txt", "a")

def test_exposure(wfs):
    wfs.expose()
    img = wfs.data
    plt.figure()
    plt.imshow(img, cmap='gray')
    plt.show()

if __name__ == "__main__":
    try:
        conf = utils.read_yaml_file("config_felix.yaml")
        wfs_conf = conf["wfs"]
        wfs = AndorWFS(wfs_conf)

        k = 0
        while wfs.total_frames < 10:
            #FILE.write(f"{k}\n")
            wfs.expose()
            FILE.write(f"{wfs.total_frames}\n")
            #time.sleep(0.1)
            k += 1

        #wfs.setRoi((64, 64, 189, 319))  # Example ROI
        #test_exposure(wfs)

    finally:
        FILE.write("aborting\n")
        del(wfs)