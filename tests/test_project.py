"""Live TCP tests plus independent peers that never import the project codec."""

import importlib.machinery
import importlib.util
import os
from pathlib import Path
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import bhttp


def load_script(name):
    loader = importlib.machinery.SourceFileLoader(name, str(ROOT / name))
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


bserve = load_script("bserve")


# Independent encoder/decoder derived from the published wire contract.
def peer_field(name_id, value, name=None):
    raw = value.encode()
    prefix = bytes([name_id])
    if name_id == 0:
        name_bytes = name.encode()
        prefix += bytes([len(name_bytes)]) + name_bytes
    return prefix + len(raw).to_bytes(2, "big") + raw


def peer_frame(kind, request_id, payload, flags=0):
    return struct.pack("!IBBH", len(payload), kind, flags, request_id) + payload


def peer_request(path="/hello.txt", request_id=1, method=1):
    raw = path.encode()
    payload = bytes([method]) + len(raw).to_bytes(2, "big") + raw
    return peer_frame(1, request_id, payload + bytes([1]) + peer_field(1, "localhost"))


def peer_exact(sock, count):
    output = b""
    while len(output) < count:
        piece = sock.recv(count - len(output))
        if not piece:
            raise AssertionError("unexpected EOF at independent peer")
        output += piece
    return output


def peer_receive(sock):
    raw = peer_exact(sock, 8)
    length, kind, flags, request_id = struct.unpack("!IBBH", raw)
    payload = peer_exact(sock, length)
    return kind, request_id, payload, raw + payload


