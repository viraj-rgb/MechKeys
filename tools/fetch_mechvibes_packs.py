"""Download recorded sound packs from the Mechvibes project (MIT licence) into sounds/.

Usage: python tools/fetch_mechvibes_packs.py
Requires the GitHub CLI (`gh`) for directory listings; files come from raw.githubusercontent.com.
"""

from __future__ import annotations

import json
import subprocess
import sys
import urllib.request
from pathlib import Path, PurePosixPath

REPO = "hainguyents13/mechvibes"
BRANCH = "main"
SOURCE_DIR = "src/audio"
PACKS = (
    "cherrymx-blue-pbt", "cherrymx-brown-pbt", "cherrymx-red-pbt", "cherrymx-black-pbt",
    "topre-purple-hybrid-pbt", "eg-crystal-purple", "eg-oreo", "holy-pandas",
    "turquoise", "cream-travel", "mxblue-travel",
)
ALLOWED_SUFFIXES = {".json", ".ogg", ".mp3", ".wav", ""}  # "" = LICENSE
DEST = Path(__file__).resolve().parent.parent / "sounds"


def list_dir(path: str) -> list[dict]:
    out = subprocess.run(["gh", "api", f"repos/{REPO}/contents/{path}?ref={BRANCH}"],
                         capture_output=True, text=True, check=True).stdout
    return json.loads(out)


def walk(path: str):
    for entry in list_dir(path):
        if entry["type"] == "dir":
            yield from walk(entry["path"])
        elif entry["type"] == "file":
            yield entry


def fetch_pack(pack: str) -> int:
    target = DEST / pack
    count = 0
    for entry in walk(f"{SOURCE_DIR}/{pack}"):
        relative = PurePosixPath(entry["path"]).relative_to(f"{SOURCE_DIR}/{pack}")
        if ".." in relative.parts or relative.suffix.lower() not in ALLOWED_SUFFIXES:
            continue
        out = target.joinpath(*relative.parts)
        out.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(entry["download_url"], timeout=60) as response:
            out.write_bytes(response.read())
        count += 1
    return count


def main() -> None:
    for pack in PACKS:
        try:
            print(f"{pack}: {fetch_pack(pack)} files")
        except (subprocess.CalledProcessError, OSError) as exc:
            print(f"{pack}: FAILED ({exc})", file=sys.stderr)


if __name__ == "__main__":
    main()
