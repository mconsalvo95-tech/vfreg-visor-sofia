# VFREG Visor — Production Readiness Roadmap

Last updated: 2026-08-25

Current status: Phase 6B functional foundation complete; approved brand assets
and stakeholder review are pending

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

- [x] Create a private source-code repository.
- [x] Choose the repository host: GitHub, GitLab, Azure DevOps, or an internal
  company server.
- [x] Confirm that generated factory data is excluded from version control.
- [x] Confirm that `.pcapng`, SQLite, CSV, XLSX, `.venv`, build, and temporary
  files are ignored.
- [x] Add a sanitized `config.example.json`.
- [x] Keep the real deployment configuration outside public history.
- [x] Create the first clean commit.
- [x] Tag the proven baseline as `v0.1.0-pilot-success`.
- [x] Store the matching sanitized portable ZIP and its SHA-256 checksum as release
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

- [x] Adopt `uv` in the existing project rather than creating a competing
  application folder.
- [x] Generate and commit `uv.lock`.
- [x] Pin the supported Python version.
- [x] Separate runtime dependencies from build and test dependencies.
- [x] Add one documented setup command.
- [x] Add one documented test command.
- [x] Add one documented portable-build command.
- [x] Verify a clean setup on another development machine or clean virtual
  environment.

### Acceptance criteria

- `uv sync` creates the complete development environment.
- The full automated test suite passes after a clean setup.
- The portable package can be rebuilt without manually installing individual
  libraries.

---

## Phase 3 — Organize the application code

Goal: Improve maintainability without changing the confirmed device protocol.

- [x] Move Python modules into a clear `src/vfreg_visor/` package.
- [x] Separate device communication, storage, exports, HTTP API, and
  configuration responsibilities.
- [x] Define a single application entry point.
- [x] Add the application version to the backend and dashboard.
- [x] Validate configuration at startup with useful error messages.
- [x] Keep deployment configuration and application binaries separate.
- [x] Ensure all data paths remain writable and relative to the deployment
  configuration.
- [x] Prevent multiple collector instances from using the same deployment
  directory.
- [x] Detect and explain when dashboard port `8000` is occupied.

### Acceptance criteria

- Existing Modbus readings remain identical to the pilot.
- Existing databases and exports remain compatible.
- A startup failure explains the specific corrective action.

---

## Phase 4 — Management-facing dashboard

Goal: Make the application useful without exposing unnecessary backend detail.

- [x] Add historical filtering above **Recent readings**.
- [x] Add presets: last 5 minutes, 15 minutes, 30 minutes, 1 hour, and today.
- [x] Add custom **From** and **To** date/time fields.
- [x] Query SQLite history instead of filtering only visible browser rows.
- [x] Show the number of matching records.
- [x] Add a clear/reset-filter action.
- [x] Allow CSV and XLSX exports to use the selected time period.
- [x] Keep Volts, mAmp, frequency, timestamp, and connection status prominent.
- [x] Keep technical diagnostics hidden from the normal management view.
- [x] Add a discreet application version and support link.
- [x] Review chart appearance only after the operational features are stable.
  Appearance changes remain intentionally deferred; operational filtering and
  export behavior are now stable and tested.

### Acceptance criteria

- A manager can find and export readings from a specific production period.
- Filtering does not pause or modify data collection.
- Clearing the filter returns the dashboard to live readings.

---

## Phase 5 — Data integrity and retention

Goal: Protect measurements during continuous operation.

- [x] Define how long raw packets, SQLite history, CSV, and XLSX files must be
  retained.
- [x] Add automatic raw-journal and application-log rotation.
- [x] Define a maximum storage budget.
- [x] Warn before disk space becomes critical.
- [x] Handle disk-full and read-only-folder errors without crashing silently.
- [x] Record connection gaps and missing readings explicitly.
- [x] Record invalid or out-of-range values with a quality flag.
- [x] Verify timestamp timezone and Windows clock behavior.
- [x] Define an automated database-backup schedule.
- [x] Document and test database restoration.
- [x] Verify SQLite recovery after an unexpected shutdown.

### Acceptance criteria

