# Phase 6A interactive dashboard mockup

Developer design archive for Phase 6E comparison. It is not copied into the
factory ZIP and is not operator documentation.

This local-only prototype validates the proposed operator experience before any
production dashboard code changes are made.

## Review goals

- Confirm the **VFREG · SOFIA** brand hierarchy and company-logo placement.
- Validate Spanish labels with normal, non-technical operators.
- Review Live Monitoring, History, and Reports navigation.
- Review connection, stale-data, out-of-range, and disconnected states.
- Validate shared time-range controls and reading-quality filters.
- Confirm the CSV raw-data and XLSX Raw Data + Report export model.
- Review at the production target resolution of 1366×768.

## Safety boundary

The mockup uses sanitized simulated readings. It does not connect to the VFREG,
Modbus, SQLite, the collector, or production export endpoints.

## Local preview

Serve this directory with any local static-file server and open `index.html`.
The prototype deliberately has no external network or package dependency.

`preview-1366x768.png` records the initial Live Monitoring view at the target
factory resolution for pull-request and manager review.
