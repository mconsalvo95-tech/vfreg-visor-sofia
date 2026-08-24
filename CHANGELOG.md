# Changelog

All notable changes to VFREG Visor will be documented in this file.

The project follows semantic versioning once it reaches its first formal
release.

## Unreleased

- Production-readiness work begins from the successful company-PC pilot.

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