- The application cannot fill the disk indefinitely.
- Missing data is distinguishable from a real zero measurement.
- A backup can be restored and exported successfully.

---

## Phase 6 — Operator UI/UX and management reporting

Goal: Create a modern, branded, operator-friendly interface and produce clear
management exports without changing collection, storage, or device behavior.

### Phase 6A — Interactive mockup and approval

- [x] Create a static dashboard mockup before modifying the production
  dashboard.
- [x] Obtain stakeholder approval before starting Phase 6B production UI
  changes.
- [x] Build the mockup as standalone local HTML/CSS/JavaScript with sanitized
  readings so approved visual components can be reused in the production UI.
- [x] Make the mockup interactive: navigation, time presets, chart tabs,
  reading-quality filters, export selection, and representative connection
  states must be reviewable without a live collector.
- [x] Represent the company logo with a placeholder until the approved logo and
  brand color are supplied; show the proposed **VFREG · SOFIA** identity.
- [x] Demonstrate clear plain-language states with an icon and label: **Normal**,
  **Production paused**, **Out of range**, **Not configured**,
  **No recent data**, and **Disconnected**.
- [x] Capture and review the mockup at 1366×768 before approving Phase 6B.

### Phase 6B — Dashboard visual foundation

- [x] Add the **VFREG · SOFIA** product identity and a reserved company-logo
  position without inventing an unapproved brand mark.
- [x] Keep a labeled placeholder until the user supplies the approved company
  logo. Track the custom application icon and browser favicon as a future
  brand-asset refinement so they do not block operator workflow work.
- [x] Implement operator-facing navigation with **Live monitoring**,
  **History**, and **Reports** while keeping routine diagnostics outside the
  normal operator view.
- [x] Implement the approved modern light-industrial visual system with a dark
  branded header, high-contrast typography, large measurements, consistent
  spacing, subtle borders, and controls suitable for the factory display.
- [x] Give Volts, mAmp, and frequency distinct, consistent visual identities
  while never relying on color alone to communicate status.
- [x] Add the approved branded launch/connection experience with understandable
  progress and a retry action when startup cannot reach the device.
- [x] Implement clear empty, loading, production-paused, disconnected,
  stale-data, degraded-storage, and export-error states. Keep connection and
  process state independent: zero/near-zero Volts and mAmp with continuing
  frequency is **Production paused**, not a connection fault.

### Phase 6C — Live charts and history interaction

- [x] Use one synchronized selected time range for charts, Recent Readings,
  the matching-record count, and filtered export, with controls available in
  the Live trends, History, and Reports workflows where operators need them.
- [x] Provide 5-minute, 15-minute, 30-minute, 1-hour, current-workday, and
  custom `Desde` / `Hasta` ranges.
- [x] Define the current workday as the configurable production start time,
  initially `06:00`, through the current local time.
- [x] Make custom ranges explicit with **Aplicar** and **Limpiar** actions, show
  the selected period, and prevent invalid or reversed ranges from running.
- [x] Add Recent Readings filters for **All**, **Valid**, and
  **Out of range**, with a sticky header and visible matching-record count.
- [x] Add compact live trends to the three measurement cards and provide both
  synchronized overview charts and a detailed single-metric chart view.
- [x] Improve chart legibility, responsive behavior, zoom, exact-value
  tooltips, and visible reset actions.
- [x] Keep a separate historical export that includes all stored readings up
  to the selected cutoff, independently of the active Recent Readings filter.
- [x] Preserve collection gaps and incomplete/zero readings in raw exports;
  filtering must never delete or rewrite stored history.

### Phase 6D — CSV and XLSX export redesign

- [x] Provide clearly separated export scopes: **Historical data**,
  **Current workday**, and **Custom period**.
- [x] Make the selected scope, time period, format, and matching-record count
  visible before download.
- [x] Keep CSV as a clean raw-data export with the columns `Fecha`, `Hora`,
  `Volts`, `mAmp`, and `Frec`, in that order. Do not add summary/footer rows.
- [x] Split timestamps into a sortable `Fecha` value formatted as `YYYY-MM-DD`
  and `Hora` formatted as `HH:mm:ss`.
