"""BHTTP/1 wire codec. See docs/protocol-spec.pdf for the normative contract."""

import re
import struct
from dataclasses import dataclass

REQUEST, RESPONSE = 1, 2
MAX_PAYLOAD = 1_048_576
MAX_FILE = 1_000_000
HEADER = struct.Struct("!IBBH")
NAMES = (
    "host", "user-agent", "accept", "content-type", "content-length",
    "server", "connection", "cache-control", "x-request-id", "x-course",
)
NAME_IDS = {name: index + 1 for index, name in enumerate(NAMES)}
TOKEN = re.compile(r"[!#$%&'*+.^_`|~0-9a-z-]+\Z")


class ProtocolError(ValueError):
    def __init__(self, message, request_id=0, fatal=False, status=400):
        super().__init__(message)
        self.request_id, self.fatal, self.status = request_id, fatal, status


@dataclass(frozen=True)
class Frame:
    kind: int
    flags: int
    request_id: int
    payload: bytes

    def to_bytes(self):
        if len(self.payload) > MAX_PAYLOAD:
            raise ProtocolError("payload exceeds 1048576 bytes", status=413)
        return HEADER.pack(len(self.payload), self.kind, self.flags, self.request_id) + self.payload


def read_exact(sock, count, *, clean_eof=False, request_id=0):
    result = bytearray()
    while len(result) < count:
        chunk = sock.recv(count - len(result))
        if not chunk:
            if clean_eof and not result:
                return None
            raise ProtocolError("truncated frame", request_id, fatal=True)
        result.extend(chunk)
    return bytes(result)


def read_frame(sock):
    raw = read_exact(sock, HEADER.size, clean_eof=True)
    if raw is None:
        return None
    length, kind, flags, request_id = HEADER.unpack(raw)
    if length > MAX_PAYLOAD:
        raise ProtocolError("payload exceeds 1048576 bytes", request_id, fatal=True, status=413)
    payload = read_exact(sock, length, request_id=request_id)
    return Frame(kind, flags, request_id, payload)


class Cursor:
    def __init__(self, data):
        self.data, self.pos = data, 0

    def take(self, count):
        if self.pos + count > len(self.data):
            raise ProtocolError("payload field is truncated")
        value = self.data[self.pos:self.pos + count]
        self.pos += count
        return value

    def number(self, count):
        return int.from_bytes(self.take(count), "big")

    def finish(self):
        if self.pos != len(self.data):
            raise ProtocolError("unexpected trailing payload bytes")


def text(raw):
    try:
        return raw.decode("utf-8", "strict")
    except UnicodeDecodeError as exc:
        raise ProtocolError("text is not valid UTF-8") from exc


def check_header(name, value):
    if not TOKEN.fullmatch(name) or len(name.encode("ascii")) > 64:
        raise ProtocolError("invalid lowercase ASCII header name")
    if len(value.encode("utf-8")) > 4096 or any(ord(c) < 32 and c != "\t" or ord(c) == 127 for c in value):
        raise ProtocolError("invalid header value")


def encode_headers(headers):
    if len(headers) > 32:
        raise ProtocolError("more than 32 headers")
    output = bytearray([len(headers)])
    for name, value in headers.items():
        check_header(name, value)
        name_id = NAME_IDS.get(name, 0)
        output.append(name_id)
        if name_id == 0:
            raw_name = name.encode("ascii")
            output.append(len(raw_name))
            output.extend(raw_name)
        raw_value = value.encode("utf-8")
        output.extend(struct.pack("!H", len(raw_value)))
        output.extend(raw_value)
    return bytes(output)


def decode_headers(cursor):
    count = cursor.number(1)
    if count > 32:
        raise ProtocolError("more than 32 headers")
    headers = {}
    for _ in range(count):
        name_id = cursor.number(1)
        if name_id == 0:
            name = text(cursor.take(cursor.number(1)))
        elif name_id <= len(NAMES):
            name = NAMES[name_id - 1]
        else:
            raise ProtocolError("unassigned header name ID")
        value = text(cursor.take(cursor.number(2)))
        check_header(name, value)
        if name in headers:
            raise ProtocolError("duplicate header name")
        headers[name] = value
    return headers


def decode_request(frame):
    if frame.kind != REQUEST or frame.request_id == 0:
        raise ProtocolError("expected REQUEST with nonzero request ID")
    cursor = Cursor(frame.payload)
    method, path_length = cursor.number(1), cursor.number(2)
    if not 1 <= path_length <= 4096:
        raise ProtocolError("invalid path length")
    path = text(cursor.take(path_length))
    if not path.startswith("/") or any(ord(c) < 32 or ord(c) == 127 for c in path):
        raise ProtocolError("invalid origin path")
    headers = decode_headers(cursor)
    cursor.finish()
    return method, path, headers


def encode_response(status, headers, body, request_id):
    if not 100 <= status <= 599:
        raise ProtocolError("invalid status")
    payload = struct.pack("!H", status) + encode_headers(headers) + struct.pack("!I", len(body)) + body
    return Frame(RESPONSE, 0, request_id, payload)


