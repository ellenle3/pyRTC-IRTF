"""Builds on Telemetry.py to generate multi-extension FITS files following
imaka telemetry format.
"""
from pyRTC.Pipeline import ImageSHM, work
from pyRTC.utils import *
from pyRTC.pyRTCComponent import *
import os
import numpy as np
import matplotlib.pyplot as plt
from numba import jit
from sys import platform

from astropy.io import fits

class ImakaTelemetry(pyRTCComponent):

    def __init__(self, conf, n_channels=64) -> None:

        super().__init__(conf)

        self.dataDir = setFromConfig(conf, "dataDir", "./data/")
        self.prefix = setFromConfig(conf, "prefix", "aocb")
        self.overwrite = setFromConfig(conf, "overwrite", True)
        self.numIter = setFromConfig(conf, "numIter", 1000)

        self.mostRecentFile = ''
        self.allFiles = []
        self.dTypes = []
        self.dims = []

        self.loopParams = []
        self.slopes = []
        self.commands = []
        self.slopeOffsets = []
        self.avgWfsPixels = []
        self.avgSlopes = []
        self.avgCommands = []
        self.wfsImages = []
        self.wfsImagesRaw = []

        # Number of voltage channels for DM
        self.n_channels = n_channels
        return
    
    def setNumIter(self, numIter):
        """Sets number of loop iterations to collect.
        """
        self.numIter = numIter
    
    def saveAndGet(self, idx, saveWFSImages=False):
        """Saves and returns telemetry data following the imaka format.

        Parameters:
        idx (int): Index for the filename.

        Returns:
        HDUList: The FITS HDUList following the imaka telemetry format.
        """
        fname = self.save(idx, saveWFSImages)
        return fits.open(fname)
    
    def save(self, idx, saveWFSImages=False):
        """Saves telemetry to a multi-extension FITS file following the imaka
        telemetry format.

        Parameters:
        idx (int): Index for the filename.

        Returns:
        str: The filename of the saved FITS file.
        """

        fname = os.path.join(self.dataDir, f"{self.prefix}{idx:04d}.fits")
        fname = os.path.abspath(fname)

        self.recordData(saveWFSImages)

        # ext0: loop state (niter, np). np = 5 currently
        hdu0 = fits.PrimaryHDU(data=np.array(self.loopParams, dtype='>i8'))

        # ext1: wfs raw pixel data, but this is obsolete. set to zero [0] dtype=uint16
        hdu1 = fits.ImageHDU(data=np.array(self.wfsImagesRaw, dtype='uint16'), name="WFS_RAW_PIXELS")

        # ext2: processed data. also obsolete. [0.], dtype=>f4
        hdu2 = fits.ImageHDU(data=np.array(self.wfsImages, dtype='>f4'), name="WFS_PROC_PIXELS")

        # ext3: wfs data. (niter, nwfs, 2*nsub) dtype=>f4
        hdu3 = fits.ImageHDU(data=np.array(self.slopes, dtype='>f4'), name="WFS_SLOPE_DATA")

        # ext4: DM data. (niter, 2, nchannels) data[0,0] should give commands
        hdu4 = fits.ImageHDU(data=np.array(self.commands, dtype='>f4'), name="DM_DATA")

        # ext5: average WFS camera data. (nwfs, nx, ny)
        hdu5 = fits.ImageHDU(data=np.array(self.avgWfsPixels, dtype='>f4'), name="WFS_AVG_PIXELS")

        # nave doesn't exist since we aren't constantly collecting telemetry over
        # a circular buffer. set to average over niter instead...

        # ext6: average slopes over nave. (2*nsub)
        hdu6 = fits.ImageHDU(data=np.array(self.avgSlopes, dtype='>f4'), name="WFS_AVG_SLOPES")

        # ext7: average DM voltages over nave. (nchannels)
        hdu7 = fits.ImageHDU(data=np.array(self.avgCommands, dtype='>f4'),   name="DM_AVG_VOLTAGES")

        # ext8: slope offsets. (niter, nwfs, 2*nsub) not implemented yet...
        hdu8 = fits.ImageHDU(data=np.array(self.slopeOffsets, dtype='>f4'), name="WFS_SLOPE_OFFSETS")

        # ext9: pseudo open-loop slopes. Potentially obsolete, set to [-1] to match.
        noData = np.array([-1.], dtype='>f4')
        hdu9 = fits.ImageHDU(data=noData, name="WFS_PSEUDO_OL_SLOPES")
        # ext10-15: The rest appear to be related to Ryan's tomography work.
        hdu10 = fits.ImageHDU(data=noData, name="SLOPE_RECFILTER_COEFF")
        hdu11 = fits.ImageHDU(data=noData, name="FILTERED_CENTROIDS")
        hdu12 = fits.ImageHDU(data=noData, name="UNFILTERED_FOURIER_SX")
        hdu13 = fits.ImageHDU(data=noData, name="FILTERED_FOURIER_SX")
        hdu14 = fits.ImageHDU(data=noData, name="UNFILTERED_FOURIER_SY")
        hdu15 = fits.ImageHDU(data=noData, name="FILTERED_FOURIER_SY")
        # Set all to [-1].

        hdul = fits.HDUList([hdu0, hdu1, hdu2, hdu3, hdu4, hdu5,
                             hdu6, hdu7, hdu8, hdu9, hdu10, hdu11,
                             hdu12, hdu13, hdu14, hdu15])
        if self.overwrite:
            hdul.writeto(fname, overwrite=True)
        else:
            n = 1
            while os.path.exists(fname) and n < 10000:
                fname = os.path.join(self.dataDir, f"{self.prefix}{idx:04d}-{n:04d}.fits")
                n += 1
            if n >= 10000:
                raise ValueError(f"Too many files beginning with the name {self.prefix}." \
                                 + " Please change the index or delete some files.")           
            hdul.writeto(fname, overwrite=False)

        self.clearData()

        return fname

    def recordData(self, saveWFSImages):
        """Listens for data over the specified number of loop iterations. Since
        not all parameters may update every iteration, it uses non-blocking reads
        except for the loop parameters, which will update every time the loop
        counter needs to be incremented.

        Parameters:
        niter (int): Number of iterations to record.
        """

        wfsShm, wfsDims, wfsDtype = initExistingShm("wfs")
        wfsRaw, wfsRawDims, wfsRawDtype = initExistingShm("wfsRaw")
        signalShm, signalDims, signalDtype = initExistingShm("signal")
        wfc2DShm, wfc2DDims, wfc2DDtype = initExistingShm("wfc2D")
        m2cShm, m2cDims, m2cDtype = initExistingShm("m2c")
        loopShm, loopDims, loopDtype = initExistingShm("loop")
        cmatShm, cmatDims, cmatDtype = initExistingShm("cmat")
        refSlopesShm, refSlopesDims, refSlopesDtype = initExistingShm("refSlopes")

        cumulativeWFSFrame = np.zeros(wfsDims, dtype=wfsDtype)
        cumulativeSlopes = np.zeros(signalDims, dtype=signalDtype)
        cumulativeCommands = np.zeros((2, self.n_channels), dtype='f4')

        for i in range(self.numIter):
            
            # block here because it will update with each loop iteration
            self.loopParams.append( loopShm.read() )

            # do not block for all of the below, e.g., refSlopes may not be updated
            # between loop iterations
            slopes = signalShm.read_noblock()
            self.slopes.append([slopes])
            cumulativeSlopes += slopes

            cmds = wfc2DShm.read_noblock()
            m2c = m2cShm.read_noblock()
            cmat = cmatShm.read_noblock()
            #cmdsRaw = wfcShapeShm.read_noblock() (64, 288)
            cmds = cmds.flatten()
            cout = np.zeros((2, self.n_channels))
            cout[0, :len(cmds)] = m2c @ (cmat @ slopes)
            cout[1, :len(cmds)] = cmds
            self.commands.append(cout)
            cumulativeCommands += cout

            refSlopes = refSlopesShm.read_noblock()

            wfsImage = wfsShm.read_noblock()
            self.slopeOffsets.append([refSlopes.flatten()])
            cumulativeWFSFrame += wfsImage

            if saveWFSImages:
                self.wfsImagesRaw.append( [wfsRaw.read_noblock()] )
                self.wfsImages.append([wfsImage])

        self.avgWfsPixels.append( cumulativeWFSFrame / self.numIter )
        self.avgSlopes.append( cumulativeSlopes / self.numIter )
        self.avgCommands.append( cumulativeCommands / self.numIter )

        if not saveWFSImages:
            self.wfsImagesRaw = [0]
            self.wfsImages = [0.]

    def clearData(self):
        self.loopParams = []
        self.slopes = []
        self.commands = []
        self.slopeOffsets = []
        self.avgWfsPixels = []
        self.avgSlopes = []
        self.avgCommands = []
        self.wfsImages = []
        self.wfsImagesRaw = []