#!/usr/bin/env python3
"""Quick test of the /v1/audio/stream WebSocket endpoint."""
import json
import os
import sys
import time

import websocket

# Generate a valid 64x64 red JPEG using Pillow (falls back to tiny hex if unavailable)
try:
    from PIL import Image
    import io as _io

    _img = Image.new("RGB", (64, 64), (255, 0, 0))
    _buf = _io.BytesIO()
    _img.save(_buf, format="JPEG", quality=50)
    JPEG_BYTES = _buf.getvalue()
    print(f"Generated test JPEG: {len(JPEG_BYTES)} bytes")
except ImportError:
    # Fallback: minimal 1x1 JPEG (may not work with all VLMs)
    JPEG_HEX = (
        "ffd8ffe000104a46494600010100000100010000"
        "ffdb004300080606070605080707070909080a0c"
        "140d0c0b0b0c1912130f141d1a1f1e1d1a1c1c"
        "20242e2720222c231c1c2837292c3031343434"
        "1f27393d38323c2e333432"
        "ffc0000b080001000101011100"
        "ffc4001f0000010501010101010100000000000000"
        "000102030405060708090a0b"
        "ffda00080101000003100001ffd9"
    )
    JPEG_BYTES = bytes.fromhex(JPEG_HEX)
    print(f"Using fallback hex JPEG: {len(JPEG_BYTES)} bytes")

ws_url = sys.argv[1] if len(sys.argv) > 1 else "ws://localhost:8100/v1/audio/stream"
api_key = os.environ.get("OPENAI_API_KEY", "")

print(f"Connecting to {ws_url} ...")
ws = websocket.WebSocket()
ws.settimeout(120)
headers = []
if api_key:
    headers.append(f"Authorization: Bearer {api_key}")
    print(f"Using auth token: {api_key[:8]}...")
ws.connect(ws_url, header=headers)
print("Connected!")

# Send config
cfg = {"model": "qwen3-vl-8b-instruct", "voice": "alloy", "max_tokens": 50}
ws.send(json.dumps(cfg))
ack = ws.recv()
print(f"Config ack: {ack}")

# Send test frame
print("Sending test JPEG frame ...")
ws.send(JPEG_BYTES, opcode=websocket.ABNF.OPCODE_BINARY)

# Receive chunks
t0 = time.time()
chunks = 0
texts = []

while True:
    opcode, data = ws.recv_data()
    if opcode == websocket.ABNF.OPCODE_TEXT:
        msg = json.loads(data)
        mtype = msg.get("type", "")
        if mtype == "error":
            print(f"  [error] {msg.get('detail', '(no detail)')}")
        else:
            print(f"  [{mtype}] {msg.get('content', '')[:120]}")
        if mtype == "text":
            texts.append(msg["content"])
        if mtype in ("done", "error"):
            break
    elif opcode == websocket.ABNF.OPCODE_BINARY:
        chunks += 1
        print(f"  [audio] chunk #{chunks}: {len(data)} bytes")

elapsed = time.time() - t0
print(f"\nResult: {chunks} audio chunks in {elapsed:.1f}s")
print(f"VLM text: {' '.join(texts)}")

ws.close()
print("Done!")
