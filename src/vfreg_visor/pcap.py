from __future__ import annotations

import os
import socket
import struct
import sys
from collections import Counter


def mac(raw: bytes) -> str:
    return ":".join(f"{b:02x}" for b in raw)


def ip4(raw: bytes) -> str:
    return socket.inet_ntoa(raw)


def parse_pcapng(path: str) -> list[bytes]:
    data = open(path, "rb").read()
    off = 0
    endian = "<"
    packets: list[bytes] = []

    while off + 12 <= len(data):
        btype, blen = struct.unpack_from(endian + "II", data, off)
        if btype == 0x0A0D0D0A:
            magic = data[off + 8: off + 12]
            if magic == b"\x4d\x3c\x2b\x1a":
                endian = "<"
            elif magic == b"\x1a\x2b\x3c\x4d":
                endian = ">"
            btype, blen = struct.unpack_from(endian + "II", data, off)

        if blen < 12 or off + blen > len(data):
            break

        body = data[off + 8: off + blen - 4]
        if btype == 6 and len(body) >= 20:
            _iface_id, _tsh, _tsl, caplen, _pktlen = struct.unpack_from(endian + "IIIII", body, 0)
            packets.append(body[20:20 + caplen])

        off += blen

    return packets


def summarize(path: str) -> None:
    packets = parse_pcapng(path)
    eth = Counter()
    arp = Counter()
    ipv4 = Counter()
    tcp = Counter()
    udp = Counter()

    for p in packets:
        if len(p) < 14:
            continue
        dst = mac(p[0:6])
        src = mac(p[6:12])
        etype = struct.unpack("!H", p[12:14])[0]
        eth[(src, dst, hex(etype))] += 1

        if etype == 0x0806 and len(p) >= 42:
            _htype, _ptype, _hlen, _plen, oper = struct.unpack("!HHBBH", p[14:22])
            sha = mac(p[22:28])
            spa = ip4(p[28:32])
            tha = mac(p[32:38])
            tpa = ip4(p[38:42])
            arp[(oper, sha, spa, tha, tpa)] += 1

        if etype == 0x0800 and len(p) >= 34:
            ihl = (p[14] & 0x0F) * 4
            proto = p[23]
            src_ip = ip4(p[26:30])
            dst_ip = ip4(p[30:34])
            ipv4[(proto, src_ip, dst_ip)] += 1

            if proto == 6 and len(p) >= 14 + ihl + 20:
                sport, dport = struct.unpack("!HH", p[14 + ihl:14 + ihl + 4])
                tcp[(src_ip, dst_ip, sport, dport)] += 1
            elif proto == 17 and len(p) >= 14 + ihl + 8:
                sport, dport = struct.unpack("!HH", p[14 + ihl:14 + ihl + 4])
                udp[(src_ip, dst_ip, sport, dport)] += 1

    print("Archivo:", os.path.basename(path))
    print("Paquetes:", len(packets))

    print("\nEthernet top:")
    for item, count in eth.most_common(10):
        print(count, item)

    print("\nARP:")
    for item, count in arp.most_common(20):
        print(count, item)

    print("\nIPv4:")
    for item, count in ipv4.most_common(20):
        print(count, item)

    print("\nTCP:")
    for item, count in tcp.most_common(20):
        print(count, item)

    print("\nUDP:")
    for item, count in udp.most_common(20):
        print(count, item)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python pcap_summary.py archivo.pcapng")
        raise SystemExit(1)
    summarize(sys.argv[1])
