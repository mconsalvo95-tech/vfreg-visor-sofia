# VFREG factory collector

Offline test bench and field collector for the poultry stunning monitor project.
It records the electrical condition of the water bath over time: voltage in
volts, current in milliamps, and frequency in hertz. It does not attempt to
associate a measurement with an individual bird.

## What is ready

- TCP and UDP listeners with connection, disconnect, duplicate, and sequence-gap events.
- Queued SQLite storage in WAL mode so network reception is not blocked by disk writes.
- A raw JSONL packet journal containing the original bytes, source, protocol, and SHA-256.
- Automatic raw-journal rotation: five 100 MB backups by default.
- Preservation of unknown binary packets as `RAW_ONLY` instead of dropping them.
- Collector receipt time, device time, source address, batch, shift, and alarm status.
- Simplified live dashboard showing time, Volts, mAmp, frequency, connection
  status, recent readings, and a live three-lane trend chart.
- Management CSV and XLSX exports containing only Time, Volts, mAmp, Frec, and
  Status, with no 5,000-record cap. XLSX includes a separate Charts worksheet
  for voltage, current, and frequency. Full technical evidence stays in the
  SQLite database and raw JSONL journal.
- In-place migration of databases created by the earlier prototype.

Port `5000` and the simulated JSON message format remain test assumptions only
for `config.json`. Confirmed real-device settings are isolated in
`config.factory.json`.

`config.factory.json` is a local deployment file and is intentionally excluded
from source control. After a clean clone, create it from the safe template:

```powershell
Copy-Item config.example.json config.factory.json
```

Review the copied file before connecting to factory equipment. The template
contains the confirmed read-only Modbus mapping but excludes deployment-specific
hardware identifiers and production data.

## Reproducible development environment

This project uses Python 3.13 and `uv`. The authoritative dependency files are
`pyproject.toml` and the committed `uv.lock`; do not install individual packages
with `pip`.

After installing `uv`, the complete setup command is:

```powershell
uv sync --locked
```

The `dev` dependency group, installed by default, contains PyInstaller. Runtime
dependencies remain separate. The portable company-PC package is different: it
already contains Python and does not require Python, `uv`, Git, an IDE, or an
internet connection.

## Confirmed factory protocol (2026-08-21)

The real viewer protocol has been correlated with its physical display:

- Ethernet module: Ebyte NT1-B at `192.168.1.7`, MAC `54:14:a7:87:cf:95`.
- Transport: TCP server on confirmed port `502`; the collector is the client.
- Serial settings observed in the NT1-B: 9600 baud, 8 data bits, even parity, 1 stop bit.
- Modbus slave `5`, function `04` (Read Input Registers).
- Register `0` = Volts, `1` = mAMPs, and `2` = FREC.
- Scale `1` for all three values, confirmed against the viewer.

The first correlated response happened to contain `37 / 425 / 203`; those are
not hardcoded values. The factory collector polls all three live registers every
configured interval and records their variation. The dashboard can change the
read-only polling interval between 0.5, 1, 5, 15, 30, and 60 seconds without changing
the NT1-B or panel. The selection is saved in `config.factory.json` and survives
restarts. Longer intervals reduce storage but can miss brief variations. Process
alarm limits are intentionally disabled until the factory supplies confirmed
acceptable ranges.

Run `run_factory_preflight.bat`, then start the real collector with
`start_factory_collector.bat`. Open `http://127.0.0.1:8000`. Factory data is kept
separate from simulator data under `data/factory/`.

For a second development notebook, clone this project, create the local factory
configuration, and run `setup_new_notebook.bat`. `NEW_NOTEBOOK_SETUP.md`
contains the complete procedure. For a factory operator computer, transfer the
tested portable ZIP instead of the source tree.

## Start the collector notebook

Before a factory session, run the offline preflight:

```powershell
uv run --locked python preflight.py
```

Or double-click `run_preflight.bat`. The report checks the configured TCP and
UDP ports (whatever values are currently in `config.json`), storage, free disk
space, clock/timezone, Excel dependency, local IPv4 addresses, and TCP framing.
Firewall reachability remains a clearly marked manual check because a local
bind test cannot prove that packets from the VFREG can cross Windows Firewall.
Save a machine-readable copy with
`uv run --locked python preflight.py --json --output report.json`.

From PowerShell in this directory:

```powershell
uv run --locked python app.py
```

On Windows, `install_dependencies.bat` performs the locked sync and
`start_collector.bat` launches the simulator configuration from the correct
directory.

Then open `http://127.0.0.1:8000` on the same notebook. The listener binds to all
network interfaces, while the dashboard intentionally remains local to the
notebook. Use the Factory Mode fields to set the production batch and shift;
new packets will carry those labels in the database and exports.

## Repeat the home-network test

Run the collector on the notebook. On the desktop, send data to the notebook's
LAN address:

```powershell
python simulator_sender.py --host NOTEBOOK_IP --protocol tcp --scenario mixed
```

Wireshark can verify the route with the display filter:

```text
tcp.port == 5000
```

The same test can use `--protocol udp` and `udp.port == 5000`.

## Factory visit

1. Run Wireshark before connecting the VFREG and capture the notebook Ethernet interface.
2. Connect the VFREG directly to the notebook with Ethernet.
3. Start `app.py` and keep the dashboard open.
4. Confirm the actual VFREG IP, destination IP, protocol, port, and whether payload bytes are visible.
5. Save the `.pcapng`, the `data/raw_packets.jsonl` journal, and an XLSX export.
6. Do not mark `port_confirmed` as `true` until the real capture proves the port.

If the VFREG emits an unknown binary format, the dashboard will show `RAW DATA`.
That is a useful capture, not a failed collection: the original bytes remain in
the raw journal for decoder development.

## Files and durability

- `data/readings.sqlite`: authoritative measurements and collector events.
- `data/raw_packets.jsonl`: append-only packet evidence, with rotated backups.
- `data/readings.csv`: generated when CSV is downloaded.
- `data/readings.xlsx`: generated when XLSX is downloaded.

Storage queue size, journal size, and backup count are configured under
`storage` in `config.json`. The dashboard reports listener health, queue depth,
decode counts, received bytes, source address, and sequence gaps.

## Simulator packet

```json
{
  "protocol_version": 1,
  "device_id": "VFREG-SIM",
  "sequence": 42,
  "measured_at": "2026-08-03T15:04:05.123-03:00",
  "voltage_v": 115.2,
  "current_ma": 1204.5,
  "frequency_hz": 799.8,
  "line_status": "RUNNING"
}
```

## Verification

```powershell
uv run --locked python -m unittest discover -s tests -v
```

Build the portable Windows folder and ZIP with one command:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\build_portable.ps1
```
