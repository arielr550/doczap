"""Refresh licenses/python from the python-build-standalone release the app is built with.

The packaged apps contain uv-managed Python, which comes from
python-build-standalone with OpenSSL, SQLite, Tcl and other libraries built in.
Its install-only archives leave out their license texts, so this script takes
them from the matching "full" archive, after checking the archive's SHA-256
against the digest GitHub publishes for it.

    uv run --python 3.14 python scripts/update_python_notices.py 3.14.10 20261110

Then set APP_PYTHON in .github/workflows/tests.yml to the same version.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
NOTICES = PROJECT_ROOT / "licenses" / "python"
REPOSITORY = "astral-sh/python-build-standalone"
TARGET = "aarch64-apple-darwin"
# Linux-only libraries (X11, Tix, Berkeley DB) are left out.
LINUX_ONLY = {"bdb", "libX11", "libXau", "libxcb", "tix"}


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    version, release = sys.argv[1:]
    name = f"cpython-{version}+{release}-{TARGET}-pgo+lto-full.tar.zst"
    with urllib.request.urlopen(
        f"https://api.github.com/repos/{REPOSITORY}/releases/tags/{release}"
    ) as response:
        assets = json.load(response)["assets"]
    asset = next((asset for asset in assets if asset["name"] == name), None)
    if asset is None:
        raise SystemExit(f"{name} is not in release {release}")

    with tempfile.TemporaryDirectory() as temporary:
        archive = Path(temporary) / name
        with urllib.request.urlopen(asset["browser_download_url"]) as response:
            with archive.open("wb") as file:
                shutil.copyfileobj(response, file)
        digest = "sha256:" + hashlib.sha256(archive.read_bytes()).hexdigest()
        if digest != asset["digest"]:
            raise SystemExit(f"{name} does not match its published digest")
        with tarfile.open(archive, "r:zst") as tar:
            licenses = [
                member for member in tar.getmembers()
                if member.isfile()
                and member.name.startswith("python/licenses/LICENSE.")
                and member.name.split(".")[-2] not in LINUX_ONLY
            ]
            shutil.rmtree(NOTICES, ignore_errors=True)
            NOTICES.mkdir(parents=True)
            for member in licenses:
                (NOTICES / Path(member.name).name).write_bytes(tar.extractfile(member).read())

    (NOTICES / "SOURCE.txt").write_text(
        f"CPython {version} from python-build-standalone {release}\n"
        f"{asset['browser_download_url']}\n"
        f"{asset['digest']}\n",
        encoding="utf-8",
    )
    print(f"Wrote {len(licenses)} notices to {NOTICES.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