def peer_response(payload):
    status = int.from_bytes(payload[:2], "big")
    count, position, headers = payload[2], 3, {}
    names = ["host", "user-agent", "accept", "content-type", "content-length", "server", "connection", "cache-control", "x-request-id", "x-course"]
    for _ in range(count):
        name_id = payload[position]
        position += 1
        if name_id == 0:
            name_length = payload[position]
            position += 1
            name = payload[position:position + name_length].decode()
            position += name_length
        else:
            name = names[name_id - 1]
        value_length = int.from_bytes(payload[position:position + 2], "big")
        position += 2
        headers[name] = payload[position:position + value_length].decode()
        position += value_length
    body_length = int.from_bytes(payload[position:position + 4], "big")
    body = payload[position + 4:]
    assert len(body) == body_length
    assert headers["content-length"] == str(body_length)
    return status, headers, body


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        (cls.root / "hello.txt").write_bytes(b"Hello, binary HTTP!\n")
        (cls.root / "index.html").write_bytes(b"INDEX\n")
        (cls.root / "empty").write_bytes(b"")
        (cls.root / "bytes.bin").write_bytes(bytes(range(256)))
        (cls.root / "caf\u00e9.txt").write_bytes("caf\u00e9\n".encode())
        (cls.root / "large").write_bytes(b"x" * (bhttp.MAX_FILE + 1))
        (cls.root / "directory").mkdir()
        os.symlink("/etc/passwd", cls.root / "escape")
        cls.server = bserve.Server(("127.0.0.1", 0), bserve.Handler)
        cls.server.root = str(cls.root)
        cls.address = cls.server.server_address
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()
        cls.temp.cleanup()

    def connect(self):
        sock = socket.create_connection(self.address, timeout=2)
        self.addCleanup(sock.close)
        return sock

    def exchange(self, sock, request):
        sock.sendall(request)
        kind, request_id, payload, raw = peer_receive(sock)
        self.assertEqual(kind, 2)
        return request_id, peer_response(payload), raw

    def test_independent_request_and_indexed_literal_response(self):
        request_id, (status, headers, body), _ = self.exchange(self.connect(), peer_request())
        self.assertEqual((request_id, status, body), (1, 200, b"Hello, binary HTTP!\n"))
        self.assertEqual(headers["x-file-name"], "hello.txt")
        self.assertEqual(headers["connection"], "keep-alive")

    def test_two_requests_one_open_connection(self):
        sock = self.connect()
        for request_id in (1, 2):
            received, (status, _, _), _ = self.exchange(sock, peer_request(request_id=request_id))
            self.assertEqual((received, status), (request_id, 200))

    def test_coalesced_tcp_requests(self):
        sock = self.connect()
        sock.sendall(peer_request(request_id=1) + peer_request(request_id=2))
        self.assertEqual(peer_receive(sock)[1], 1)
        self.assertEqual(peer_receive(sock)[1], 2)

    def test_byte_at_a_time_tcp_delivery(self):
        sock = self.connect()
        for value in peer_request():
            sock.sendall(bytes([value]))
        self.assertEqual(peer_response(peer_receive(sock)[2])[0], 200)

    def test_unknown_frame_then_known_request(self):
        sock = self.connect()
        extension = peer_frame(239, 0, b"future-extension", flags=255)
        _, (status, _, body), _ = self.exchange(sock, extension + peer_request())
        self.assertEqual((status, body), (200, b"Hello, binary HTTP!\n"))

    def test_empty_unknown_frame_is_skipped(self):
        _, (status, _, _), _ = self.exchange(self.connect(), peer_frame(255, 0, b"") + peer_request())
        self.assertEqual(status, 200)

    def test_unknown_flags_are_ignored(self):
        data = bytearray(peer_request())
        data[5] = 128
        _, (status, _, _), _ = self.exchange(self.connect(), data)
        self.assertEqual(status, 200)

    def test_missing_file_404_then_success_same_connection(self):
        sock = self.connect()
        _, (status, _, _), _ = self.exchange(sock, peer_request("/missing"))
        self.assertEqual(status, 404)
        _, (status, _, _), _ = self.exchange(sock, peer_request(request_id=2))
        self.assertEqual(status, 200)

    def test_malformed_payload_400_then_success(self):
        sock = self.connect()
        _, (status, _, _), _ = self.exchange(sock, peer_frame(1, 7, b"\x01\x00\x10/"))
        self.assertEqual(status, 400)
        _, (status, _, _), _ = self.exchange(sock, peer_request(request_id=8))
        self.assertEqual(status, 200)

    def test_invalid_utf8_400(self):
        _, (status, _, _), _ = self.exchange(self.connect(), peer_frame(1, 1, b"\x01\x00\x02/\xff\x00"))
        self.assertEqual(status, 400)

    def test_duplicate_headers_400(self):
        payload = b"\x01\x00\x01/\x02" + peer_field(1, "a") + peer_field(1, "b")
        _, (status, _, _), _ = self.exchange(self.connect(), peer_frame(1, 1, payload))
        self.assertEqual(status, 400)

    def test_literal_request_header_and_utf8_value(self):
        payload = b"\x01\x00\x01/\x01" + peer_field(0, "caf\u00e9", "x-note")
        _, (status, _, body), _ = self.exchange(self.connect(), peer_frame(1, 1, payload))
        self.assertEqual((status, body), (200, b"INDEX\n"))

    def test_header_limits_controls_wrong_direction_and_zero_id(self):
        malformed = [
            peer_frame(1, 1, b"\x01\x00\x01/\x21"),
            peer_frame(1, 1, b"\x01\x00\x01/\x01" + peer_field(1, "x\r\ny")),
            peer_frame(1, 1, b"\x01\x00\x01/\x01" + peer_field(0, "x", "Upper")),
            peer_frame(1, 1, b"\x01\x00\x01/\x01" + peer_field(1, "x" * 4097)),
            peer_frame(2, 1, b""),
            peer_request(request_id=0),
        ]
        for wire in malformed:
            with self.subTest(wire=wire[:12]):
                self.assertEqual(self.exchange(self.connect(), wire)[1][0], 400)

    def test_missing_document_root_is_server_error(self):
        with self.assertRaises(bserve.FileStatus) as raised:
            bserve.get_file(self.root / "missing-root", "/")
        self.assertEqual(raised.exception.status, 500)

    def test_unassigned_header_id_400(self):
        _, (status, _, _), _ = self.exchange(self.connect(), peer_frame(1, 1, b"\x01\x00\x01/\x01\x0b\x00\x00"))
        self.assertEqual(status, 400)

    def test_trailing_payload_byte_400(self):
        request = peer_request()
        size = len(request) - 8
        request = struct.pack("!I", size + 1) + request[4:] + b"!"
        self.assertEqual(self.exchange(self.connect(), request)[1][0], 400)

    def test_oversize_advertisement_413_and_close(self):
        sock = self.connect()
        _, (status, headers, _), _ = self.exchange(sock, struct.pack("!IBBH", bhttp.MAX_PAYLOAD + 1, 1, 0, 4))
        self.assertEqual((status, headers["connection"]), (413, "close"))
        self.assertEqual(sock.recv(1), b"")

    def test_truncated_payload_after_half_close_400(self):
        sock = self.connect()
        sock.sendall(struct.pack("!IBBH", 10, 1, 0, 4) + b"x")
        sock.shutdown(socket.SHUT_WR)
        self.assertEqual(peer_response(peer_receive(sock)[2])[0], 400)
        self.assertEqual(sock.recv(1), b"")

    def test_truncated_header_after_half_close_400(self):
        sock = self.connect()
        sock.sendall(b"\x00\x00")
        sock.shutdown(socket.SHUT_WR)
        self.assertEqual(peer_response(peer_receive(sock)[2])[0], 400)

    def test_traversal_and_symlink_are_blocked(self):
        for path in ("/../etc/passwd", "/%2e%2e/etc/passwd", "/escape", "/..\\etc\\passwd"):
            with self.subTest(path=path):
                self.assertEqual(self.exchange(self.connect(), peer_request(path))[1][0], 403)

    def test_binary_empty_unicode_and_default_index(self):
        for path, expected in (("/bytes.bin", bytes(range(256))), ("/empty", b""), ("/caf%C3%A9.txt", "caf\u00e9\n".encode()), ("/", b"INDEX\n")):
            with self.subTest(path=path):
                _, (status, _, body), _ = self.exchange(self.connect(), peer_request(path))
                self.assertEqual((status, body), (200, expected))

    def test_non_get_405_directory_404_large_file_413(self):
        sock = self.connect()
        for request, expected in ((peer_request(method=2), 405), (peer_request("/directory", 2), 404), (peer_request("/large", 3), 413)):
            self.assertEqual(self.exchange(sock, request)[1][0], expected)

    def test_cli_body_only_and_error_exit(self):
        host, port = self.address
        base = f"{host}:{port}"
        ok = subprocess.run([sys.executable, str(ROOT / "bcurl"), base + "/bytes.bin"], capture_output=True, timeout=5)
        self.assertEqual((ok.returncode, ok.stdout, ok.stderr), (0, bytes(range(256)), b""))
        bad = subprocess.run([sys.executable, str(ROOT / "bcurl"), base + "/missing"], capture_output=True, timeout=5)
        self.assertEqual((bad.returncode, bad.stdout), (1, b"404\n"))


