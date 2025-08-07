import matplotlib.pyplot as plt
import pyRTC.utils as utils

from pyRTC.hardware.AndorWFS import AndorWFS

def test_set_roi(wfs, roi):
    wfs.setRoi(roi)

def test_set_texpos(wfs, texpos):
    wfs.setExposure(texpos)

def test_binning(wfs, binning):
    wfs.setBinning(binning)

def test_gain(wfs, gain):
    wfs.setGain(gain)

def set_bit_depth(wfs, bit_depth):
    wfs.setBitDepth(bit_depth)

def test_exposure(wfs):
    wfs.expose()
    img = wfs.data()
    plt.figure()
    plt.imshow(img, cmap='gray')
    plt.show()

if __name__ == "__main__":
    conf = utils.read_yaml_file("test_config.yaml")
    wfs_conf = conf["wfs"]
    wfs = AndorWFS(wfs_conf)

    test_set_roi(wfs, (100, 100, 128, 128))
    test_set_texpos(wfs, 0.5)
    test_binning(wfs, 1)
    test_gain(wfs, 0)
    set_bit_depth(wfs, 16)
    test_exposure(wfs)