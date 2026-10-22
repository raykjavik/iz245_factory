# Calibration GUI integration

The folder is a runnable update of the supplied flat Python application. Run
`python -m pip install -r requirements.txt`, then `python app.py`.
Python 3.10+ is required. The supplied complete `iz245` package is bundled in the `iz245/` folder.
Keep your existing `template.docx` beside `project.py`. Instrument imports
are at module level; missing dependencies now fail immediately at startup.
`pyzmq` is included in requirements for `iz245.nmea`.

## Files to integrate

Changed: `app.py`, `calib_tab.py`, `calib_controller.py`, `ssh_utils.py`,
`requirements.txt`. Installation constants: `connection_cfg.py`. The `iz245/` package contains
all eight newly supplied modules. One import correction in `iz245/device.py`
loads `TIMEOUT_SCPI` from `connection_utils`, where it is defined, rather than
from `scpi_utils`. Other application files were copied from your baseline.
`calib_cfg.py` is an unchanged copy of your latest attachment. Replace it
with your own corrected version before running real hardware measurements.
No hardware-specific configuration corrections are applied by this update.
The controller imports the flat module names used by your application's entry
point; these replace the earlier `app.calib` / `app.calib_cfg` imports.

## Operation

Open/create a project. Only Operator and Dwell time appear in the calibration
settings. Verify the dwell time (initially 0.100 seconds per point); it is an
editable starting value, not a validated DUT setting. These two values persist
locally through Qt QSettings. Connection parameters come exclusively from
`connection_cfg.py`; any old connection settings in QSettings are ignored.
Temperature comes from project details.

Connect the generator to the correct channel before clicking CALIBRATE CH1
or CALIBRATE CH2. The buttons run independent pipelines:

- CH1: measure CH1 files, upload them, restart/reconnect, measure preselector
  files, upload them, restart/reconnect.
- CH2: measure CH2 files, upload them, restart/reconnect.

A row's Measure action only measures and saves that calibration locally.
Upload only transfers that file; it does not restart the DUT. Download fetches
that file from the DUT and replaces the local version after validating it.
The top-row Download All button downloads every configured calibration file,
updates rows after each file and reports progress by file count. It supports
Abort and the same busy-state locking. On the first failed download it stops;
completed downloads are kept and untouched local files retain their data.
It uses SSH only, without connecting the generator or restarting the DUT.
The Available row LED means complete, finite local measured data, not proof of
an upload or calibration accuracy. The Calibrations tab LED goes green once
all configured calibration files exist locally, including files that have not
yet been measured; it stays red while any file is missing. Missing/corrupt files stay red; hover the
LED for details. Show overlays available curves. Frequency is displayed in
MHz on a logarithmic or linear x axis; Limit remains in dB without conversion.

Each completed measurement is saved by replacing a temporary file and is
published immediately to the GUI, even while the pipeline continues. Abort
stops between device calls/frequency points and during restart waits or
transfers. Completed results are retained. An unfinished measurement does
not overwrite a prior file. Aborting cannot undo uploads already completed.
An interrupted upload may leave a partial remote file: rerun that upload
before using the DUT calibration. Generator output is switched off and both
instrument connections are closed when hardware work ends, including errors.

Progress counts frequency points, file transfers and successful restarts as
work units. It is not a time estimate. During work, all pipeline and row action
buttons are disabled; plot selection remains available. Project changes,
DUT identity reads and window closure are blocked until cleanup completes.
Abort cannot forcibly interrupt a blocking SCPI call. Configure finite socket
connection/read timeouts in your existing `iz245.connection_utils` so failed
hardware cannot block indefinitely.

## Windows app to Linux DUT transfer

Set installation constants in `connection_cfg.py`:

- `GENERATOR_IP = '10.0.1.54'`, `GENERATOR_PORT = 5025`.
- `SSH_USERNAME = 'root'`, `SSH_PORT = 22`.
- `SSH_REMOTE_CALIB_DIR`: REQUIRED; set to the DUT's actual absolute directory.
  It was not supplied, so its initial value is empty and transfers fail clearly
  until it is configured. The directory must already exist and be writable.
- `PUTTY_KEY_PATH`: `secrets/245.ppk` relative to the application modules
  (`app/secrets/245.ppk` in an app-directory deployment). Paths resolve from
  `__file__`, independently of the working directory.
- `PSCP_EXECUTABLE = 'pscp.exe'`: install PuTTY on PATH or set a full path.
- `SSH_TRANSFER_TIMEOUT_SEC = 120.0`.
- `SSH_AUTO_ACCEPT_NEW_HOST = True`.

The private key was not attached, so the archive contains the `secrets` folder
and instructions, but no actual key. Copy your existing `245.ppk` into that
folder before deployment. For a PyInstaller Windows build, include the key with
`--add-data "secrets/245.ppk;secrets"`. Use a key usable noninteractively or
pre-load an encrypted key into Pageant. The DUT IP remains project-specific.

Transfers run without a command shell. On a first connection, the subprocess
recognizes PuTTY's uncached-host-key prompt and supplies `y` automatically to
cache and trust that first key. No fingerprint field or acceptance dialog is
shown. This trusts the first host reached at the project's DUT address. A
changed cached host key receives no automatic acceptance. Unexpected prompts
are bounded by the transfer timeout. The prompt handling follows PuTTY's English
console messages. To require an existing cached key, set
`SSH_AUTO_ACCEPT_NEW_HOST = False` (batch mode).
PuTTY documents its host prompt and batch behavior at
https://the.earth.li/~sgtatham/putty/latest/htmldoc/Chapter5.html .

Linux remote paths with spaces/shell characters are not supported; Windows
local paths with spaces are supported. Download validation preserves the old
local file if transfer or validation fails. The supplied SMA1000B.open ignores
its port argument, so the GUI's default generator adapter opens a socket using
the configured IP and port with a 10-second socket timeout; tuning and commands
continue to use the supplied instrument methods.

## Validation

`python -m unittest -v test_calibration.py test_gui.py`

Tests use fake instruments/transfers and offscreen Qt. Real Windows PuTTY
transfers, DUT behavior, generator power settings and hardware-specific SCPI
commands still require validation with your equipment.
