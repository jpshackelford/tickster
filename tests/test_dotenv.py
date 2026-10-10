"""`.env` discovery when the CLI module is imported.

Runs a script file in a subprocess: python-dotenv treats `python -c` as
interactive and searches from cwd regardless, which would hide the bug.
"""

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PROBE = "TKT_DOTENV_PROBE"


def _probe(cwd: Path, tmp_path: Path, **extra_env: str) -> str:
    script = tmp_path / "probe.py"
    script.write_text(f"import os, src.__main__\nprint(os.environ.get({PROBE!r}, '<unset>'))\n")
    env = {k: v for k, v in os.environ.items() if k != PROBE}
    env["PYTHONPATH"] = str(REPO_ROOT)
    env.update(extra_env)
    return subprocess.run(
        [sys.executable, str(script)],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def test_loads_dotenv_from_working_directory(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    (work / ".env").write_text(f"{PROBE}=from-cwd\n")
    assert _probe(work, tmp_path) == "from-cwd"


def test_loads_dotenv_from_parent_of_working_directory(tmp_path):
    project = tmp_path / "project"
    sub = project / "sub"
    sub.mkdir(parents=True)
    (project / ".env").write_text(f"{PROBE}=from-parent\n")
    assert _probe(sub, tmp_path) == "from-parent"


def test_exported_variable_wins_over_dotenv(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    (work / ".env").write_text(f"{PROBE}=from-cwd\n")
    assert _probe(work, tmp_path, **{PROBE: "from-shell"}) == "from-shell"
