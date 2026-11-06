"""Installation-specific connection constants; no connection controls in the GUI."""
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
GENERATOR_IP = '10.0.1.54'
GENERATOR_PORT = 5025

# DUT address continues to come from the active project's DUT IP.
SSH_USERNAME = 'root'
SSH_PORT = 22
SSH_REMOTE_CALIB_DIR = '/xradio/calibration'
SSH_KEY_PATH = Path.home() / '.ssh' / 'vasek' / '245.ppk'
SSH_EXECUTABLE = 'ssh'
SSH_TRANSFER_TIMEOUT_SEC = 120.0
SSH_AUTO_ACCEPT_NEW_HOST = True
