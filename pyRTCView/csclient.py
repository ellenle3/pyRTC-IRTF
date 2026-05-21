#
#   Example command line csclient written in python
#   Uses pyZMQ
#
#   Usage:   % python3 csclient.py <csclient commmand>
#   Example: % python3 cslcient.py loop.state 0
#
#   Version
#    20251002 - second version (MC) cleaning up to be consistent with C-code version...
#    20250716 - first version (MC)
#
#   Dependencies
#    * Zero MQ python library (pip install pyzmq)
#
#   Notes
#    * Assumes a few things that could change - port number, reply message length, (things 
#      that are definitions in imaka.h
#    * sys is only needed for the example/main code to parse the command line.
#
# Example usage - main level % python3 csclient.py loop.state 1
# sys.argv is a list containing all command-line arguments.
# sys.argv[0] is the script name itself.
# sys.argv[1:] contains all the actual arguments passed by the user.
# combine all the arguments into a single string:

import zmq
import os
import sys

# Constants (match the C code)
MAX_MSG_SIZE = 40960     # HARDCODED BUG - Must match imaka.h's MAX_MSG_SIZE
USERNAME = os.getenv("USER", "pycsclient")  # Fallback username
SERVER_ADDR = "tcp://localhost:5556"  # Port from IMAKA_CMD_CLIENT_PORT

def csclient(cscommand):

    # 1. Parse command and parameters
    cmd_parts = cscommand.strip().split()
    if len(cmd_parts) == 0:
        print("No command provided.")
        return

    cmd = cmd_parts[0]
    params = cmd_parts[1:]
    nparams = len(params)

    # 2. Build message like C client
    #    Format: <username> <command> <5-digit param count> <params> "\0"
    param_count_str = f"{nparams:05d}"          # zero-padded to 5 digits
    msg_str = f"{USERNAME} {cmd} {param_count_str}"
    if params:
        msg_str += " " + " ".join(params)
    msg_str += "\0"   # Null terminator, just like C strings

    # Safety check
    if len(msg_str) > MAX_MSG_SIZE:
        print(f"Error: message too long ({len(msg_str)} bytes). Max is {MAX_MSG_SIZE}.")
        return

    print(f">pycsclient: Sending: {msg_str}")

    # 3. Connect to server
    context = zmq.Context()
    socket = context.socket(zmq.REQ)
    socket.connect(SERVER_ADDR)

    # 4. Send the message as bytes
    socket.send_string(msg_str)  # zmq handles the null terminator as part of the string

    # 5. Receive the reply
    reply_bytes = socket.recv()
    try:
        # Convert to string safely
        reply_str = reply_bytes.decode('utf-8', errors='ignore')
    except Exception as e:
        print(f"Error decoding reply: {e}")
        reply_str = "<non-decodable reply>"

    # 6. Print reply (full, or first 2 chars like original C client)
    print(f">pycsclient: Received reply [ {reply_str[:2]} ]")

    # 7. Clean up
    socket.close()
    context.term()

# ------------------------------
# Example usage: python csclient.py loop.state -1
# ------------------------------
if __name__ == "__main__":
    # Combine all command-line args into a single command string
    cscommand = " ".join(sys.argv[1:])
    if not cscommand:
        print("Usage: python csclient.py <command> [params...]")
        sys.exit(1)
    csclient(cscommand)

