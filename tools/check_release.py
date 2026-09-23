"""Validate release archive boundaries and hashes before uploading anything."""
import hashlib
from pathlib import Path
import re
import zipfile

ROOT = Path(__file__).resolve().parents[1]
VERSION = "0.1.2-dev3"


def check_archive(path):
    forbidden_parts = {".git", "__pycache__", "memory.md", ".env", "credentials.json"}
    forbidden_suffixes = {".vdi", ".vmdk", ".vhdx", ".log", ".ini.bak", ".pyc"}
    private_markers = (rb"-----BEGIN .*PRIVATE KEY-----", rb"gh[pousr]_[A-Za-z0-9]{20,}",
                       rb"C:\\Users\\", rb"(?i)(?:password|api_key)\s*=\s*['\"][^'\"]+['\"]")
    with zipfile.ZipFile(path) as archive:
        assert archive.testzip() is None, "Corrupt archive"
        for name in archive.namelist():
            entry = Path(name)
            assert not entry.is_absolute() and ".." not in entry.parts, name
            assert not forbidden_parts.intersection(entry.parts), name
            assert entry.suffix.lower() not in forbidden_suffixes, name
            data = archive.read(name)
            if name != "tools/check_release.py":
                for marker in private_markers:
                    assert not re.search(marker, data), f"Review private-content marker in {name}"
        print(f"PASS {path.name}: {len(archive.namelist())} checked entries")


def main():
    paths = [ROOT / f"dist/NVDA Add-on/AngelLegacyVoiceBridge-{VERSION}.nvda-addon",
             ROOT / f"dist/AngelLegacyVoiceBridge-{VERSION}-source.zip",
             ROOT / "dist/XP Bridge/AngelLegacyVoiceBridge.exe"]
    for path in paths:
        if path.suffix != ".exe":
            check_archive(path)
        else:
            assert b"FAULT-INJECTION TEST ONLY" not in path.read_bytes(), "Refusing test-only helper"
        expected = path.with_suffix(path.suffix + ".sha256").read_text(encoding="ascii").split()[0]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == expected, path.name
        print(f"PASS SHA-256: {path.name}")


if __name__ == "__main__":
    main()
