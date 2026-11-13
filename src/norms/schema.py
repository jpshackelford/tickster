"""Parse, validate and migrate ``.agents/tickster.toml``.

The file carries a required integer ``schema``. Older files are migrated in memory
through ``MIGRATIONS`` steps; a newer file than this tkt understands is not an error
for callers that only need GitHub data: they get ``status="unsupported"`` and no norms.
"""

from __future__ import annotations

import re
import tomllib
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

import tomli_w

from src.norms.model import (
    CI,
    CURRENT_SCHEMA,
    DEFAULT_STALE_LABELS,
    Actors,
    Commits,
    ImpactLine,
    Labels,
    Norms,
    Report,
    Review,
)

type Migration = Callable[[dict[str, Any]], dict[str, Any]]

# Maps schema N to the step that turns a schema N file into schema N+1.
MIGRATIONS: dict[int, Migration] = {}

ACTOR_CLASSES = ("humans", "agents", "bots")
IMPACT_SOURCES = ("agents", "author", "humans", "bots")


@dataclass(frozen=True)
class Key:
    kind: str  # strs | str | int | bool | regex | enum
    choices: tuple[str, ...] = ()
    required: bool = False
    unique: bool = False  # strs only: no repeats, ignoring case


@dataclass(frozen=True)
class Named:
    """A table whose sub-tables are user-named and share one spec."""

    spec: Mapping[str, Any]


type Spec = Mapping[str, Any]

REPORT_SPEC: Spec = {
    "marker": Key("regex", required=True),
    "required": Key("bool"),
    "only_paths": Key("strs"),
    "fail": Key("regex"),
    "impact_line": {
        "pattern": Key("regex", required=True),
        "from": Key("strs", choices=IMPACT_SOURCES),
        "unassessed": Key("enum", choices=("rerun", "ignore")),
    },
}

SPEC: Spec = {
    "actors": {
        "agent_logins": Key("strs"),
        "agent_disclosure": Key("regex"),
        "bots": Key("strs"),
    },
    "labels": {"stale": Key("strs"), "rank": Key("strs", unique=True)},
    "review": {
        "count_reviews_from": Key("strs", choices=ACTOR_CLASSES),
        "rerequest_labels": Key("strs"),
    },
    "ci": {"ignore_checks": Key("strs")},
    "commits": {"ignore_paths": Key("strs"), "min_changed_lines": Key("int")},
    "reports": Named(REPORT_SPEC),
}


@dataclass(frozen=True)
class Issue:
    level: str  # "error" | "warning"
    key: str
    message: str

    def format(self, filename: str) -> str:
        where = f"{filename}: {self.key}" if self.key else filename
        return f"{where}: {self.message}"


@dataclass
class LoadResult:
    norms: Norms | None
    issues: list[Issue] = field(default_factory=list)
    status: str = "ok"  # ok | invalid | unsupported
    file_schema: int | None = None
    migrated: bool = False
    data: dict[str, Any] | None = None  # raw data after migration

    @property
    def errors(self) -> list[Issue]:
        return [i for i in self.issues if i.level == "error"]

    @property
    def warnings(self) -> list[Issue]:
        return [i for i in self.issues if i.level == "warning"]


def _err(key: str, message: str) -> Issue:
    return Issue("error", key, message)


def _warn(key: str, message: str) -> Issue:
    return Issue("warning", key, message)


def _check_key(value: Any, spec: Key, path: str, issues: list[Issue]) -> tuple[bool, Any]:
    kind = spec.kind
    if kind == "bool":
        if isinstance(value, bool):
            return True, value
        issues.append(_err(path, "expected a boolean"))
    elif kind == "int":
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            return True, value
        issues.append(_err(path, "expected a non-negative integer"))
    elif kind == "str":
        if isinstance(value, str):
            return True, value
        issues.append(_err(path, "expected a string"))
    elif kind == "enum":
        if isinstance(value, str) and value in spec.choices:
            return True, value
        issues.append(_err(path, f"expected one of {', '.join(spec.choices)}"))
    elif kind == "regex":
        if not isinstance(value, str):
            issues.append(_err(path, "expected a string holding a regex"))
        else:
            try:
                return True, re.compile(value, re.IGNORECASE)
            except re.error as e:
                issues.append(_err(path, f"invalid regex {value!r}: {e}"))
    elif kind == "strs":
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            issues.append(_err(path, "expected a list of strings"))
        else:
            bad = [v for v in value if spec.choices and v not in spec.choices]
            if bad:
                issues.append(
                    _err(path, f"unknown value {bad[0]!r}; expected {', '.join(spec.choices)}")
                )
            else:
                folded = [v.lower() for v in value]
                dup = next((v for v in value if spec.unique and folded.count(v.lower()) > 1), None)
                if dup is not None:
                    issues.append(_err(path, f"duplicate value {dup!r} (case-insensitive)"))
                else:
                    return True, tuple(value)
    return False, None


def _validate(
    data: Mapping[str, Any], spec: Spec, path: str, issues: list[Issue], strict: bool
) -> dict[str, Any]:
    """Return the valid entries of ``data``, recording a problem for every other one."""
    out: dict[str, Any] = {}
    for name, value in data.items():
        key_path = f"{path}.{name}" if path else name
        sub = spec.get(name)
        if sub is None:
            level = _err if strict else _warn
            issues.append(level(key_path, "unknown key; a newer tickster may understand it"))
        elif isinstance(sub, Key):
            ok, checked = _check_key(value, sub, key_path, issues)
            if ok:
                out[name] = checked
        elif not isinstance(value, dict):
            issues.append(_err(key_path, "expected a table"))
        elif isinstance(sub, Named):
            out[name] = {}
            for rname, rvalue in value.items():
                rpath = f"{key_path}.{rname}"
                if isinstance(rvalue, dict):
                    out[name][rname] = _validate(rvalue, sub.spec, rpath, issues, strict)
                else:
                    issues.append(_err(rpath, "expected a table"))
        else:
            out[name] = _validate(value, sub, key_path, issues, strict)
    return out


