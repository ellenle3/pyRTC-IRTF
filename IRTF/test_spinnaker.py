import time
import matplotlib.pyplot as plt
import pyRTC.utils as utils
import numpy as np

from pyRTC.hardware import SpinnakerWFS

FILE = open("/Users/ellenlee/Documents/pyRTC-IRTF/IRTF/output.txt", "a")

def test_exposure(wfs):
    wfs.expose()
    img = wfs.data
    plt.figure()
    plt.imshow(img, cmap='gray')
    plt.show()

if __name__ == "__main__":
    try:
        from pyRTC.Pipeline import clear_shms
        shm_names = ["wfs", "wfsRaw", "wfc", "wfc2D", "signal", "signal2D", "psfShort", "psfLong"] #list of SHMs to reset
        clear_shms(shm_names)
    except:
        print("Could not clear all SHMs")
    try:
        conf = utils.read_yaml_file("config_asmlab.yaml")
        wfs_conf = conf["wfs"]
        wfs = SpinnakerWFS(wfs_conf)

        #wfs.setRoi((336, 336, 200, 200))

        # flush out the first one
        #wfs.expose()

        #wfs.setRoi((256, 256, 100, 100))
        #wfs.setRoi((336, 336, 200, 200))
        
        #wfs.setRoi((336, 336, 200, 200))
        #FILE.write(str(wfs.roi_nodes["offset_x"].GetValue()))

        #wfs.setRoi((336, 336, 972, 844))
        FILE.write(str(wfs.roi_nodes["offset_x"].GetValue()))

        test_exposure(wfs)

        k = 0
        N = 1000
        start = time.time()
        while k < N:
            #FILE.write(f"{k}\n")
            wfs.expose()
            k += 1
        end = time.time()
        FILE.write(f"Average framerate: {N/(end-start)} Hz\n")

        #wfs.setRoi((64, 64, 189, 319))  # Example ROI
        #test_exposure(wfs)

    finally:
        FILE.close()
        del(wfs)