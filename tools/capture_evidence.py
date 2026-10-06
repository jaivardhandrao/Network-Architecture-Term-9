#!/usr/bin/env python3
"""Reproduce live request/response bytes and the connection-reuse demonstration."""

import hashlib
import json
from pathlib import Path
import platform
import re
import socket
import struct
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "evidence"


def read_exact(sock, count):
    result = b""
    while len(result) < count:
        part = sock.recv(count - len(result))
        if not part:
            raise RuntimeError("unexpected EOF")
        result += part
    return result


def read_frame(sock):
    header = read_exact(sock, 8)
    return header + read_exact(sock, int.from_bytes(header[:4], "big"))


def request(request_id):
    path = b"/hello.txt"
    payload = b"\x01" + len(path).to_bytes(2, "big") + path + b"\x00"
    return struct.pack("!IBBH", len(payload), 1, 0, request_id) + payload


def captured_frames(trace):
    frames, current = [], None
    for line in trace.splitlines():
        if line.startswith(("> REQUEST", "< FRAME")):
            current = bytearray()
            frames.append(current)
        elif current is not None and re.match(r"^[0-9a-f]+  ", line):
            hex_bytes = line.split("  ", 1)[1].split("  |", 1)[0]
            current.extend(bytes.fromhex(hex_bytes))
    return [bytes(frame) for frame in frames]


def main():
    OUTPUT.mkdir(exist_ok=True)
    process = subprocess.Popen([sys.executable, "./bserve", "./www", "0"], cwd=ROOT, stderr=subprocess.PIPE, text=True)
    logs, outcomes = [], {}
    try:
        first_line = process.stderr.readline()
        match = re.search(r"LISTEN 127\.0\.0\.1:(\d+)", first_line)
        if not match:
            raise RuntimeError("server did not report a listening address")
        port = int(match[1])
        logs.append(first_line)
        url = f"127.0.0.1:{port}/hello.txt"
        run = subprocess.run([sys.executable, str(ROOT / "bcurl"), "-v", url], capture_output=True, timeout=5)
        expected = (ROOT / "www/hello.txt").read_bytes()
        assert run.returncode == 0 and run.stdout == expected
        trace = run.stderr.decode()
        request_bytes, response_bytes = captured_frames(trace)
        assert len(request_bytes) == 8 + int.from_bytes(request_bytes[:4], "big")
        assert len(response_bytes) == 8 + int.from_bytes(response_bytes[:4], "big")
        (OUTPUT / "request.bin").write_bytes(request_bytes)
        (OUTPUT / "response.bin").write_bytes(response_bytes)
        (OUTPUT / "live-exchange.txt").write_text(f"$ ./bserve ./www {port}\n$ ./bcurl -v {url}\n" + trace + "\nSTDOUT\n" + run.stdout.decode() + f"EXIT {run.returncode}\n")
        outcomes["complete_exchange"] = {"request_bytes": len(request_bytes), "response_bytes": len(response_bytes), "stdout_sha256": hashlib.sha256(run.stdout).hexdigest(), "file_sha256": hashlib.sha256(expected).hexdigest(), "exit": run.returncode}

        reuse = subprocess.run([sys.executable, str(ROOT / "bcurl"), "-v", url, url], capture_output=True, timeout=5)
        assert reuse.returncode == 0 and reuse.stdout == expected * 2
        (OUTPUT / "connection-reuse.txt").write_text(f"$ ./bcurl -v {url} {url}\n" + reuse.stderr.decode() + "\nSTDOUT\n" + reuse.stdout.decode() + f"EXIT {reuse.returncode}\n")
        outcomes["connection_reuse"] = {"requests": 2, "response_frames": reuse.stderr.count(b"< FRAME"), "body_matches": True, "exit": reuse.returncode}

        with socket.create_connection(("127.0.0.1", port), timeout=2) as sock:
            extension = struct.pack("!IBBH", 6, 239, 255, 0) + b"future"
            sock.sendall(extension + request(3))
            reply = read_frame(sock)
            assert int.from_bytes(reply[8:10], "big") == 200
            malformed = struct.pack("!IBBH", 2, 1, 0, 4) + b"\x01\x00"
            sock.sendall(malformed)
            assert int.from_bytes(read_frame(sock)[8:10], "big") == 400
            sock.sendall(request(5))
            assert int.from_bytes(read_frame(sock)[8:10], "big") == 200
        outcomes["unknown_and_malformed_recovery"] = {"unknown_type": 239, "payload_discarded": 6, "statuses_on_same_connection": [200, 400, 200]}
        outcomes["environment"] = {"python": platform.python_version(), "os": platform.system(), "machine": platform.machine(), "transport": "IPv4 TCP loopback", "port": port}
    finally:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        logs.append(process.stderr.read())
        process.stderr.close()
    server_log = "".join(logs)
    (OUTPUT / "server-log.txt").write_text(server_log)
    # Three demonstrations above use exactly three successful connections.
    assert server_log.count("CONNECT ") == 3
    outcomes["accepted_tcp_connections"] = 3
    (OUTPUT / "results.json").write_text(json.dumps(outcomes, indent=2) + "\n")
    print(json.dumps(outcomes, indent=2))


if __name__ == "__main__":
    main()
