# VFREG Visor — Production Readiness Roadmap

Last updated: 2026-08-24  
Current status: Successful factory pilot  
Target milestone: `v1.0.0`

## Purpose

This roadmap turns the proven VFREG collector pilot into a maintainable,
supportable, and production-ready Windows application.

Complete the phases in order unless a dependency explicitly allows parallel
work. Check an item only after its result has been tested and documented.

## Confirmed pilot baseline

- [x] The real NT1-B was identified at `192.168.1.7`.
- [x] The confirmed TCP port is `502`.
- [x] The confirmed Modbus unit is `5`.
- [x] The confirmed Modbus function is `04` (Read Input Registers).
- [x] Registers `0–2` provide Volts, mAmp, and frequency.
- [x] The collector stores readings locally.
- [x] CSV and XLSX exports work.
- [x] The browser dashboard works locally.
- [x] The polling interval can be changed from the dashboard.
- [x] A portable Windows package works without Python, Git, or an IDE.
- [x] The portable package was successfully tested on the company PC.

## Non-negotiable safety constraints

- The production collector must remain read-only.
- Only Modbus function `04` may be used by the production collector.
- No Modbus write operation may be added without a separate engineering and
  safety review.
- The application monitors the electrical panel; it does not control the
  process or replace any safety system.
- The dashboard must bind to `127.0.0.1` unless remote access is deliberately
  designed, secured, and approved.
- The confirmed device settings must not be changed automatically.
- Ethernet configuration must never guess which company network adapter to
  modify.

---

## Phase 1 — Preserve the successful baseline

Goal: Preserve the exact version that passed the company-PC pilot.

- [ ] Create a private source-code repository.
- [ ] Choose the repository host: GitHub, GitLab, Azure DevOps, or an internal
  company server.
- [x] Confirm that generated factory data is excluded from version control.
- [x] Confirm that `.pcapng`, SQLite, CSV, XLSX, `.venv`, build, and temporary
  files are ignored.
- [x] Add a sanitized `config.example.json`.
- [x] Keep the real deployment configuration outside public history.
- [ ] Create the first clean commit.
- [ ] Tag the proven baseline as `v0.1.0-pilot-success`.
- [ ] Store the matching portable ZIP and its SHA-256 checksum as release
  artifacts.

### Suggested repository structure

```text
VFREG-VISOR/
├── src/                     # Python application code
├── dashboard/               # Browser UI
├── tests/                   # Automated tests
├── scripts/                 # Build, diagnostic, and deployment tools
├── docs/                    # Operator and support documentation
├── config.example.json      # Safe configuration template
├── pyproject.toml
├── uv.lock
├── README.md
├── CHANGELOG.md
└── PRODUCTION_READINESS_ROADMAP.md
```

### Acceptance criteria

- A new developer can clone the private repository without receiving factory
  measurements or confidential captures.
- The pilot version can be restored from its tag and release artifact.
- The released executable checksum matches the recorded checksum.

---

## Phase 2 — Reproducible development environment

Goal: Make development and builds repeatable on another development computer.

- [ ] Adopt `uv` in the existing project rather than creating a competing
  application folder.
- [ ] Generate and commit `uv.lock`.
- [ ] Pin the supported Python version.
- [ ] Separate runtime dependencies from build and test dependencies.
- [ ] Add one documented setup command.
- [ ] Add one documented test command.
- [ ] Add one documented portable-build command.
- [ ] Verify a clean setup on another development machine or clean virtual
  environment.

### Acceptance criteria

- `uv sync` creates the complete development environment.
- The full automated test suite passes after a clean setup.
- The portable package can be rebuilt without manually installing individual
  libraries.

---

## Phase 3 — Organize the application code

Goal: Improve maintainability without changing the confirmed device protocol.

- [ ] Move Python modules into a clear `src/vfreg_visor/` package.
- [ ] Separate device communication, storage, exports, HTTP API, and
  configuration responsibilities.
- [ ] Define a single application entry point.
- [ ] Add the application version to the backend and dashboard.
- [ ] Validate configuration at startup with useful error messages.
- [ ] Keep deployment configuration and application binaries separate.
- [ ] Ensure all data paths remain writable and relative to the deployment
  configuration.
- [ ] Prevent multiple collector instances from using the same deployment
  directory.
- [ ] Detect and explain when dashboard port `8000` is occupied.

### Acceptance criteria

