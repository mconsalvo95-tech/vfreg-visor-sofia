from __future__ import annotations

import json
import time

from network_listener import parse_payload
from simulator_sender import build_packet
from storage import StorageWriter


def main() -> None:
    with open("config.json", "r", encoding="utf-8") as handle:
        cfg = json.load(handle)
    rate = float(cfg["simulator"]["readings_per_second"])
    writer = StorageWriter(cfg["output_sqlite"], cfg["raw_journal"])
    print("Writing simulated readings directly to local storage. Press Ctrl+C to stop.")
    try:
        sequence = 1
        while True:
            packet = build_packet(sequence, cfg, "mixed")
            payload = json.dumps(packet).encode("utf-8")
            row = parse_payload(payload, cfg, protocol="local", source_ip="127.0.0.1")
            writer.submit_measurement(row)
            print(row)
            sequence += 1
            time.sleep(1 / rate)
    except KeyboardInterrupt:
        print("\nSimulator stopped.")
    finally:
        writer.close()


if __name__ == "__main__":
    main()
