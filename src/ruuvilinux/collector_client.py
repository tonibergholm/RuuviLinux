"""Small local control protocol for the independent collector daemon."""
import hashlib
import json
import os
from pathlib import Path
import socket
import tempfile


def control_path(database):
    digest = hashlib.sha256(str(Path(database).expanduser().resolve()).encode()).hexdigest()[:20]
    runtime = Path(os.environ.get("XDG_RUNTIME_DIR", str(Path(tempfile.gettempdir()) / f"ruuvilinux-{os.getuid()}")))
    runtime.mkdir(mode=0o700, parents=True, exist_ok=True)
    return runtime / f"ruuvilinux-collector-{digest}.sock"


def request(database, command="status", timeout=.25, **arguments):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(timeout)
        client.connect(str(control_path(database)))
        client.sendall(json.dumps({"command": command, **arguments}).encode() + b"\n")
        data = bytearray()
        while b"\n" not in data:
            packet = client.recv(4096)
            if not packet: raise OSError("Collector did not respond")
            data.extend(packet)
            if len(data) > 16384: raise OSError("Collector response was too large")
        result = json.loads(bytes(data).split(b"\n", 1)[0])
        if result.get("error"): raise OSError(result["error"])
        return result
