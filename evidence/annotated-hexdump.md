# Annotated Live BHTTP1 Exchange

Captured using the actual bserve and bcurl programs over local IPv4 TCP. Byte offsets below are hexadecimal and include the eight-byte frame header. The body is 20 bytes including the newline.

## Complete request

```text
0000  00 00 00 58 01 00 00 01 01 00 0a 2f 68 65 6c 6c  |...X......./hell|
0010  6f 2e 74 78 74 06 01 00 0f 31 32 37 2e 30 2e 30  |o.txt....127.0.0|
0020  2e 31 3a 35 30 37 39 30 02 00 07 62 63 75 72 6c  |.1:50790...bcurl|
0030  2f 31 03 00 03 2a 2f 2a 07 00 0a 6b 65 65 70 2d  |/1...*/*...keep-|
0040  61 6c 69 76 65 09 00 01 31 0a 00 14 6e 65 74 77  |alive...1...netw|
0050  6f 72 6b 2d 61 72 63 68 69 74 65 63 74 75 72 65  |ork-architecture|
```

| Hex offsets | Field | Decoded meaning |
|---|---|---|
| 0000-0003 | Payload length | 88 bytes; header excluded |
| 0004 | Type | 1 REQUEST |
| 0005 | Flags | 0; reserved bits clear |
| 0006-0007 | Request ID | 1 |
| 0008 | Method | 1 GET |
| 0009-000a | Path length | 10 |
| 000b-0014 | UTF-8 path | /hello.txt |
| 0015 | Header count | 6 |
| 0016-0027 | Header 1 | ID 1 = host; valueLen 15; value 127.0.0.1:50790 |
| 0028-0031 | Header 2 | ID 2 = user-agent; valueLen 7; value bcurl/1 |
| 0032-0037 | Header 3 | ID 3 = accept; valueLen 3; value */* |
| 0038-0044 | Header 4 | ID 7 = connection; valueLen 10; value keep-alive |
| 0045-0048 | Header 5 | ID 9 = x-request-id; valueLen 1; value 1 |
| 0049-005f | Header 6 | ID 10 = x-course; valueLen 20; value network-architecture |

## Complete response

```text
0000  00 00 00 83 02 00 00 01 00 c8 08 04 00 0a 74 65  |..............te|
0010  78 74 2f 70 6c 61 69 6e 05 00 02 32 30 06 00 08  |xt/plain...20...|
0020  62 73 65 72 76 65 2f 31 07 00 0a 6b 65 65 70 2d  |bserve/1...keep-|
0030  61 6c 69 76 65 08 00 08 6e 6f 2d 73 74 6f 72 65  |alive...no-store|
0040  09 00 01 31 0a 00 14 6e 65 74 77 6f 72 6b 2d 61  |...1...network-a|
0050  72 63 68 69 74 65 63 74 75 72 65 00 0b 78 2d 66  |rchitecture..x-f|
0060  69 6c 65 2d 6e 61 6d 65 00 09 68 65 6c 6c 6f 2e  |ile-name..hello.|
0070  74 78 74 00 00 00 14 48 65 6c 6c 6f 2c 20 62 69  |txt....Hello, bi|
0080  6e 61 72 79 20 48 54 54 50 21 0a                 |nary HTTP!.|
```

| Hex offsets | Field | Decoded meaning |
|---|---|---|
| 0000-0003 | Payload length | 131 bytes; header excluded |
| 0004 | Type | 2 RESPONSE |
| 0005 | Flags | 0; reserved bits clear |
| 0006-0007 | Request ID | 1 |
| 0008-0009 | Status | 200 |
| 000a | Header count | 8 |
| 000b-0017 | Header 1 | ID 4 = content-type; valueLen 10; value text/plain |
| 0018-001c | Header 2 | ID 5 = content-length; valueLen 2; value 20 |
| 001d-0027 | Header 3 | ID 6 = server; valueLen 8; value bserve/1 |
| 0028-0034 | Header 4 | ID 7 = connection; valueLen 10; value keep-alive |
| 0035-003f | Header 5 | ID 8 = cache-control; valueLen 8; value no-store |
| 0040-0043 | Header 6 | ID 9 = x-request-id; valueLen 1; value 1 |
| 0044-005a | Header 7 | ID 10 = x-course; valueLen 20; value network-architecture |
| 005b-0072 | Header 8 | ID 0; nameLen 11; name x-file-name; valueLen 9; value hello.txt |
| 0073-0076 | Body length | 20 |
| 0077-008a | Body bytes | Hello, binary HTTP!\n |

Byte verification: stdout SHA-256 equals the served file SHA-256.

`e39a22ac0e29905c83bc5e51f209b9249aa4db8db722e99c8605dd1624eda3f2`
