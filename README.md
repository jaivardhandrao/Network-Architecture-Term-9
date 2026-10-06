# Network Architecture Project

**HTTP in binary: a wire specification, static-file server, and command-line client.**

Jaivardhan D. Rao | 24BCS10117 | Term 9

The project implements BHTTP/1, a small custom binary protocol over TCP. The server and client have separate wire implementations. The client opens one socket and never reconnects. The server reuses a connection for successive requests. Both endpoints skip unknown frame types by length, preserving the next frame boundary.

## Required deliverables

1. [Two-page protocol specification](docs/protocol-spec.pdf) and its [editable text](docs/protocol-spec.md).
2. Server: [bserve](bserve) with its wire codec [bhttp.py](bhttp.py). Client: [bcurl](bcurl), which uses only the Python standard library and does not import server code.
3. [Annotated complete request and response](evidence/annotated-hexdump.pdf), [text annotations](evidence/annotated-hexdump.md), [request bytes](evidence/request.bin), [response bytes](evidence/response.bin), and [actual CLI output](evidence/live-exchange.txt).

Both tracks are provided so either program can be inspected and run. Actual classmate pairing and a peer-authored implementation must be coordinated separately; the included independent test peers demonstrate wire interoperability without shared codec imports.

## Run

Requires Python 3.10 or later on macOS or Linux. No dependencies, database, cloud service, or build step is required. The server uses read-only descriptor-based file access and does not follow symlinks.

From this repository, in the first terminal:

```bash
./bserve ./www 9000
```

In another terminal:

```bash
./bcurl -v localhost:9000/index.html
./bcurl localhost:9000/hello.txt
./bcurl -v localhost:9000/hello.txt localhost:9000/index.html
./bcurl localhost:9000/missing.txt
```

The final command outputs `404` and returns exit code 1. Body bytes go to stdout; verbose hexdumps go to stderr. Multiple URLs must share an origin, and their bodies are concatenated in order. The server defaults to loopback and stops with Ctrl-C. For an agreed local-network peer demonstration, use `./bserve ./www 9000 --host 0.0.0.0` and the machine's IPv4 address.

## Verification

```bash
python3 -m unittest discover -s tests -v
python3 tools/capture_evidence.py
```

The 28 tests exercise actual TCP, byte-at-a-time input, coalesced requests, independent peers, exact binary stdout, literal and indexed header names, keep-alive reuse, unknown extensions at both endpoints, 400/404/405/413/500 handling, UTF-8, duplicate fields, body lengths, mismatched IDs, traversal, symlink escapes, and peer shutdown without retry. See [test output](evidence/test-results.txt).

The [live results](evidence/results.json) record actual measured values. One exchange transferred a 96-byte request and a 139-byte response; the returned body and the file had identical SHA-256 hashes. A second demonstration sent two requests using one connection. A third sent an unknown frame, a malformed request, and a valid request without opening a new connection. These three demonstrations produced exactly three accepted connections in the [server log](evidence/server-log.txt).

## Protocol choices

The header is eight bytes: 32-bit payload length, 8-bit type, 8-bit flags, and 16-bit request ID. A one-MiB payload cap bounds memory use. IDs 1 to 10 name the header fields actually sent; ID 0 carries a length-prefixed literal name. Values are length-prefixed UTF-8, and bodies remain arbitrary bytes. A complete file is returned in one response frame, so this version supports sequential GET exchanges and bounded files. It does not implement HTTP/2 multiplexing or full HPACK.

The fixed registry contains host, user-agent, accept, content-type, content-length, server, connection, cache-control, x-request-id, and x-course. The response also demonstrates the unregistered literal name x-file-name. [The specification](docs/protocol-spec.md) contains every width, limit, error, and extension rule needed for another implementation.

## Submission checklist

- Two-page spec, executable source, and annotated exchange are included.
- All required artifacts can be opened from this repository or the ZIP.
- Recorded tests and bytes come from actual local runs.
- Partner identity and the course Google Form URL are needed to finalize the paired submission.

## Reference material

- [Instructor's project brief](https://drive.google.com/file/d/1tvzl6m0zUp98KlBdvLV8I_N0ki7qvY2J/view).
- [RFC 9113 frame format](https://www.rfc-editor.org/rfc/rfc9113.html#section-4.1).
- [RFC 7541 header representations](https://www.rfc-editor.org/rfc/rfc7541.html#section-6.2).
