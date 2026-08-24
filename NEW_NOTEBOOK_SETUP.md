# Replicate the VFREG collector on another notebook

The authoritative runtime configuration is `config.factory.json`. It is a local
deployment file and is not stored in source control. After cloning the project,
create it from the safe template:

```powershell
Copy-Item config.example.json config.factory.json
```

Review the copied configuration before connecting factory equipment. The
`pyproject.toml` manifest records the Python dependency and the confirmed
notebook, NT1-B, and Modbus settings in a machine-readable format.

## 1. Copy the project

Copy the complete `vfreg_logger_mvp` directory to the new notebook. The
existing `.venv` and `data` directories do not need to be copied. Do not use
the older package in `dist`; the working project directory is authoritative.

## 2. Install the software once

Install Python 3.10 or newer, including the Python launcher or the PATH option.
With temporary internet access, double-click:

```text
setup_new_notebook.bat
```

This creates an isolated `.venv`, installs the Excel dependency, and runs the
factory preflight. Later starts do not require internet access.

## 3. Configure the direct Ethernet adapter

The adapter name can differ between notebooks. In an elevated PowerShell:

```powershell
Get-NetAdapter | Format-Table Name, Status, MacAddress, LinkSpeed
```

After identifying the wired adapter, replace `Ethernet` below if necessary:

```powershell
netsh interface ipv4 set address name="Ethernet" source=static address=192.168.1.1 mask=255.255.255.0 gateway=none
Get-NetIPAddress -InterfaceAlias "Ethernet" -AddressFamily IPv4
```

Leave gateway and DNS blank on this direct VFREG connection. Wi-Fi may remain
connected separately.

## 4. Verify and start

Connect the NT1-B Ethernet cable, then run:

```powershell
ping 192.168.1.7
Test-NetConnection 192.168.1.7 -Port 502
```

Double-click `run_factory_preflight.bat`, then
`start_factory_collector.bat`. Open `http://127.0.0.1:8000`.

The confirmed runtime settings are Modbus TCP at `192.168.1.7:502`, unit 5,
function 04, registers 0-2. The runtime values are live and are never replaced
with the original discovery values.

CSV export contains the management columns Time, Volts, mAmp, Frec, and Status.
XLSX contains the same columns plus Summary, Charts, and a hidden sampled
chart-data worksheet. All readings remain complete in the Readings worksheet;
technical evidence remains in SQLite and the raw JSONL journal.
