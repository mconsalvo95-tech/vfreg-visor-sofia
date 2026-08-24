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
- Advanced the development version to `0.3.0.dev0`.

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
