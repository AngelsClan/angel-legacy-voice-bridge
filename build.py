"""Build the XP helper and a deterministic add-on; never install either one."""
from pathlib import Path
import argparse
import hashlib
import os
import py_compile
import shutil
import subprocess
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parent
VERSION = "0.1.2-dev3"


def find_tools():
    candidates = sorted(Path(r"C:\Program Files\Microsoft Visual Studio\2022").glob("*/VC/Tools/MSVC/*"))
    compiler_root = next((p for p in reversed(candidates) if (p / "bin/Hostx64/x86/cl.exe").is_file()), None)
    if compiler_root is None:
        raise RuntimeError("Install Visual Studio C++ x86 build tools first.")
    kits = Path(r"C:\Program Files (x86)\Windows Kits\10")
    sdk = next((p.name for p in sorted((kits / "Include").iterdir(), reverse=True)
                if (kits / "Lib" / p.name / "um/x86/kernel32.lib").is_file()), None)
    if sdk is None:
        raise RuntimeError("Install a Windows SDK with x86 libraries first.")
    return compiler_root, kits, sdk


def build_bridge(test_drop_end_events=False):
    compiler, kits, sdk = find_tools()
    environment = os.environ.copy()
    environment["INCLUDE"] = ";".join(map(str, [compiler / "include", kits / "Include" / sdk / "ucrt",
                                               kits / "Include" / sdk / "shared", kits / "Include" / sdk / "um"]))
    environment["LIB"] = str(kits / "Lib" / sdk / "um/x86")
    output = ROOT / "build" / ("completion-test" if test_drop_end_events else "release")
    output.mkdir(parents=True, exist_ok=True)
    cl = compiler / "bin/Hostx64/x86/cl.exe"
    link = compiler / "bin/Hostx64/x86/link.exe"
    # /GS- and /NODEFAULTLIB avoid newer CRT imports. Buffers have explicit bounds;
    # this is a compatibility compromise, not a claim of modern exploit mitigation.
    defines = ["/DALVB_TEST_DROP_END_EVENTS"] if test_drop_end_events else []
    for filename in ("main", "runtime"):
        subprocess.run([str(cl), "/nologo", "/c", "/W4", "/GS-", "/GR-", "/Zl", "/Od",
                        "/D_UNICODE", "/DUNICODE", "/Fo" + str(output / (filename + ".obj")),
                        str(ROOT / "bridge" / (filename + ".cpp")), *defines], env=environment, check=True)
    # Fault injection must never replace the distributable helper.
    destination = ROOT / ("build/completion-test" if test_drop_end_events else "dist/XP Bridge")
    destination.mkdir(parents=True, exist_ok=True)
    executable = destination / "AngelLegacyVoiceBridge.exe"
    subprocess.run([str(link), "/NOLOGO", "/NODEFAULTLIB", "/MACHINE:X86", "/SUBSYSTEM:CONSOLE,5.01",
                    "/ENTRY:bridgeEntry", "/DYNAMICBASE", "/NXCOMPAT", "/OUT:" + str(executable),
                    str(output / "main.obj"), str(output / "runtime.obj"),
                    "kernel32.lib", "ole32.lib", "user32.lib", "shell32.lib", "sapi.lib", "winmm.lib"], env=environment, check=True)
    return executable


def build_addon():
    if not (ROOT / "addon/doc/en/readme.html").is_file():
        raise RuntimeError("Embedded add-on help is required")
    destination = ROOT / "dist/NVDA Add-on"
    destination.mkdir(parents=True, exist_ok=True)
    addon = destination / f"AngelLegacyVoiceBridge-{VERSION}.nvda-addon"
    with tempfile.TemporaryDirectory() as temp:
        for index, source in enumerate((ROOT / "addon").rglob("*.py")):
            py_compile.compile(str(source), cfile=str(Path(temp) / f"{index}.pyc"), doraise=True)
    with zipfile.ZipFile(addon, "w", zipfile.ZIP_DEFLATED) as archive:
        for source in sorted((ROOT / "addon").rglob("*")):
            if source.is_file() and "__pycache__" not in source.parts and source.suffix != ".pyc":
                info = zipfile.ZipInfo(source.relative_to(ROOT / "addon").as_posix(), (2026, 9, 19, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(info, source.read_bytes())
        if (ROOT / "LICENSE").exists():
            info = zipfile.ZipInfo("LICENSE.txt", (2026, 9, 19, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, (ROOT / "LICENSE").read_bytes())
    return addon


def build_source():
    """Explicit source allowlist: never archive the workspace or local history."""
    destination = ROOT / "dist" / f"AngelLegacyVoiceBridge-{VERSION}-source.zip"
    sources = [ROOT / name for name in ("build.py", "LICENSE", "README.md", "PROTOCOL.md", "RATIONALE.md",
                                       "CHANGELOG.md", "PUBLICATION.md", "OPERATIONS.md", "TEST-REPORT.md", "RELEASE-NOTES.md", ".gitignore", ".gitattributes")]
    for folder in ("addon", "bridge", "tests", "tools"):
        sources.extend(path for path in (ROOT / folder).rglob("*")
                       if path.is_file() and "__pycache__" not in path.parts
                       and path.suffix in (".py", ".cpp", ".ini", ".html"))
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
        for source in sorted(sources):
            info = zipfile.ZipInfo(source.relative_to(ROOT).as_posix(), (2026, 9, 19, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, source.read_bytes())
    return destination


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package-only", action="store_true",
                        help="Keep the already-tested helper binary; refresh add-on, source and hashes")
    args = parser.parse_args()
    helper = ROOT / "dist/XP Bridge/AngelLegacyVoiceBridge.exe"
    if args.package_only and not helper.is_file():
        parser.error("Build and test the XP helper before packaging it")
    paths = [helper if args.package_only else build_bridge(), build_addon(), build_source()]
    for source in ("README.md", "PROTOCOL.md", "TEST-REPORT.md", "PUBLICATION.md", "OPERATIONS.md", "LICENSE"):
        if (ROOT / source).exists():
            shutil.copy2(ROOT / source, ROOT / "dist" / source)
    for artifact in paths:
        digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
        artifact.with_suffix(artifact.suffix + ".sha256").write_text(f"{digest}  {artifact.name}\n", encoding="ascii")
        print(f"Built {artifact}")
