"""Generate paths and run the PlaceRAN PuLP/CBC implementation."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


PLACE_RAN_DIR = Path(__file__).resolve().parent


def main() -> None:
    subprocess.run(
        [sys.executable, str(PLACE_RAN_DIR / "model_files" / "path_gen.py")],
        cwd=str(PLACE_RAN_DIR),
        check=True,
    )
    subprocess.run(
        [
            sys.executable,
            str(PLACE_RAN_DIR / "model_files" / "model_pulp.py"),
            *sys.argv[1:],
        ],
        cwd=str(PLACE_RAN_DIR),
        check=True,
    )


if __name__ == "__main__":
    main()
