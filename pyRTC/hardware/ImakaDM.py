import os 
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["OPENBLAS_NUM_THREADS"] = "1" 
os.environ["MKL_NUM_THREADS"] = "1" 
os.environ["VECLIB_MAXIMUM_THREADS"] = "1" 
os.environ["NUMEXPR_NUM_THREADS"] = "1" 
os.environ['NUMBA_NUM_THREADS'] = '1'

from pyRTC.WavefrontCorrector import *
from pyRTC.Pipeline import *
from pyRTC.utils import *
import struct
import argparse
import sys
import zmq


class ImakaDM(WavefrontCorrector):

    @staticmethod
    def generate_layout_irtf1():
        """Creates the layout of IRTF-ASM-1."""
        #xx, yy = np.meshgrid(np.arange(7), np.arange(7))
        #layout = np.sqrt((xx - 3)**2 + (yy-3)**2) < 3.2
        layout = np.full((6, 6), True, dtype=bool) # placeholder
        return layout

    def __init__(self, conf) -> None:
        #Initialize the pyRTC super class
        super().__init__(conf)

        self.port = conf["port"]
        self.numActuators = conf["numActuators"]
        self.numChannels = conf["numChannels"]
        self.CAP = conf["commandCap"]  # Maximum command amplitude

        # Initialize socket connection
        context = zmq.Context()
        print("Connecting to loop CMD server...")
        self.socket = context.socket(zmq.REQ)
        self.socket.connect(f"tcp://localhost:{self.port}")
       
        layout = self.generate_layout_irtf1()
        self.setLayout(layout)

        if conf["floatingActuatorsFile"][-4:] == '.npy':
            floatActuatorInds = np.load(conf["floatingActuatorsFile"])
            self.deactivateActuators(floatActuatorInds)

        #flatten the mirror
        self.flatten()

        return
    
    def csclient(self, cscommand):
        """Modified python implementation of csclient originally written by Mark Chun.
        
        The imaka loop CMD server expects a message in the following format
        <username> <csclient command> <nparams> <parameters> "\0"
        Notes:  
        * loop CMD server code uses spaces as the delimiter between elements
        * <username> e.g. normal csclient has a username = "imaka"... no spaces
        * <csclient command> is the command without parameters e.g. "loop.state"
        * <nparams> is the number of parameters we are sending e.g. "1" for "loop.state"
        * <parameters> is a string containing all of the parameters, space delimited. 
        e.g. " -1" for "loop.state", " 0 0 0 0 0 0 ...." for something like set.act.volts
        """
        #  Reparse the cscommand - Need the number of parameters
        cmdstr = cscommand.split(' ')
        n = len(cmdstr)
        cmd = cmdstr[0]
        params = " ".join(cmdstr[1:])
        nparams = n-1
        sndcmd = "imakapycsclientv20250716 " + cmd + " " + str(nparams) + " " + params
        #print(">pycsclient: Sending: %s" % sndcmd)
        self.socket.send_string(sndcmd)
        message = self.socket.recv()
        #print(">pycsclient: Received reply [ %s ]" % (message[:2]))
        return message.decode('utf-8').replace("\x00", "")
    
    def sendToHardware(self):
        #Do all of the normal updating of the super class
        super().sendToHardware()
        #Cap the Commands to reduce likelihood of DM failiure
        self.currentShape = np.clip(self.currentShape, -self.CAP, self.CAP)
        #Send the correction to the actual mirror

        # Pad command to match number of channels
        c = self.currentShape
        c_chan = np.zeros(self.numChannels)
        c_chan[:len(c)] = self.currentShape

        # Generate the command string
        cmd_str = "set.act.volts "
        for num in c_chan:
            cmd_str += '{:.5f}'.format(num) + ' '
        cmd_str = cmd_str.strip()
        message = self.csclient(cmd_str)
        self.testval = message
        self.num_values = len(c_chan)
        return

    def __del__(self):
        super().__del__()
        self.currentShape = np.zeros(self.numActuators)
        self.sendToHardware()
        return
    

if __name__ == "__main__":

    launchComponent(ImakaDM, "wfc", start = True)