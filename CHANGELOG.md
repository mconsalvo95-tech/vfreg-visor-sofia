# Changelog

All notable changes to VFREG Visor will be documented in this file.

The project follows semantic versioning once it reaches its first formal
release.

## Unreleased

## 0.4.0.dev1 — 2026-09-06

- Production-readiness work begins from the successful company-PC pilot.
- Added a Python 3.13 `uv` environment with a committed dependency lockfile.
- Separated the OpenPyXL runtime dependency from the PyInstaller development
  and portable-build dependency.
- Standardized setup, test, preflight, collector, and portable-build commands
  on the locked environment.
- Reorganized Python code into the `src/vfreg_visor` application package with a
  single `vfreg-visor` entry point.
- Added application version reporting to the CLI, backend, and dashboard.
- Added startup configuration validation, local-only dashboard enforcement,
  writable data-path checks, single-instance protection, and clear occupied-port
  diagnostics.
- Added SQLite-backed historical filtering with five management presets, custom
  From/To timestamps, matching-record counts, and a live-view reset.
- CSV and XLSX downloads now export the selected period. XLSX keeps only the
  Readings, Charts, and hidden Chart Data worksheets.
- Added a discreet support link and kept technical diagnostics out of the normal
  dashboard.
- Advanced the development version to `0.4.0.dev1`.
- The portable executable now opens the dashboard in the Windows default browser
  automatically while keeping its collector console visible.
- Added 400-day measurement and event retention, a 12 GB runtime storage budget,
  bounded operational logs, free-space health thresholds, and a preflight
  capacity check sized for five-second production polling.
- Added verified scheduled SQLite backups, offline backup/verification/restore
  commands, and tested recovery of WAL-committed records after abrupt exit.
- Added explicit Modbus data-gap events and backend quality flags for
  unverified, out-of-range, incomplete, and invalid readings.
- Added the approved Phase 6 **VFREG · SOFIA** Spanish operator shell with
  separate Live, History, and Reports sections while keeping routine technical
  information collapsed.
- Added plain-language waiting, disconnected, stale-data, storage-warning,
  export-error, and production-paused UI states. Production pause is inferred
  only for presentation when Volts and mAmp are zero/near zero while frequency
  continues; collection and raw history remain unchanged.
- Added a shared time period for live trends, history, matching counts, and
  filtered CSV/XLSX downloads, with 5/15/30/60-minute, current-workday, and
  validated custom ranges.
- Added card sparklines, overview and single-metric chart modes, zoom, exact
  value tooltips, sticky history headers, table-only quality filters, and a
  separate historical CSV through the selected cutoff. Raw stored readings,
  including zero values and gaps, remain unchanged.
- Kept the operator-controlled recording interval in a compact top control and
  moved the displayed time range into the Live Monitoring trends panel that it
  directly controls. The controls no longer remain pinned while scrolling, and
  Report's **Change period** action returns directly to the chart selector.
- Scoped the recording-interval control to **Live Monitoring** so it is hidden
  automatically in the History and Reports views.
- Restored synchronized period controls inside History and a guided Reports
  workflow with workday, full-history, and custom scopes. Report format
  selection once again updates a visible download summary, and selecting
  **Excel + charts** reveals a truthful workbook-content preview.
- Decoupled the three card sparklines from the selected Trends period. They now
  always show the latest 40 live readings with a simple operator-facing label.
- History now treats 5/15/30/60 minutes as sampling intervals across the
  current workday, selecting the first real stored reading in each aligned
  interval instead of showing second-by-second rows from a recent-time window.
- Redesigned management exports so CSV and XLSX use the clean Fecha, Hora,
  Volts, mAmp, and Frec columns without connection status. XLSX now contains
  Raw Data plus a Report worksheet with blank validated limit cells,
  positive-reading averages, and separate Voltage, Current, and Frequency
  charts whose limit lines appear only after both limits are entered.
- Restored a live XLSX preview in Reports with the same parameter/limit table,
  calculated averages, and three separate trend previews for the selected
  period.
- History sampling selections respond immediately, show a visible loading
  state, and supersede any automatic refresh already in progress. Trends and
  Reports retain their independent period behavior, and raw readings remain
  unchanged for exports and investigation.
- History source rows and their total are now read from the same SQLite snapshot,
  preventing live inserts from producing a misleading one-row truncation
  message while the simulator or factory collector is active.
- Completed the Phase 6D workbook report with explicit start/end timestamps,
  total and valid reading counts, editable-limit out-of-range formulas, and
  separate estimated production-pause and disconnection durations.
- Production pauses remain untouched in Raw Data. Voltage and current averages
  exclude zero/near-zero pause values, while received frequency remains part of
  its own average.
- XLSX export now rejects selections beyond Excel's 1,048,575 data-row capacity
  with smaller-period/CSV guidance; the collector continues running normally.
- Reports now offer Automatic, 1, 5, 10, 15, and 30-minute XLSX chart
  resolution. Manual intervals chart bucket averages while retaining detected
  production-pause points; Raw Data and all report calculations remain complete.
- Improved Excel 2019 chart compatibility: hidden helper data now materializes
  typed timestamps and measurements, charts opt into hidden-cell plotting, and
  workbook objects are explicitly visible. Manual Excel/Google Sheets validation
  remains an operational gate.

## 0.1.0-pilot-success — 2026-08-24

### Added

- Read-only Modbus TCP collection from the confirmed NT1-B endpoint.
- Unit 5, function 04, input-register 0–2 mapping for Volts, mAmp, and
  frequency.
- Local SQLite storage and raw packet journal.
- Management CSV and XLSX exports with second-resolution timestamps.
- Local browser dashboard with connection state, recent readings, trends, and
  selectable polling intervals.
- Portable Windows package that runs without Python, Git, an IDE, or internet
  access.

### Validated

- Correlated live register values against the physical VFREG display.
- Successful portable deployment and pilot operation on the company PC.

### Safety

- Production communication is restricted to Modbus function 04 reads.
- No device write operation is implemented.
