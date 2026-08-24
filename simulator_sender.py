from __future__ import annotations

import argparse
import json
import math
import random
import socket
import time
from datetime import datetime


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


def load_config(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def build_packet(sequence: int, cfg: dict, scenario: str = "normal") -> dict:
    simulator = cfg["simulator"]
    phase = sequence / 10
    voltage = float(simulator["base_voltage_v"]) + math.sin(phase) * 2.2
    current = float(simulator["base_current_ma"]) + math.sin(phase * 0.7) * 65
    frequency = float(simulator["base_frequency_hz"]) + math.cos(phase * 0.4) * 7
    line_status = "RUNNING"

    if scenario == "mixed":
        cycle = sequence % 80
        if 48 <= cycle < 56:
            current += 520
        elif 64 <= cycle < 70:
            line_status = "STOPPED"
            voltage = current = frequency = 0

    if line_status == "RUNNING":
        voltage += random.uniform(-0.35, 0.35)
        current += random.uniform(-5, 5)
        frequency += random.uniform(-0.8, 0.8)

    return {
        "protocol_version": 1,
        "device_id": simulator.get("device_id", cfg["device_name"]),
        "sequence": sequence,
        "measured_at": now_iso(),
        "voltage_v": round(voltage, 2),
        "current_ma": round(current, 1),
        "frequency_hz": round(frequency, 1),
        "line_status": line_status,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Send simulated VFREG measurements")
    parser.add_argument("--config", default="config.json")
    parser.add_argument("--host", help="Collector IP address")
    parser.add_argument("--port", type=int)
    parser.add_argument("--protocol", choices=("udp", "tcp"))
    parser.add_argument("--rate", type=float, help="Readings per second")
    parser.add_argument("--duration", type=float, default=0, help="Seconds; 0 runs until stopped")
    parser.add_argument("--scenario", choices=("normal", "mixed"), default="mixed")
    parser.add_argument("--quiet", action="store_true", help="Suppress per-reading console output")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    cfg = load_config(args.config)
    simulator = cfg["simulator"]
    protocol = args.protocol or simulator["protocol"]
    host = args.host or simulator["target_host"]
    port = args.port or int(cfg["network"][f"{protocol}_port"])
    rate = args.rate or float(simulator["readings_per_second"])
    interval = 1 / rate
    deadline = time.monotonic() + args.duration if args.duration > 0 else None
    sequence = 1

    socket_type = socket.SOCK_DGRAM if protocol == "udp" else socket.SOCK_STREAM
    with socket.socket(socket.AF_INET, socket_type) as sender:
        if protocol == "tcp":
            sender.connect((host, port))
        print(f"VFREG simulator sending {rate:g}/s via {protocol.upper()} to {host}:{port}")
        try:
            while deadline is None or time.monotonic() < deadline:
                packet = build_packet(sequence, cfg, args.scenario)
                encoded = json.dumps(packet, separators=(",", ":")).encode("utf-8")
                if protocol == "udp":
                    sender.sendto(encoded, (host, port))
                else:
                    sender.sendall(encoded + b"\n")
                if not args.quiet:
                    print(
                        f"#{sequence:05d} {packet['voltage_v']:6.2f} V  "
                        f"{packet['current_ma']:7.1f} mA  {packet['frequency_hz']:6.1f} Hz  "
                        f"{packet['line_status']}"
                    )
                sequence += 1
                time.sleep(interval)
        except KeyboardInterrupt:
            print("\nSimulator stopped.")


if __name__ == "__main__":
    main()