- [x] Exclude connection status from management CSV/XLSX columns while keeping
  the complete timestamp, connection state, and quality information in SQLite
  for internal diagnostics.
- [x] Generate one XLSX workbook with a **Raw Data** worksheet containing the
  same selected raw readings as CSV and a separate **Report** worksheet.
- [x] In **Report**, provide the parameter names and units but leave the
  minimum/maximum limit cells empty and visibly editable for employees.
- [x] Validate report limit inputs as numeric values and treat blanks as
  **Not configured**, never as zero.
- [x] Calculate averages from positive readings only so missing/incomplete zero
  values do not distort the report.
- [x] Preserve production-pause readings in Raw Data. Exclude zero/near-zero
  Volts and mAmp from production averages while retaining received frequency,
  and report paused duration separately from disconnection time.
- [x] Add report start/end time, record counts, valid-reading counts, and
  per-parameter out-of-range counts.
- [x] Add separate Voltage, mAmp, and Frequency charts. Each chart must show the
  measured series and display its minimum/maximum limit lines only after the
  employee configures both limits.
- [x] Let operators choose Automatic, 1, 5, 10, 15, or 30-minute resolution
  for exported XLSX charts. Keep Raw Data and report statistics complete,
  average each manual time bucket, and preserve detected production-pause
  points in the chart helper data.
- [x] Keep formula/helper columns hidden and preserve all selected raw readings
  even when the Report excludes invalid readings from calculations.
- [x] Protect against Excel's 1,048,576-row worksheet limit by requiring a
  smaller range, splitting large XLSX history by period, or directing the user
  to CSV without interrupting collection.
### Phase 6E — Validation and production-PC review

- [ ] Test the approved implementation at the production PC's screen size and
  browser zoom.
- [ ] Verify keyboard operation, readable Spanish operator labels, contrast,
  focus states, and non-color status cues.
- [ ] Verify all Phase 6 export scopes while collection continues.
- [ ] Review the finished phase with a normal operator and manager before final
  merge.

### Phase 6 acceptance criteria

- The approved mockup is reviewed before production UI code changes begin.
- A normal operator can understand live state, inspect history, and start the
  correct download without seeing backend terminology.
- A planned production stop remains **Connected** and is shown separately as
  **Production paused** when Volts and mAmp are zero/near zero but frequency is
  still being received.
- Chart, Recent Readings, matching count, and filtered export use the same
  selected time range.
- Historical export includes every selected stored record, including gaps and
  incomplete readings; current-workday export uses the configured workday start.
- CSV contains only the five clean raw-data columns and no calculated summary
  rows.
- XLSX contains **Raw Data** and **Report** worksheets; the raw sheet reconciles
  exactly to CSV for the same scope.
- Entering report limits recalculates statuses, out-of-range counts, and chart
  limit lines without modifying raw data.
- Exported dates and times remain sortable and preserve seconds.
- Exporting and UI filtering never pause, change, or discard collection.
- The confirmed local-only dashboard binding and read-only Modbus function `04`
  behavior remain unchanged.

### Phase 6F and later — Approved future refinements

- [ ] Record new UI/UX ideas discovered after Phase 6A here, then prioritize
  them only after the approved Phase 6A–6E work is stable.
- [ ] Replace the labeled logo placeholder and add the approved application
  icon and browser favicon when the company brand assets are supplied.
- [ ] Keep a Power BI-ready export documented as an inactive future option; do
  not expose it in the Phase 6 application UI.
- [ ] Revisit the approved mockup colors after operational behavior and
  reporting are stable; color changes must preserve contrast and non-color
  status cues.

Phase 6 changes presentation, history interaction, and export formatting only.
It must not change the confirmed device protocol or safety constraints.

---

## Phase 7 — Runtime reliability

Goal: Operate unattended on the factory PC.

- [ ] Verify automatic reconnection after the Ethernet cable is disconnected.
- [ ] Verify automatic reconnection after the NT1-B is rebooted.
- [ ] Verify recovery after Windows sleep or network-adapter reset.
- [ ] Add graceful shutdown and confirm queued records are flushed.
- [ ] Add health information for the collector, storage writer, and last valid
  reading.