- Existing Modbus readings remain identical to the pilot.
- Existing databases and exports remain compatible.
- A startup failure explains the specific corrective action.

---

## Phase 4 — Management-facing dashboard

Goal: Make the application useful without exposing unnecessary backend detail.

- [ ] Add historical filtering above **Recent readings**.
- [ ] Add presets: last 5 minutes, 15 minutes, 30 minutes, 1 hour, and today.
- [ ] Add custom **From** and **To** date/time fields.
- [ ] Query SQLite history instead of filtering only visible browser rows.
- [ ] Show the number of matching records.
- [ ] Add a clear/reset-filter action.
- [ ] Allow CSV and XLSX exports to use the selected time period.
- [ ] Keep Volts, mAmp, frequency, timestamp, and connection status prominent.
- [ ] Keep technical diagnostics hidden from the normal management view.
- [ ] Add a discreet application version and support link.
- [ ] Review chart appearance only after the operational features are stable.

### Acceptance criteria

- A manager can find and export readings from a specific production period.
- Filtering does not pause or modify data collection.
- Clearing the filter returns the dashboard to live readings.

---

## Phase 5 — Data integrity and retention

Goal: Protect measurements during continuous operation.

- [ ] Define how long raw packets, SQLite history, CSV, and XLSX files must be
  retained.
- [ ] Add automatic raw-journal and application-log rotation.
- [ ] Define a maximum storage budget.
- [ ] Warn before disk space becomes critical.
- [ ] Handle disk-full and read-only-folder errors without crashing silently.
- [ ] Record connection gaps and missing readings explicitly.
- [ ] Record invalid or out-of-range values with a quality flag.
- [ ] Verify timestamp timezone and Windows clock behavior.
- [ ] Define an automated database-backup schedule.
- [ ] Document and test database restoration.
- [ ] Verify SQLite recovery after an unexpected shutdown.

### Acceptance criteria

- The application cannot fill the disk indefinitely.
- Missing data is distinguishable from a real zero measurement.
- A backup can be restored and exported successfully.

---

## Phase 6 — Runtime reliability

Goal: Operate unattended on the factory PC.

- [ ] Verify automatic reconnection after the Ethernet cable is disconnected.
- [ ] Verify automatic reconnection after the NT1-B is rebooted.
- [ ] Verify recovery after Windows sleep or network-adapter reset.
- [ ] Add graceful shutdown and confirm queued records are flushed.
- [ ] Add health information for the collector, storage writer, and last valid
  reading.
- [ ] Add structured operational logs with timestamps and severity.
- [ ] Decide between a Windows service and a Scheduled Task for automatic
  startup.
- [ ] Start the collector automatically after Windows restarts.
- [ ] Avoid opening duplicate dashboard or collector processes.
- [ ] Provide a safe manual stop/restart procedure.

### Acceptance criteria

- The application resumes collection without operator intervention after a
  temporary network interruption.
- A Windows restart returns the collector to service automatically.
- Normal shutdown leaves no pending SQLite WAL files or lost queued records.

---

## Phase 7 — Packaging and deployment

Goal: Produce controlled, versioned releases for company computers.

- [ ] Keep PyInstaller folder mode as the initial supported package format.
- [ ] Include the application version in the folder and ZIP filename.
- [ ] Include `config.factory.json`, operator instructions, and SHA-256 file.
- [ ] Keep the deployment data directory empty in every release.
- [ ] Add a read-only offline preflight/diagnostic script.
- [ ] Verify Windows 10 and Windows 11 64-bit compatibility.
- [ ] Document SmartScreen and antivirus behavior.
- [ ] Evaluate digital code signing with company IT.
- [ ] Define an upgrade procedure that preserves configuration and data.
- [ ] Define a rollback procedure to the previous release.
- [ ] Test the final ZIP after extracting it into a new directory.

### Acceptance criteria

- The application runs on a clean supported PC without Python, Git, an IDE, or
  internet access.
- Updating the application does not overwrite historical measurements.
- The previous release can be restored quickly.

---

## Phase 8 — Security and industrial safeguards

Goal: Minimize technical and operational risk.

