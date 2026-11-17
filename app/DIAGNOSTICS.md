# Diagnostics tab

The new Diagnostics tab lives in tab_diagnostics.py. diagnostic_controller.py owns its SCPI/capture/file worker; diagnostic_spectrum.py contains the spectrum data, persistence, conversions and acquisition function. Existing measurement procedures and the latest dwell/Test7 fixes are unchanged. app.py is the only pre-existing production file modified for integration.

## Using the tab

1. Open a project. Instrument addresses are taken from its Settings: DUT, Generator 1, and the Test7 two-tone generator as Generator 2.
2. Select a target and enter SCPI commands/queries, one per line. Send SCPI executes the batch and displays query responses. Lines starting with # are comments. Manual SCPI keeps the requested hardware state; closing its connection does not reset the DUT or disable generator outputs.
3. Set a capture name, samples per FFT, FFT window count, overlap percentage and optional IQ format. Capture averaged spectrum reads the current DUT configuration. It waits for pending DUT operations with *OPC?, queries the current frequency/BAND, configures IQ format and linear capture mode, and acquires without a reset or retune. Capture does not resend the SCPI editor contents and does not command generators.
4. View spectra in dBµV, dBm or dBm/Hz. Each saved capture retains its own sample rate and FFT size, so unit conversion uses that capture's Hann noise bandwidth.
5. Completed captures are automatically saved as comment-headed semicolon text files in PROJECT/diagnostics. They appear in the captured-spectra list and are loaded again when the project opens. Show checkboxes and Show all / Hide all control overlays. Delete removes the selected capture file and its curve. Save copy exports a complete file through a background worker.
6. Load spectrum imports another diagnostic file or a calibrated Test8 power-spectrum file. A separate copy is created in the current project's diagnostics folder; the source remains untouched. Diagnostic captures are excluded from calibration uploads, verification evaluation and reports.

## Spectrum units and display

A two-sided periodic-Hann complex FFT is averaged in linear power. Receiver header calibration is applied in the same way as Test8, with no additional peak/RMS factor. Calibrated density in dBm/Hz is the stored canonical data.

For ENBW = 1.5 * sampling_rate / window_samples:

- dBm/Hz displays stored density directly.
- dBm displays density + 10*log10(ENBW), the same Hann power-spectrum convention used by Test8.
- dBµV adds 106.9897 dB to that dBm value for the existing 50-ohm convention.

Power in dBm/dBµV is per Hann resolution bandwidth, not the total power integrated over the entire captured band. Different FFT sizes/sample rates can therefore change noise levels in those views; dBm/Hz is appropriate for comparing densities.

Live chart updates and progress are throttled to 0.5 seconds, with a final completion update. Full-resolution data is saved. Maximum envelopes of up to 2048 display buckets are cached for responsive overlays/unit changes. The chart reuses SweepChart, including signed linear frequency offsets, SI tick labels, reset/pan/zoom, visible-Y autoscaling and collapsible free/snap cursors. Hover is disabled as on the other spectral charts.

All instrument work, FFT processing, saves, loads, imports and exports run outside the GUI thread. The existing measurement toolbar pauses/resumes/aborts diagnostic capture. Abort also interrupts blocked capture/SCPI reads. Global busy handling prevents diagnostics from running simultaneously with calibration, verification or DUT identity reads. Import/load operations open no hardware.

Each file records its name, UTC time, operator, carrier, bandwidth, sample rate, FFT size, overlap, completed averages, Hann ENBW, and all full-resolution density points. The display unit is a frontend choice and does not change the saved spectrum.

## Validation

97 automated tests pass, including the original 87 regressions and diagnostic tests for linear averaging/calibration, all three units, both automatic IQ formats, full-resolution save/load, peak-preserving display, all three SCPI targets, query responses/disconnects, Test8 import, comparison/export/delete, pause/resume, blocked-I/O abort and global hardware locking. The nine-tab GUI was inspected offscreen with two populated comparison spectra. No hardware measurements were run in this environment.

The archive retains the uploaded app-directory layout: app.py and modules are at the ZIP root, with tests/ and change notes alongside them. No extra dependencies are required beyond the existing requirements.
