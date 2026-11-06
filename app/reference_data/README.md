# App reference overlays

Put reference files in `calibration/` or `tests/`, using exactly the same filenames and measurement formats as the corresponding project files. Calibration references use `calibration/` here even though project calibration files are stored in `calib/`.

When a project measurement is shown in the app, its matching reference is shown in the same color with a dash-dot line and 50% opacity. Reference files are optional and read-only. Missing or unreadable files are skipped. A changed file is reloaded on the next chart redraw.

References do not affect validation, measurement files, uploads, project data or generated reports. Test8 reference spectra should use the same units as the measurement being compared; incompatible legacy PSD references are skipped rather than mixed with calibrated dBm levels.
