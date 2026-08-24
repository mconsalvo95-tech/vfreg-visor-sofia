# VFREG Visor — Project Handoff

Last updated: 2026-08-24
Current development version: `0.4.0.dev0`
Production-readiness status: Phase 5 complete

## User communication

The user speaks Spanish and prefers responses in English unless they explicitly
request Spanish content.

## Objective and safety boundary

VFREG Visor records the electrical values shown by the poultry stunning monitor:
Volts, mAmp, and frequency. It stores historical evidence and provides local CSV
and XLSX exports. It does not associate measurements with individual birds.

The production collector is strictly read-only:

- Only Modbus function `04` is permitted by startup validation and request code.
- No Modbus write operation may be added without a separate engineering and
  safety review.
- The application monitors the process; it does not control it or replace any
  safety system.
- The dashboard must remain bound to `127.0.0.1`.

## Confirmed factory protocol

Confirmed against the real viewer on 2026-08-21:

- Ebyte NT1-B at `192.168.1.7`, TCP server port `502`.
- Collector Ethernet address: `192.168.1.1/24`, with blank gateway and DNS.
- Modbus slave `5`, function `04`, input registers `0–2`.
- Register `0` = Volts, `1` = mAmp, `2` = frequency; scale `1`.
- Serial side observed as 9600 baud, 8 data bits, even parity, 1 stop bit.
- Values vary continuously; no discovery sample is hardcoded.

Do not assume simulator port `5000` or the simulator JSON format applies to the
real device.

## Repository and application structure

The private GitHub repository is `mconsalvo95-tech/vfreg-visor-sofia`.

- `src/vfreg_visor/config.py`: validation, path resolution, safe config updates.
- `src/vfreg_visor/cli.py`: single production entry point and startup lifecycle.
- `src/vfreg_visor/dashboard.py`: local HTTP API and dashboard asset serving.
- `src/vfreg_visor/modbus.py`: confirmed read-only Modbus request/response logic.
- `src/vfreg_visor/network.py`: simulator listeners and collector selection.
- `src/vfreg_visor/storage.py`: SQLite, events, CSV, and raw journal.
- `src/vfreg_visor/exports.py`: XLSX export and charts.
- `dashboard/`: browser UI.
- `tests/`: automated protocol, storage, export, and startup-safety tests.
- `config.example.json`: safe configuration template.
- `config.factory.json`: local deployment configuration, excluded from Git.

Runtime output paths are resolved relative to the deployment configuration.
Startup verifies they are writable, prevents duplicate collectors in one
deployment directory, and reports occupied dashboard ports clearly.

## Reproducible development commands

Python 3.13 and exact dependencies are managed by `uv`:

```powershell
uv sync --locked
uv run --locked python -m unittest discover -s tests -v
uv run --locked vfreg-preflight --config config.factory.json
uv run --locked vfreg-visor --config config.factory.json
```

Build the portable company-PC package with:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\build_portable.ps1
```

The portable package requires no Python, `uv`, Git, IDE, internet access, or
Wireshark on the factory computer.

## Current verification baseline

- The company-PC pilot succeeded with the real viewer.
- Phase 2 reproducible environment was merged through PR #1.
- Phase 5 validation passes 51 automated tests, including HTTP-level filtered
  readings, CSV, XLSX, and invalid-range cases.
- Both simulator and factory configurations pass the new schema validation.
- The reviewed Phase 4 PyInstaller package builds and its executable reports
  `VFREG Visor 0.3.0.dev1` in an offline smoke test. The portable launcher opens
  the local dashboard in the Windows default browser automatically.
- Phase 5 adds 400-day measurement and event retention, bounded journals and
  logs, a 12 GB runtime budget, daily verified backups, tested
  restore/export behavior, explicit data-gap events, and backend quality flags.
- SQLite WAL recovery after abrupt exit, corrupt-database startup rejection,
  disk-full visibility, timestamp timezone awareness, and budget pruning are
  covered by automated tests.
- An 18,522-reading XLSX export was validated with all readings preserved and
  2,000 sampled chart points.
- Existing database schema, relative data paths, exports, and confirmed Modbus
  mapping remain compatible.

## Next work

Follow `PRODUCTION_READINESS_ROADMAP.md`. The next planned work is the UI/UX
refinement checkpoint, followed by Phase 6 runtime reliability. Keep the
production Modbus path strictly read-only while that work proceeds.
