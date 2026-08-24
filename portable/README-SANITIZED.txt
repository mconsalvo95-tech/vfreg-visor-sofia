VFREG-VISOR-SOFIA - SANITIZED RELEASE
=====================================

This package contains the complete VFREG Visor application but does not contain
deployment-specific hardware identifiers or production measurements.

BEFORE USING IT IN THE FACTORY
------------------------------
1. Obtain the approved config.factory.json from the secure deployment backup.
2. Replace the template config.factory.json in this folder with that approved
   deployment file.
3. Configure only the dedicated Ethernet adapter according to the approved
   company installation procedure.
4. Verify the device connection before starting production collection.

START
-----
From PowerShell opened in this folder:

  & ".\VFREG-VISOR-SOFIA.exe" --config ".\config.factory.json"

Then open:

  http://127.0.0.1:8000

Keep the collector window open. Press Ctrl+C to stop it safely.

DATA
----
Runtime measurements and exports are written under data\factory. They are not
included in this release archive.