- [ ] Keep the dashboard local-only on `127.0.0.1`.
- [ ] Run without administrator privileges during normal collection.
- [ ] Require administrator privileges only for deliberate Ethernet setup.
- [ ] Validate that the collector cannot send Modbus write functions.
- [ ] Add automated tests that reject write function codes.
- [ ] Protect deployment configuration from accidental edits.
- [ ] Pin and review third-party dependencies.
- [ ] Add dependency and source-code security scanning to the repository.
- [ ] Ensure support bundles exclude confidential measurements unless the
  operator explicitly includes them.
- [ ] Obtain company IT approval for the executable and startup mechanism.

### Acceptance criteria

- A normal operator cannot accidentally write to the device.
- The application does not expose a network service beyond the local PC.
- Production releases are traceable to reviewed source code.

---

## Phase 9 — Production validation

Goal: Prove stability under realistic factory conditions.

- [ ] Run a continuous 24-hour test.
- [ ] Extend to a 72-hour test if the 24-hour test succeeds.
- [ ] Consider a seven-day soak test before final acceptance.
- [ ] Disconnect and reconnect Ethernet during collection.
- [ ] Reboot the NT1-B during collection.
- [ ] Restart Windows during collection.
- [ ] Test temporary loss of power using an approved procedure.
- [ ] Export a large date range to CSV and XLSX.
- [ ] Verify timestamps, seconds, ordering, and duplicate handling.
- [ ] Check CPU, memory, database, and disk growth.
- [ ] Test with no internet connection.
- [ ] Test recovery from backup.
- [ ] Complete final acceptance testing on the exact production PC.

### Minimum production acceptance table

| Area | Required result |
|---|---|
| Device reading | Correct Volts, mAmp, and frequency |
| Safety | Modbus read-only behavior confirmed |
| Reconnection | Automatic recovery after temporary interruption |
| Storage | No silent data loss or uncontrolled disk growth |
| Export | Filtered CSV and XLSX open correctly |
| Startup | Collector returns after Windows restart |
| Offline operation | No internet dependency |
| Deployment | Clean-PC installation succeeds |
| Recovery | Previous version and database backup can be restored |

---

## Phase 10 — Documentation and ownership

Goal: Make operation and support independent of the original development chat.

- [ ] Write an operator quick-start guide.
- [ ] Write a company-PC installation guide.
- [ ] Write an Ethernet configuration guide.
- [ ] Write a backup and restore guide.
- [ ] Write an incident and troubleshooting runbook.
- [ ] Document all confirmed NT1-B and Modbus settings.
- [ ] Document release creation and verification.
- [ ] Define who owns application support.
- [ ] Define who approves updates.
- [ ] Define where releases, backups, and logs are stored.
- [ ] Maintain `CHANGELOG.md` for every release.

### Acceptance criteria

- A trained operator can start, stop, and export data without developer help.
- A support technician can diagnose a connection failure while offline.
- A new developer can reproduce the build from repository documentation.

---

## Version 1.0 release gate

Release `v1.0.0` only when every item below is complete:

- [ ] Private repository and pilot baseline tag exist.
- [ ] Reproducible `uv` environment and lockfile exist.
- [ ] Automated tests pass.
- [ ] Read-only Modbus behavior is verified.
- [ ] Historical filtering and filtered exports work.
- [ ] Reconnection and automatic startup work.
- [ ] Retention, backup, and recovery are documented and tested.
- [ ] A multi-day soak test succeeds.
- [ ] Company IT approves the executable and deployment method.
- [ ] Operator and support documentation are complete.
- [ ] Final portable package passes testing on the production PC.
- [ ] Versioned release ZIP and SHA-256 checksum are archived.

## Recommended immediate work order

1. Create the clean private repository.
2. Preserve and tag the successful pilot baseline.
3. Adopt `uv` and generate the lockfile.
4. Reorganize the project without changing Modbus behavior.
5. Implement historical time filtering and filtered exports.
6. Add single-instance protection, clearer startup errors, and offline preflight.
7. Define retention, backup, and automatic startup.
8. Run fault-recovery and multi-day stability tests.
9. Complete security, IT approval, and documentation.
10. Release `v1.0.0`.

## Decision log

Record meaningful production decisions here as they are approved.

| Date | Decision | Reason | Approved by |
|---|---|---|---|
| 2026-08-24 | Preserve the successful pilot before further restructuring | Protect the proven device integration | Pending |
| 2026-08-24 | Keep production Modbus communication read-only | Protect the electrical process and equipment | Pending |
| 2026-08-24 | Use `uv` for development and PyInstaller for Windows deployment | Reproducible development plus offline operation | Pending |
