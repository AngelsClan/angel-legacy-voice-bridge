"""Manual fault test: close/restart ONLY the XP bridge helper when prompted.

Never run this while using the bridge as your screen reader. Does not kill
processes itself, change VM settings, or send real user speech.
"""
from pathlib import Path
import argparse
import sys
import threading

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "addon/synthDrivers"))
from _alvb.client import BridgeClient, DEFAULT_PIPE
from _alvb.protocol import Bookmark, Speech

disconnected = threading.Event()
reconnected = threading.Event()
done = threading.Event()
indices = []
connection_count = 0


def event(name, data):
    global connection_count
    if name == "connected":
        connection_count += 1
        if connection_count > 1:
            reconnected.set()
    elif name == "disconnected":
        disconnected.set()
    elif name == "index":
        indices.append(data[1])
    elif name == "done":
        done.set()


parser = argparse.ArgumentParser()
parser.add_argument("--pipe", default=DEFAULT_PIPE)
args = parser.parse_args()
client = BridgeClient(args.pipe, callback=event)
client.start()
try:
    assert client.wait_connected(12), client.status
    client.enqueue([Speech("This old test must not resume. " * 300, volume=0), Bookmark(99)])
    print("READY: close only the XP helper, wait for DISCONNECTED, then restart it.", flush=True)
    assert disconnected.wait(60), "No disconnect detected"
    print("DISCONNECTED: now restart the XP helper.", flush=True)
    assert reconnected.wait(60), "No reconnect detected"
    client.enqueue([Speech("Fresh session works.", volume=0), Bookmark(100)])
    assert done.wait(15), "New speech did not complete"
    assert indices == [100], indices
    print("PASS same client recovered after helper termination; old speech discarded", flush=True)
finally:
    client.close()
