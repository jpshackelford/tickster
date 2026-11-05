import pytest

from src.norms.model import CURRENT_SCHEMA, pattern_matches
from src.norms.schema import (
    dump_raw,
    migrate_raw,
    parse_norms,
    read_raw,
)
from tests.norms.conftest import ISSUE_EXAMPLE


def keys(result, level):
    return {i.key for i in result.issues if i.level == level}


def test_issue_example_parses_with_no_issues():
    result = parse_norms(ISSUE_EXAMPLE, strict=True)
    assert result.status == "ok"
    assert result.issues == []
    norms = result.norms
    assert norms is not None
    assert norms.actors.agent_logins == ("all-hands-bot", "openhands-agent")
    assert pattern_matches(norms.actors.agent_disclosure, "Created by an AI agent (OpenHands)")
    assert norms.review.rerequest_labels == ("review-this",)
    assert norms.ci.ignore_checks == ("codecov/*",)
    manual = norms.reports["manual_test"]
    assert manual.required is True
    assert pattern_matches(manual.marker, "## manual test results")
    assert pattern_matches(manual.fail, "| x | ❌ FAIL |")
    assert manual.impact_line is not None
    assert manual.impact_line.unassessed == "rerun"
    assert pattern_matches(manual.impact_line.pattern, "Manual test impact: re-run")
    assert norms.reports["docs_review"].required is False


def test_only_schema_is_enough_and_defaults_apply():
    norms = parse_norms("schema = 1\n").norms
    assert norms is not None
    assert norms.labels.stale == ("stale",)
    assert norms.review.count_reviews_from == ("humans", "agents")
    assert norms.reports == {}


def test_missing_schema_is_rejected():
    result = parse_norms("[labels]\nstale = []\n")
    assert result.norms is None
    assert result.status == "invalid"
    assert keys(result, "error") == {"schema"}


@pytest.mark.parametrize("value", ['"1"', "1.5", "true", "0", "-2"])
def test_non_integer_schema_is_rejected(value):
    result = parse_norms(f"schema = {value}\n")
    assert result.norms is None
    assert keys(result, "error") == {"schema"}


def test_unparseable_toml_is_rejected():
    result = parse_norms("schema = [\n")
    assert result.norms is None
    assert "not valid TOML" in result.errors[0].message


def test_newer_schema_is_unsupported_not_fatal():
    result = parse_norms(f"schema = {CURRENT_SCHEMA + 1}\nbrand_new = 1\n")
    assert result.norms is None
    assert result.status == "unsupported"
    assert result.file_schema == CURRENT_SCHEMA + 1
    assert result.errors[0].message == (
        f"unknown (config schema {CURRENT_SCHEMA + 1}; this tkt understands {CURRENT_SCHEMA})"
    )


def test_unknown_key_warns_and_names_the_key():
    result = parse_norms('schema = 1\nfuture = 1\n[actors]\nrobots = ["x"]\n')
    assert result.norms is not None
    assert keys(result, "warning") == {"future", "actors.robots"}
    assert "newer tickster" in result.warnings[0].message


def test_unknown_key_is_an_error_in_strict_mode():
    result = parse_norms('schema = 1\n[actors]\nrobots = ["x"]\n', strict=True)
    assert result.norms is None
    assert keys(result, "error") == {"actors.robots"}


def test_unknown_key_inside_named_report_is_flagged():
    text = "schema = 1\n[reports.x]\nmarker = 'a'\nextra = 1\n"
    assert keys(parse_norms(text), "warning") == {"reports.x.extra"}


