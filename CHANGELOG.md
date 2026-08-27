# Changelog

All notable changes to VFREG Visor will be documented in this file.

The project follows semantic versioning once it reaches its first formal
release.

## Unreleased

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
- Advanced the development version to `0.4.0.dev0`.
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
  always show the latest 40 live readings, with a dynamic label that translates
  the configured recording interval into approximate time coverage.

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
