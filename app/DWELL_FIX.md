# Dwell timing correction based on the uploaded project

This archive keeps the uploaded app-directory layout: app.py and the other application files are at the ZIP root. Updated regression tests are in tests/. Apply these files to the same app directory from which the uploaded tab_ip3.zip was made.

The upload is the source of truth. Only seven supplied files changed: detector.py, cfg_test2.py, cfg_test_5_6.py, cfg_test_7.py, cfg_test8.py, measurement.py and tab_ip3.py. The other 50 supplied files are byte-identical. Every module-level configuration assignment in cfg*.py is preserved, including frequency arrays, IF filter commands, FFT settings and limits. The supplied Test8 report acquisition paragraph and imports are retained.

Dwell rules:
- SWEEP:DWELL belongs in test setup, not in the detector read helper.
- Clear the detector for each reading.
- For dwell <= 1 second, issue the blocking sense:data? read without an extra sleep.
- For dwell > 1 second, wait once before reading.

Calibration, Test1, Test3 and Test4 already set dwell once during setup and call the supplied Device.measure_point_rms, which implements this threshold correctly. Their files are unchanged. Tests verify their timing using the actual supplied driver method with simulated SCPI.

Test2 sets its dwell once before its sweep. The compatibility noise_measurement helper already did this and remains unchanged. detector.read_detector now clears/reads without setting dwell and waits only above one second. Its explicit wait uses the controller's abortable callback.

Test5/6 sets dwell in initial setup, clears the detector and waits only for a long dwell before the full-range read. The extra dwell sleep after enabling CW is removed. Generator OPC synchronization and FFT averaging remain intact.

Test8 no longer sleeps for short configured settling values; values above one second retain the existing wait. Its IQ capture, filter settings, FFT parameters and user report content are preserved. Test8 uses IQ captures rather than detector readings, so no unrelated SWEEP:DWELL command was added to it.

Test7 retains independent noise and signal/IM3 dwell settings. To avoid per-reading dwell programming, it performs a receiver-noise pass at every frequency with the generator off, followed by the signal/IM3 pass. Each dwell is configured at the start of its pass; equal dwell values need only the initial setting. Cached NF and full-range values are paired with their original frequency. Complete rows/live charts and progress are published during the signal/IM3 pass. Abort cleanup still turns both generator outputs off.

The supplied Test7 NF calculation in dB and exact 3 kHz SFDR correction are preserved. Matching measurement column/metadata and GUI NF labels/filter checks are updated to dB. Files with older unit conventions remain flagged for remeasurement rather than silently relabelled. The previously documented assumption about the receiver's NF field is unchanged.

Validation: 87 tests pass. Timing tests cover <1 s, exactly 1 s, >1 s, command counts, two-pass Test7 frequency pairing, generator-off noise acquisition, equal dwell reuse, and cancellation. All eight supplied GUI tabs open, and Test7 NF values display in dB. Hardware measurements were not run in this environment.