def _require_keys(table: Mapping[str, Any], spec: Spec, path: str, issues: list[Issue]) -> None:
    """Flag required keys that are absent; a key that failed validation already has its own error."""
    failed = {i.key for i in issues}
    for name, sub in spec.items():
        key_path = f"{path}.{name}" if path else name
        if isinstance(sub, Key) and sub.required and name not in table and key_path not in failed:
            issues.append(_err(key_path, "missing required key"))


def _build_report(r: Mapping[str, Any]) -> Report | None:
    if "marker" not in r:
        return None
    impact = r.get("impact_line")
    impact_line = None
    if impact is not None and "pattern" in impact:
        impact_line = ImpactLine(
            pattern=impact["pattern"],
            from_=impact.get("from", ("agents", "author")),
            unassessed=impact.get("unassessed", "rerun"),
        )
    return Report(
        marker=r["marker"],
        required=r.get("required", False),
        only_paths=r.get("only_paths", ()),
        fail=r.get("fail"),
        impact_line=impact_line,
    )


def _build(schema: int, d: Mapping[str, Any], issues: list[Issue]) -> Norms:
    actors, labels, review = d.get("actors", {}), d.get("labels", {}), d.get("review", {})
    commits = d.get("commits", {})
    reports: dict[str, Report] = {}
    for name, raw in d.get("reports", {}).items():
        issues_before = len(issues)
        _require_keys(raw, REPORT_SPEC, f"reports.{name}", issues)
        impact = raw.get("impact_line")
        if impact is not None:
            _require_keys(impact, REPORT_SPEC["impact_line"], f"reports.{name}.impact_line", issues)
        report = _build_report(raw)
        if report is not None and len(issues) == issues_before:
            reports[name] = report
    return Norms(
        schema=schema,
        actors=Actors(
            agent_logins=actors.get("agent_logins", ()),
            agent_disclosure=actors.get("agent_disclosure"),
            bots=actors.get("bots", ()),
        ),
        labels=Labels(stale=labels.get("stale", DEFAULT_STALE_LABELS), rank=labels.get("rank", ())),
        review=Review(
            count_reviews_from=review.get("count_reviews_from", Review().count_reviews_from),
            rerequest_labels=review.get("rerequest_labels", ()),
        ),
        ci=CI(ignore_checks=d.get("ci", {}).get("ignore_checks", ())),
        commits=Commits(
            ignore_paths=commits.get("ignore_paths", ()),
            min_changed_lines=commits.get("min_changed_lines", 0),
        ),
        reports=reports,
    )


def read_raw(text: str) -> tuple[dict[str, Any] | None, int | None, list[Issue]]:
    """Parse TOML and check ``schema``; returns (data, schema, errors)."""
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        return None, None, [_err("", f"not valid TOML: {e}")]
    schema = data.get("schema")
    if schema is None:
        return None, None, [_err("schema", "missing required key; add `schema = 1`")]
    if not isinstance(schema, int) or isinstance(schema, bool) or schema < 1:
        return None, None, [_err("schema", f"expected a positive integer, got {schema!r}")]
    return data, schema, []


def migrate_raw(
    data: dict[str, Any],
    schema: int,
    current_schema: int = CURRENT_SCHEMA,
    migrations: Mapping[int, Migration] | None = None,
) -> dict[str, Any]:
    """Apply ``schema → schema+1`` steps until ``current_schema`` is reached."""
    steps = MIGRATIONS if migrations is None else migrations
    while schema < current_schema:
        if schema not in steps:
            raise ValueError(f"no migration from schema {schema} to {schema + 1}")
        data = steps[schema](data)
        schema += 1
        data["schema"] = schema
    return data


def unsupported_message(file_schema: int, current_schema: int) -> str:
    return f"unknown (config schema {file_schema}; this tkt understands {current_schema})"


def parse_norms(
    text: str,
    *,
    strict: bool = False,
    current_schema: int = CURRENT_SCHEMA,
    migrations: Mapping[int, Migration] | None = None,
) -> LoadResult:
    data, schema, issues = read_raw(text)
    if data is None or schema is None:
        return LoadResult(norms=None, issues=issues, status="invalid")
    if schema > current_schema:
        return LoadResult(
            norms=None,
            issues=[_err("schema", unsupported_message(schema, current_schema))],
            status="unsupported",
            file_schema=schema,
        )
    migrated = schema < current_schema
    if migrated:
        try:
            data = migrate_raw(data, schema, current_schema, migrations)
        except ValueError as e:
            return LoadResult(
                norms=None, issues=[_err("schema", str(e))], status="invalid", file_schema=schema
            )
        issues.append(
            _warn("schema", f"migrated in memory from schema {schema} to {current_schema}")
        )
    body = {k: v for k, v in data.items() if k != "schema"}
    checked = _validate(body, SPEC, "", issues, strict)
    norms = _build(current_schema, checked, issues)
    has_errors = any(i.level == "error" for i in issues)
    return LoadResult(
        norms=None if has_errors else norms,
        issues=issues,
        status="invalid" if has_errors else "ok",
        file_schema=schema,
        migrated=migrated,
        data=data,
    )


def dump_raw(data: Mapping[str, Any]) -> str:
    return tomli_w.dumps(dict(data))
