"""PyInstaller adapter for the single VFREG application entry point."""

from vfreg_visor.cli import main


raise SystemExit(main())
