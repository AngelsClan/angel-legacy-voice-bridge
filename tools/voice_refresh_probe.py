"""Opt-in live catalog test. Operator adds/removes a disposable XP voice alias.

Does not modify the registry itself or require credentials. Never remove real
voice tokens. The temporary token suffix is ALVB-Disposable-Voice-Test.
"""
import argparse
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "addon/synthDrivers"))
from _alvb.client import BridgeClient, DEFAULT_PIPE
from _alvb.protocol import Speech
from integration import wait_until

parser = argparse.ArgumentParser()
parser.add_argument("--pipe", default=DEFAULT_PIPE)
args = parser.parse_args()
events = []
client = BridgeClient(args.pipe, lambda event, data: events.append((event, data)))
client.start()
try:
    wait_until(lambda: client.connected)
    original = client.voice_tokens
    assert not any(token.endswith("ALVB-Disposable-Voice-Test") for token in original.values())
    print("READY: add the disposable voice alias now.", flush=True)
    wait_until(lambda: any(token.endswith("ALVB-Disposable-Voice-Test") for token in client.voice_tokens.values()), 60)
    new_index = next(index for index, token in client.voice_tokens.items() if token.endswith("ALVB-Disposable-Voice-Test"))
    assert all(client.voice_tokens.get(index) == token for index, token in original.items())
    client.enqueue([Speech("Live voice refresh check.", voice=new_index, volume=0)])
    wait_until(lambda: any(event == "done" for event, data in events), 15)
    print("ADDED AND SPOKEN: remove only the disposable alias now.", flush=True)
    wait_until(lambda: new_index not in client.voice_tokens, 60)
    assert client.voice_tokens == original
    assert sum(event == "connected" for event, data in events) == 1
    assert not any(event == "disconnected" for event, data in events)
    print("PASS live addition, speech, removal, stable IDs; no helper restart or reconnect", flush=True)
finally:
    client.close()