@pytest.mark.parametrize(
    ("text", "key"),
    [
        ("schema = 1\n[actors]\nbots = 'x'\n", "actors.bots"),
        ("schema = 1\n[actors]\nbots = [1]\n", "actors.bots"),
        ("schema = 1\n[commits]\nmin_changed_lines = 'a'\n", "commits.min_changed_lines"),
        ("schema = 1\n[commits]\nmin_changed_lines = -1\n", "commits.min_changed_lines"),
        ("schema = 1\n[commits]\nmin_changed_lines = true\n", "commits.min_changed_lines"),
        ("schema = 1\nactors = 3\n", "actors"),
        ("schema = 1\nreports = 3\n", "reports"),
        ("schema = 1\n[reports]\nx = 3\n", "reports.x"),
        ("schema = 1\n[reports.x]\nmarker = 'a'\nrequired = 'yes'\n", "reports.x.required"),
        ("schema = 1\n[review]\ncount_reviews_from = ['robots']\n", "review.count_reviews_from"),
        (
            "schema = 1\n[reports.x]\nmarker = 'a'\n[reports.x.impact_line]\n"
            "pattern = 'b'\nunassessed = 'maybe'\n",
            "reports.x.impact_line.unassessed",
        ),
        ("schema = 1\n[actors]\nagent_disclosure = 5\n", "actors.agent_disclosure"),
    ],
)
def test_wrong_type_is_an_error_naming_the_key(text, key):
    result = parse_norms(text)
    assert result.norms is None
    assert key in keys(result, "error")


@pytest.mark.parametrize(
    ("text", "key"),
    [
        ("schema = 1\n[actors]\nagent_disclosure = '('\n", "actors.agent_disclosure"),
        ("schema = 1\n[reports.x]\nmarker = '[a'\n", "reports.x.marker"),
        (
            "schema = 1\n[reports.x]\nmarker = 'a'\nfail = '*'\n",
            "reports.x.fail",
        ),
    ],
)
def test_invalid_regex_is_an_error_naming_the_key(text, key):
    result = parse_norms(text)
    assert result.norms is None
    assert key in keys(result, "error")
    assert "invalid regex" in next(i for i in result.errors if i.key == key).message


def test_report_requires_marker_and_impact_pattern():
    result = parse_norms("schema = 1\n[reports.x]\nrequired = true\n")
    assert keys(result, "error") == {"reports.x.marker"}
    result = parse_norms(
        "schema = 1\n[reports.x]\nmarker = 'a'\n[reports.x.impact_line]\nfrom = ['agents']\n"
    )
    assert keys(result, "error") == {"reports.x.impact_line.pattern"}


def test_issue_format_includes_file_and_key():
    result = parse_norms("schema = 1\n[actors]\nbots = 3\n")
    assert result.errors[0].format("a/tickster.toml").startswith("a/tickster.toml: actors.bots: ")
    assert parse_norms("schema = [").errors[0].format("f.toml").startswith("f.toml: not valid")


def _rename_ignore_ci(d):
    d = dict(d)
    d["ci"] = {"ignore_checks": d.pop("ignore_ci", [])}
    return d


V2_RENAME = {1: _rename_ignore_ci}


def test_v1_file_loads_under_a_fake_schema_2_with_a_migration():
    v1 = 'schema = 1\nignore_ci = ["codecov/*"]\n'
    strict_v1_as_current = parse_norms(v1)
    assert keys(strict_v1_as_current, "warning") == {"ignore_ci"}

    result = parse_norms(v1, current_schema=2, migrations=V2_RENAME)
    assert result.status == "ok"
    assert result.migrated is True
    assert result.file_schema == 1
    assert result.norms is not None
    assert result.norms.schema == 2
    assert result.norms.ci.ignore_checks == ("codecov/*",)
    assert "migrated in memory from schema 1 to 2" in result.warnings[0].message


def test_current_schema_file_is_not_migrated():
    result = parse_norms("schema = 2\n", current_schema=2, migrations=V2_RENAME)
    assert result.migrated is False
    assert result.warnings == []


def test_missing_migration_step_is_an_error():
    result = parse_norms("schema = 1\n", current_schema=3, migrations={})
    assert result.norms is None
    assert "no migration from schema 1 to 2" in result.errors[0].message


def test_migrate_raw_chains_steps_and_stamps_schema():
    steps = {
        1: lambda d: {**d, "a": 1},
        2: lambda d: {**d, "b": 2},
    }
    out = migrate_raw({"schema": 1}, 1, 3, steps)
    assert out == {"schema": 3, "a": 1, "b": 2}


def test_read_raw_and_dump_round_trip():
    data, schema, errors = read_raw('schema = 1\n[labels]\nstale = ["x"]\n')
    assert (schema, errors) == (1, [])
    assert read_raw(dump_raw(data))[0] == data
