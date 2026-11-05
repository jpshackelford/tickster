"""A closed stdout (``tkt ... | head``) ends quietly instead of printing a traceback."""

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent


def test_closed_stdout_exits_quietly():
    read_fd, write_fd = os.pipe()
    os.close(read_fd)
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "src", "--version"],
            stdout=write_fd,
            stderr=subprocess.PIPE,
            text=True,
            cwd=REPO_ROOT,
            timeout=60,
        )
    finally:
        os.close(write_fd)

    assert proc.stderr == ""
    assert proc.returncode == 141