class ClientIndependentPeerTests(unittest.TestCase):
    def run_peer(self, requests=1, status=200, wrong_id=False, bad_length=False, close=False):
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        listener.settimeout(2)
        address = listener.getsockname()
        observations, errors = [], []

        def peer():
            try:
                sock, _ = listener.accept()
                with sock:
                    sock.settimeout(2)
                    for _ in range(requests):
                        kind, request_id, payload, _ = peer_receive(sock)
                        observations.append((kind, request_id, payload))
                        if close:
                            return
                        body = b"peer-body\x00\xff"
                        response_headers = b"\x02" + peer_field(5, str(len(body))) + peer_field(0, "independent", "x-peer")
                        reply = status.to_bytes(2, "big") + response_headers + (len(body) + int(bad_length)).to_bytes(4, "big") + body
                        extension = peer_frame(237, 0, b"opaque", 127)
                        wire = extension + peer_frame(2, request_id + int(wrong_id), reply)
                        for offset in range(0, len(wire), 3):
                            sock.sendall(wire[offset:offset + 3])
                    self.assertEqual(sock.recv(1), b"")
                # A second accepted TCP connection would violate the client rule.
                listener.settimeout(.15)
                try:
                    extra, _ = listener.accept()
                    extra.close()
                    errors.append("unexpected second connection")
                except socket.timeout:
                    pass
            except Exception as exc:
                errors.append(repr(exc))
            finally:
                listener.close()

        thread = threading.Thread(target=peer)
        thread.start()
        url = f"{address[0]}:{address[1]}/sample"
        result = subprocess.run([sys.executable, str(ROOT / "bcurl"), "-v"] + [url] * requests, capture_output=True, timeout=5)
        thread.join(3)
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        return result, observations

    def test_independent_server_unknown_types_fragmented_response(self):
        result, observed = self.run_peer(requests=2)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, b"peer-body\x00\xff" * 2)
        self.assertEqual([row[:2] for row in observed], [(1, 1), (1, 2)])
        self.assertEqual(result.stderr.count(b"> REQUEST"), 2)
        self.assertEqual(result.stderr.count(b"< FRAME"), 4)
        # Decode request path directly, without calling bhttp.decode_request.
        payload = observed[0][2]
        self.assertEqual(payload[0], 1)
        length = int.from_bytes(payload[1:3], "big")
        self.assertEqual(payload[3:3 + length], b"/sample")

    def test_500_body_written_and_exit_nonzero(self):
        result, _ = self.run_peer(status=500)
        self.assertEqual((result.returncode, result.stdout), (1, b"peer-body\x00\xff"))

    def test_wrong_response_id_rejected(self):
        result, _ = self.run_peer(wrong_id=True)
        self.assertEqual((result.returncode, result.stdout), (2, b""))

    def test_inconsistent_body_length_rejected(self):
        result, _ = self.run_peer(bad_length=True)
        self.assertEqual((result.returncode, result.stdout), (2, b""))

    def test_peer_close_does_not_retry(self):
        result, observed = self.run_peer(close=True)
        self.assertEqual((result.returncode, len(observed)), (2, 1))


if __name__ == "__main__":
    unittest.main(verbosity=2)
