"""Snapshots written by 1.x (old window flags) stay readable and comparable.

The scope literals below are the 1.x file content, written out by hand: they
prove the stored window format did not change when the old flags went away.
"""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from src.date_window import build_date_window, field_flag_names
from src.snapshot import store
from src.snapshot.models import SnapshotScope, WindowScope
from tests.snapshot.test_list_cmd_watch import COMMANDS, fake_client  # noqa: F401

OLD_RELATIVE = {"field": "created", "since_days": 14}
OLD_ABSOLUTE = {"field": "closed", "after": "2026-11-01", "before": "2026-11-07"}


def _window(field: str, **kwargs):
    window = build_date_window(
        ["closed"], date_field=field, flag_names=field_flag_names(field), **kwargs
    )
    return WindowScope.from_window(window)


def test_relative_old_window_equals_the_new_flag_window():
    assert WindowScope.from_dict(OLD_RELATIVE) == _window("created", since_days=14)


def test_absolute_old_window_equals_the_new_flag_window():
    new = _window("closed", after="2026-11-01", before="2026-11-07")
    assert WindowScope.from_dict(OLD_ABSOLUTE) == new


@pytest.mark.parametrize(
    ("old", "new"),
    [
        (OLD_RELATIVE, ("created", {"since_days": 14})),
        (OLD_ABSOLUTE, ("closed", {"after": "2026-11-01", "before": "2026-11-07"})),
    ],
)
def test_old_and_new_windows_share_a_fingerprint(old, new):
    base = SnapshotScope(board="oh", states=("open",))
    old_scope = replace(base, window=WindowScope.from_dict(old))
    new_scope = replace(base, window=_window(new[0], **new[1]))
    assert old_scope == new_scope
    assert old_scope.fingerprint() == new_scope.fingerprint()


def test_new_windows_serialise_to_the_old_literal():
    assert _window("created", since_days=14).to_dict() == OLD_RELATIVE
    absolute = _window("closed", after="2026-11-01", before="2026-11-07")
    assert absolute.to_dict() == OLD_ABSOLUTE


@pytest.mark.parametrize("command", list(COMMANDS))
def test_watch_against_a_baseline_in_the_old_shape(
    command,
    tkt_home,  # noqa: ARG001
    fake_client,  # noqa: F811
    capsys,
):
    kind, cmd_list = COMMANDS[command]
    fake_client.numbers = [1]
    assert cmd_list(snapshot_name="base", field_dates={"created_since": 14}) == 0
    path = store.path_for(kind, "base")
    data = json.loads(path.read_text())
    data["scope"]["window"] = dict(OLD_RELATIVE)
    path.write_text(json.dumps(data))
    capsys.readouterr()

    assert cmd_list(watch_name="base", field_dates={"created_since": 14}) == 0
    assert "scope mismatch" not in capsys.readouterr().out


@pytest.mark.parametrize("command", list(COMMANDS))
def test_diff_against_a_baseline_in_the_old_shape(
    command,
    tkt_home,  # noqa: ARG001
    fake_client,  # noqa: F811
    capsys,
):
    kind, cmd_list = COMMANDS[command]
    fake_client.numbers = [1]
    assert cmd_list(snapshot_name="base", field_dates={"created_since": 14}) == 0
    path = store.path_for(kind, "base")
    data = json.loads(path.read_text())
    data["scope"]["window"] = dict(OLD_RELATIVE)
    path.write_text(json.dumps(data))
    capsys.readouterr()

    assert cmd_list(diff_name="base", field_dates={"created_since": 14}) == 0
    assert "scope mismatch" not in capsys.readouterr().out


@pytest.mark.parametrize("command", list(COMMANDS))
def test_a_different_new_flag_is_still_a_scope_change(
    command,
    tkt_home,  # noqa: ARG001
    fake_client,  # noqa: F811
    capsys,
):
    kind, cmd_list = COMMANDS[command]
    fake_client.numbers = [1]
    assert cmd_list(snapshot_name="base", field_dates={"created_since": 14}) == 0
    path = store.path_for(kind, "base")
    data = json.loads(path.read_text())
    data["scope"]["window"] = dict(OLD_RELATIVE)
    path.write_text(json.dumps(data))
    capsys.readouterr()

    assert cmd_list(watch_name="base", field_dates={"updated_since": 14}) == 2
    assert "scope mismatch" in capsys.readouterr().out
