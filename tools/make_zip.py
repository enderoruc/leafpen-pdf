"""Zip dist\\LeafpenPDF into dist\\LeafpenPDF-v<version>-win64.zip and print its SHA-256.

Used by build.ps1 (PowerShell's Compress-Archive fails on files that are briefly locked
right after the build, e.g. by a virus scanner).
"""
import hashlib
import sys
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from leafpen import APP_VERSION  # noqa: E402


def main() -> int:
    dist = ROOT / "dist"
    folder = dist / "LeafpenPDF"
    if not (folder / "LeafpenPDF.exe").exists():
        print(f"{folder} has no LeafpenPDF.exe; build first", file=sys.stderr)
        return 1
    target = dist / f"LeafpenPDF-v{APP_VERSION}-win64.zip"
    tmp = target.with_suffix(".zip.tmp")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for path in sorted(folder.rglob("*")):
            if path.is_file():
                for attempt in range(20):  # a scanner may hold a fresh file for a moment
                    try:
                        z.write(path, path.relative_to(dist))
                        break
                    except PermissionError:
                        if attempt == 19:
                            raise
                        time.sleep(0.25)
    tmp.replace(target)
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    print(f"{target.name}  {target.stat().st_size / 1_048_576:.1f} MB")
    print(f"SHA-256: {digest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