- [ ] Add structured operational logs with timestamps and severity.
- [ ] Use Windows Task Scheduler for the initial unattended deployment and
  provide an installation script that creates or updates the task safely.
- [ ] Start the collector every day at `05:50` so it is ready before production
  begins at `06:00`.
- [ ] Configure **Run task as soon as possible after a scheduled start is
  missed** and **Wake the computer to run this task** where company policy
  permits it.
- [ ] Add a Windows startup or user-logon trigger so a restart also returns the
  collector to service without waiting until the following day.
- [ ] Document that the initial portable deployment requires the dedicated
  Windows operator account to remain signed in; locking the session is allowed.
- [ ] Keep reconnecting safely when the task starts before the VFREG/NT1-B is
  powered or reachable.
- [ ] Avoid opening duplicate dashboard or collector processes.
- [ ] Configure the scheduled task to keep the existing instance instead of
  launching another one when the collector is already running.
- [ ] Provide a safe manual stop/restart procedure.

### Acceptance criteria

- The application resumes collection without operator intervention after a
  temporary network interruption.
- A Windows restart returns the collector to service automatically.
- With the PC left powered on and the operator account signed in, the collector
  starts by `05:50`, becomes ready before `06:00`, and remains functional while
  the Windows session is locked.
- A missed trigger or unavailable VFREG does not require someone in the room:
  Windows starts the task when possible and the collector reconnects when the
  device becomes reachable.
- Running the scheduled task again never creates a second collector instance.
- Normal shutdown leaves no pending SQLite WAL files or lost queued records.

---

## Phase 8 — Packaging and deployment

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

## Phase 9 — Security and industrial safeguards

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

## Phase 10 — Production validation

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

## Phase 11 — Documentation and ownership

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

- [x] Private repository and pilot baseline tag exist.
- [x] Reproducible `uv` environment and lockfile exist.
- [x] Automated tests pass.
- [x] Read-only Modbus behavior is verified.
- [x] Historical filtering and filtered exports work.
- [ ] Reconnection and automatic startup work.
- [x] Retention, backup, and recovery are documented and tested.
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
| 2026-08-24 | Preserve the successful pilot before further restructuring | Protect the proven device integration | MC95 |
| 2026-08-24 | Use a private GitHub repository named `vfreg-visor-sofia` | Keep source and releases controlled and recoverable | MC95 |
| 2026-08-24 | Keep production Modbus communication read-only | Protect the electrical process and equipment | MC95 |
| 2026-08-24 | Use `uv` for development and PyInstaller for Windows deployment | Reproducible development plus offline operation | MC95 |
| 2026-08-24 | Support Python 3.13 for the production-ready development baseline | Match the successfully tested development and Windows build environment | MC95 |
| 2026-08-24 | Use `src/vfreg_visor` with one production CLI entry point | Separate responsibilities while keeping the confirmed device protocol unchanged | MC95 |
| 2026-08-25 | Make operator UI/UX and management reporting Phase 6, starting with an approved static mockup | Validate the experience before changing the proven production dashboard | MC95 |
| 2026-08-25 | Keep CSV raw and generate XLSX with separate Raw Data and Report worksheets | Preserve audit-ready readings while giving management summaries and charts | MC95 |
| 2026-08-25 | Leave XLSX report limits empty and employee-configurable | Allow each work period to use approved operational limits without altering raw data | MC95 |
| 2026-08-25 | Keep Power BI integration inactive as a documented future option | Prioritize the formats employees currently use | MC95 |
| 2026-08-25 | Approve the Phase 6A mockup and proceed to Phase 6B, with final color refinement deferred | The structure and interaction are approved; operational behavior has priority over visual polish | MC95 |
| 2026-08-25 | Treat zero/near-zero Volts and mAmp with continuing frequency as Production paused while Connected | This condition was observed during the 2026-08-21 factory stop and must not be mistaken for disconnection or missing data | MC95 |
| 2026-08-25 | Keep Phase 6B pause detection in the dashboard layer and preserve every raw reading | Improve operator guidance without changing the confirmed collector, protocol, or stored evidence | MC95 |
