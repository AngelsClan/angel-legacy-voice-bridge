"""Disable a running, updated NVDA bridge without navigating its settings."""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "addon/synthDrivers"))
from _alvb.control import request_disable


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid", type=int, required=True, help="PID of the intended NVDA process")
    args = parser.parse_args()
    try:
        request_disable(args.pid)
    except (OSError, TimeoutError) as error:
        parser.exit(1, f"Bridge disable not confirmed: {error}\n")
    print("Bridge disabled; its worker has released the pipe. NVDA and XP are still running.")
