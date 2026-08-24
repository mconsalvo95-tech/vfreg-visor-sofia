# Reproduce the VFREG development environment

This guide is for a development computer. A factory operator computer should
receive the tested portable ZIP; that package needs no Python, `uv`, Git, IDE,
internet access, or Wireshark.

The authoritative runtime configuration is `config.factory.json`. It is a local
deployment file and is not stored in source control. `pyproject.toml`,
`uv.lock`, and `.python-version` are the authoritative development-environment
files. They pin Python 3.13 and all runtime/build dependencies.

## 1. Clone and configure the project

Clone the private repository on the new development computer. Do not copy
`.venv`, `data`, factory packet captures, or a real `config.factory.json`.
Create the local configuration from the safe template and review it before
connecting factory equipment:

```powershell
Copy-Item config.example.json config.factory.json
```

The safe template contains the confirmed read-only Modbus mapping but excludes
deployment-specific hardware identifiers and production data.

## 2. Install the locked environment once

Install `uv` using its official Windows instructions, then open a new
PowerShell window so its PATH change is visible:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

From the project directory, the complete setup command is:

```powershell
uv sync --locked
```

Alternatively, double-click `setup_new_notebook.bat`. It performs the same
locked sync and then runs the factory preflight. `uv` installs the pinned Python
version and creates `.venv`; do not manually install individual packages with
`pip`. Temporary internet access is required for the first uncached setup.

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
connected separately. The software never guesses or changes the adapter.

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
XLSX contains the same columns plus Charts and a hidden sampled chart-data
worksheet. All readings remain complete in the Readings worksheet; technical
evidence remains in SQLite and the raw JSONL journal.

## 5. Standard verification and build commands

Run the complete automated test suite:

```powershell
uv run --locked python -m unittest discover -s tests -v
```

Build the portable Windows folder and transfer ZIP:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\build_portable.ps1
```

The build uses only the locked environment. It does not require manually
installing PyInstaller or any other library.
