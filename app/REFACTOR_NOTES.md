# Application refactor

## Applying this update

Python application files are at the archive root, matching the supplied upload. Copy them into your app directory. Keep your current template.docx and reference_data directory; neither was included in the supplied upload and neither is replaced here.

Delete these obsolete files from an existing installation: noise_density.py, noise_measurement.py, noise_units.py, ssh_utils.py. Old aliases and project/file migration paths have been removed. Existing pre-release data may need to be remeasured.

## Measurement values and references

SweepMeasurement uses vals throughout, with no limit_dB alias. Unit and quantity describe the native saved values. Calibration retains the firmware-required freq[Hz];Limit[dB]; header. Noise figure uses NF[dB], noise density uses Noise density[dB/Hz], and dBm power uses Power[dBm]. Frontend display offsets remain in test configuration.

Reference overlays require matching native units. They use the same display transformation as the corresponding measurement, with dashed lines and 50% opacity. Reference data is used only in GUI plots.

## Preserved domain changes

Test2 retains the uploaded thermal-noise correction: NF = receiver reading - (-174), stored and plotted in dB. Its quantity is noise_figure so it writes NF[dB].

Test7 retains the uploaded calculation: noise floor = raw noise density + 10*log10(3000); SFDR = (2/3)*(IP3 - noise floor); NF = raw noise density - (-174). NF display and table units are dB. Configuration arrays, hardware commands, independent dwell times, generator synchronization and attenuation settings are preserved.

The supplied fft_processor.py and capture_device.py were preserved unchanged. The iz245 package was not modified.

## Diagnostic capture

Diagnostics now calls the same measurement routine as Test8. BAND and FREQ are explicit capture controls, entered in MHz (defaults 20 MHz and 500 MHz). Before every capture it sends BAND, checks *OPC?, reads back the selected bandwidth, and applies FREQ through Test8 awaited tuning (FREQ ...;:*OPC?). Other DUT setup is retained. Capture format is then selected and acquisition status is published. BAND/FREQ controls are disabled while work is running. A capture socket timeout bounds an absent IQ response. The display dropdown provides RMS dBuV, P [dBm] (50 ohm), and NF [dB]. NF is saved density in dBm/Hz minus (-174 dBm/Hz), independent of FFT ENBW; RMS voltage and power use the Hann ENBW. Files retain calibrated density at full resolution. Completed full-resolution spectra remain available for comparison.

## Spectral chart rendering

Test5, Test6, Test8 and diagnostic spectra (including reference overlays and live averages) retain full-resolution chart sources. Each visible horizontal pixel bin contributes two vertices at the same x-coordinate: minimum then maximum. Zoom, pan, log/linear scale changes and resize recompute this one-line envelope from the visible original data. At close zoom the original FFT bins are drawn directly. Acquisition averages, saved data and report data are unchanged.

## Diagnostic layout and SCPI help

Diagnostics has no tab LED. The top row is Averaged spectrum capture settings, Manual SCPI, then responses/acquisition log. Below, a horizontal splitter places the measurement table on the left and spectrum chart on the right. Drag the splitter to resize. The table supports horizontal scrolling for metadata and save/delete actions.

Manual SCPI has a Help button opening a read-only, monospaced popup. Its UTF-8 source is scpi_help.txt beside tab_diagnostics.py. Copy this resource with the Python files. The offline reference contains 102 alphabetized entries across SMA100B, SMATE200A and IZ245. It combines commands from the supplied package/app and common R&S manual commands, with provenance labels, official manual URLs and separate-port notes for GNSS/logging. No iz245 code or measurement procedure was changed for this layout update.

## IF-spectrum report fix

report.py no longer reads quantity from IFSpectrumMeasurement when preparing template context. quantity remains a sweep field. A regression saves a Test8 spectrum and renders complete reports with and without the generated_report template anchor, checking the filled unit and embedded chart. For this fix alone, replace report.py.

## Verification

105 automated tests passed, including current-format round trips, quantity headers, native-unit reference matching, Test2 and Test7 calculations, diagnostic BAND/OPC/tune-before-capture and GUI-to-worker MHz conversion, missing IQ, pause/resume and abort paths. Offscreen GUI checks covered Test2 NF and a simulated diagnostic capture. Additional regressions check min/max extrema, duplicate bin x-coordinates, logarithmic buckets, a million-point zoom/resize, original-bin recovery, and NF conversion. The diagnostic layout, absence of its tab LED, offline Help popup and reopening were checked in the GUI, alongside a simulated capture. Real hardware capture still needs confirmation.

Tests are in tests/. Run from the app directory with dependencies installed:

    QT_QPA_PLATFORM=offscreen python -m unittest discover -s tests -q

Report-style tests additionally require your Word template.docx.
