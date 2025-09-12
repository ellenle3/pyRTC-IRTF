import time
import matplotlib.pyplot as plt
import pyRTC.utils as utils
import numpy as np

from pyRTC.hardware import AndorWFS

#FILE = open("/home/felix/src/pyrtc/IRTF/output.txt", "a")
FILE = open("/home/imaka/asm/pyrtc/pyRTC-IRTF/IRTF/output.txt", "a")

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
        test_exposure(wfs)
        #raise RuntimeError("Test complete")
        #wfs.expose()
        k = 0
        Nframes = 10000
        start = time.time()
        while k < Nframes:
            t1 = time.time()
            wfs.expose()
            t2 = time.time()
            FILE.write(f"{wfs.oldTotalFrames} {t2 - t1}\n")
            k += 1
        end = time.time()
        FILE.write(f"Frame rate: {Nframes / (end - start)}\n")
        #wfs.setRoi((64, 64, 189, 319))  # Example ROI
        #test_exposure(wfs)

    finally:
        FILE.write("aborting\n")
        del(wfs)
