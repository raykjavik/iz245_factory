"""Installation-specific connection constants; no connection controls in the GUI."""
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
GENERATOR_IP = '10.0.1.54'
GENERATOR_PORT = 5025

# DUT address continues to come from the active project's DUT IP.
SSH_USERNAME = 'root'
SSH_PORT = 22
SSH_REMOTE_CALIB_DIR = '/xradio/calibration'  # Set to the DUT's actual absolute calibration directory.
PUTTY_KEY_PATH = APP_DIR / 'secrets' / '245.ppk'
PSCP_EXECUTABLE = 'pscp.exe'
SSH_TRANSFER_TIMEOUT_SEC = 5.0
SSH_AUTO_ACCEPT_NEW_HOST = True
