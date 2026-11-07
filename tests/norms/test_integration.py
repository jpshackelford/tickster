"""How norms change board rules, bot detection and the saved agent settings."""

import pytest

import src.board.macros as macros
from src.board.config import BoardConfig, BoardsConfig
from src.board.gist import boards_config_to_toml, toml_to_boards_config
from src.board.models import COLUMN_AGENT_CODING, Item, ItemType, get_default_board_definition
from src.board.rules import Rule, matches_rule
from src.board.state import determine_column, explain_column
from src.board.yaml_config import (
    DEFAULT_TEMPLATE,
    load_board_from_string,
    save_board_definition,
)
from src.issue.config import is_bot_user
from src.issue.history import _parse_timeline_item, process_issue_data
from src.issue.models import IssueActionType
from src.norms import store
from src.norms.schema import parse_norms


def item(**kwargs) -> Item:
    defaults = {
        "repo": "owner/repo",
        "number": 1,
        "type": ItemType.ISSUE,
        "node_id": "I_1",
        "title": "t",
        "state": "open",
        "author": "someone",
    }
    return Item(**{**defaults, **kwargs})


def install_norms(text_by_repo: dict[str, str]):
    def loader(repo):
        text = text_by_repo.get(repo)
        return parse_norms(text).norms if text else None

    store.set_loader(loader)


@pytest.fixture(autouse=True)
def fresh_warning(monkeypatch):
    monkeypatch.setattr(macros, "_agent_warning_shown", False)


AGENT_RULE = Rule(column="Agent Coding", when={"$has_agent_assigned": True})
NOT_AGENT_RULE = Rule(column="x", when={"$has_agent_assigned": False})


class TestHasAgentAssigned:
    def test_false_with_no_norms_and_no_board_setting(self):
        assert matches_rule(item(assignees=["openhands-agent"]), AGENT_RULE)[0] is False
        assert matches_rule(item(assignees=["openhands-agent"]), NOT_AGENT_RULE)[0] is True

    def test_never_defaults_to_openhands(self):
        assert (
            matches_rule(item(assignees=["openhands"]), AGENT_RULE, agent_pattern=None)[0] is False
        )

    def test_repo_agent_logins_make_it_true(self):
        install_norms({"owner/repo": 'schema = 1\n[actors]\nagent_logins = ["robo-*"]\n'})
        assert matches_rule(item(assignees=["Robo-One"]), AGENT_RULE)[0] is True
        assert matches_rule(item(assignees=["human"]), AGENT_RULE)[0] is False

    def test_repo_norms_win_over_the_board_setting(self):
        install_norms({"owner/repo": 'schema = 1\n[actors]\nagent_logins = ["robo-*"]\n'})
        board_match = item(assignees=["mybot"])
        assert matches_rule(board_match, AGENT_RULE, agent_pattern="mybot")[0] is False
        assert matches_rule(item(assignees=["robo-1"]), AGENT_RULE, agent_pattern="mybot")[0]

    def test_explicit_board_pattern_still_works(self):
        assert matches_rule(item(assignees=["MyBot-1"]), AGENT_RULE, agent_pattern="mybot")[0]

    def test_board_pattern_applies_when_norms_have_no_agent_logins(self):
        install_norms({"owner/repo": "schema = 1\n"})
        assert matches_rule(item(assignees=["mybot"]), AGENT_RULE, agent_pattern="mybot")[0]

    def test_norms_are_looked_up_per_item_repo(self):
        install_norms({"a/with": 'schema = 1\n[actors]\nagent_logins = ["robo"]\n'})
        assert matches_rule(item(repo="a/with", assignees=["robo"]), AGENT_RULE)[0] is True
        assert matches_rule(item(repo="a/without", assignees=["robo"]), AGENT_RULE)[0] is False

    def test_column_assignment_uses_norms(self):
        install_norms({"owner/repo": 'schema = 1\n[actors]\nagent_logins = ["robo"]\n'})
        assert determine_column(item(assignees=["robo"])) == COLUMN_AGENT_CODING

    def test_column_assignment_uses_board_pattern(self):
        config = BoardConfig(agent_username_pattern="OpenHands")
        issue = item(assignees=["openhands-bot"])
        assert determine_column(issue, config) == COLUMN_AGENT_CODING
        assert "openhands-bot" in explain_column(issue, config)


class TestNoAgentSettingWarning:
    def test_prints_once_naming_both_fixes(self, capsys):
        for repo in ("a/one", "a/two"):
            matches_rule(item(repo=repo, assignees=["x"]), AGENT_RULE)
        err = capsys.readouterr().err
        assert err.count("$has_agent_assigned") == 1
        assert "a/one" in err
        assert "tkt norms init --from github:jpshackelford/tickster" in err
        assert "tkt board config set agent-username-pattern" in err

    def test_not_printed_when_a_setting_applies(self, capsys):
        matches_rule(item(assignees=["x"]), AGENT_RULE, agent_pattern="x")
        install_norms({"owner/repo": 'schema = 1\n[actors]\nagent_logins = ["r"]\n'})
        matches_rule(item(assignees=["x"]), AGENT_RULE)
        assert capsys.readouterr().err == ""

    def test_not_printed_for_rules_without_the_macro(self, capsys):
        matches_rule(item(assignees=["x"]), Rule(column="c", when={"state": "open"}))
        assert capsys.readouterr().err == ""


class TestClosedByBot:
    RULE = Rule(column="Icebox", when={"$closed_by_bot": True})

    def closed(self, **kwargs):
        return item(state="closed", **kwargs)

    def test_stale_label_is_the_built_in_fallback(self):
        assert matches_rule(self.closed(labels=["Stale"]), self.RULE)[0] is True

    def test_other_labels_do_not_match(self):
        assert matches_rule(self.closed(labels=["bug"]), self.RULE)[0] is False

    def test_item_flag_still_counts(self):
        assert matches_rule(self.closed(closed_by_bot=True), self.RULE)[0] is True

    def test_norms_without_labels_section_keep_the_fallback(self):
        install_norms({"owner/repo": "schema = 1\n"})
        assert matches_rule(self.closed(labels=["stale"]), self.RULE)[0] is True

    def test_empty_list_disables_the_label_check(self):
        install_norms({"owner/repo": "schema = 1\n[labels]\nstale = []\n"})
        assert matches_rule(self.closed(labels=["stale"]), self.RULE)[0] is False
        assert matches_rule(self.closed(closed_by_bot=True), self.RULE)[0] is True

    def test_custom_list_replaces_the_default(self):
        install_norms({"owner/repo": 'schema = 1\n[labels]\nstale = ["wontfix"]\n'})
        assert matches_rule(self.closed(labels=["WontFix"]), self.RULE)[0] is True
        assert matches_rule(self.closed(labels=["stale"]), self.RULE)[0] is False


class TestBotDetection:
    def test_bot_suffix(self):
        assert is_bot_user("anything[bot]") is True

    def test_no_built_in_name_list(self):
        assert is_bot_user("github-actions") is False
        assert is_bot_user("dependabot") is False

    def test_issue_bot_usernames_from_config(self, tmp_path, monkeypatch):
        from src.issue import config as issue_config

        cfg = tmp_path / "config.toml"
        cfg.write_text('[issue]\nbot_usernames = ["Automaton"]\n')
        monkeypatch.setattr(issue_config, "CONFIG_FILE", cfg)
        monkeypatch.setattr(issue_config, "_bot_usernames_lower", None)
        assert is_bot_user("automaton") is True
        monkeypatch.setattr(issue_config, "_bot_usernames_lower", None)

    def test_repo_bots_are_added(self):
        norms = parse_norms('schema = 1\n[actors]\nbots = ["ci-*"]\n').norms
        assert is_bot_user("CI-runner", norms) is True
        assert is_bot_user("CI-runner") is False

    def test_union_of_all_sources(self, tmp_path, monkeypatch):
        from src.issue import config as issue_config

        cfg = tmp_path / "config.toml"
        cfg.write_text('[issue]\nbot_usernames = ["listed"]\n')
        monkeypatch.setattr(issue_config, "CONFIG_FILE", cfg)
        monkeypatch.setattr(issue_config, "_bot_usernames_lower", None)
        norms = parse_norms('schema = 1\n[actors]\nbots = ["from-repo"]\n').norms
        assert all(is_bot_user(u, norms) for u in ("x[bot]", "listed", "from-repo"))
        assert not is_bot_user("human", norms)
        monkeypatch.setattr(issue_config, "_bot_usernames_lower", None)

    def test_agent_login_beats_the_bot_suffix(self):
        norms = parse_norms(
            'schema = 1\n[actors]\nagent_logins = ["all-hands-bot[bot]", "robo-*"]\n'
        ).norms
        assert is_bot_user("all-hands-bot[bot]") is True
        assert is_bot_user("all-hands-bot[bot]", norms) is False
        assert is_bot_user("other[bot]", norms) is True

    def test_agent_login_wins_even_if_also_listed_as_a_bot(self):
        norms = parse_norms(
            'schema = 1\n[actors]\nagent_logins = ["robo"]\nbots = ["robo"]\n'
        ).norms
        assert is_bot_user("robo", norms) is False

    def test_history_uses_repo_norms(self):
        norms = parse_norms(
            'schema = 1\n[actors]\nbots = ["ci-runner"]\nagent_logins = ["ai[bot]"]\n'
        ).norms
        comment = {"author": {"login": "ci-runner"}, "createdAt": "2024-01-15T11:00:00Z"}
        assert _parse_timeline_item("IssueComment", comment, "me", norms).action == (
            IssueActionType.BOT_COMMENT
        )
        assert (
            _parse_timeline_item("IssueComment", comment, "me", None).action
            == IssueActionType.COMMENT
        )
        agent = {"author": {"login": "ai[bot]"}, "createdAt": "2024-01-15T11:00:00Z"}
        assert (
            _parse_timeline_item("IssueComment", agent, "me", norms).action
            == IssueActionType.COMMENT
        )
        assert (
            _parse_timeline_item("IssueComment", agent, "me", None).action
            == IssueActionType.BOT_COMMENT
        )


def issue_data(commenter: str) -> dict:
    return {
        "number": 1,
        "title": "t",
        "state": "OPEN",
        "createdAt": "2024-01-15T10:00:00Z",
        "closedAt": None,
        "author": {"login": "author"},
        "repository": {"nameWithOwner": "owner/repo"},
        "labels": {"nodes": []},
        "timelineItems": {
            "nodes": [
                {
                    "__typename": "IssueComment",
                    "author": {"login": commenter},
                    "createdAt": "2024-01-15T11:00:00Z",
                }
            ]
        },
    }


class TestHistoryStringsUnchanged:
    @pytest.mark.parametrize("commenter", ["github-actions[bot]", "stale[bot]", "dependabot[bot]"])
    def test_former_default_bots_still_render_as_bots(self, commenter):
        with_bot = process_issue_data(issue_data(commenter), "author").history
        as_human = process_issue_data(issue_data("a-human"), "author").history
        assert with_bot != as_human
        assert "B" in with_bot or "b" in with_bot

    def test_newer_schema_file_does_not_break_issue_history(self):
        install_norms({"owner/repo": "schema = 99\n"})
        before = process_issue_data(issue_data("dependabot[bot]"), "author").history
        store.set_loader(lambda _r: None)
        assert before == process_issue_data(issue_data("dependabot[bot]"), "author").history

    def test_norms_for_the_issue_repo_are_used(self):
        install_norms({"owner/repo": 'schema = 1\n[actors]\nbots = ["ci-runner"]\n'})
        listed = process_issue_data(issue_data("ci-runner"), "author").history
        store.set_loader(lambda _r: None)
        unlisted = process_issue_data(issue_data("ci-runner"), "author").history
        assert listed != unlisted


class TestStoreMemoisation:
    def test_loader_runs_once_per_repo_case_insensitively(self):
        calls = []

        def loader(repo):
            calls.append(repo)
            return None

        store.set_loader(loader)
        store.get_repo_norms("A/b")
        store.get_repo_norms("a/B")
        store.get_repo_norms("a/c")
        assert calls == ["A/b", "a/c"]

    def test_set_loader_none_restores_github_and_clears_memo(self):
        store.set_loader(lambda _r: None)
        store.get_repo_norms("a/b")
        store.set_loader(None)
        assert store._loader is store.github_loader
        assert store._memo == {}


class TestAgentSettingIsSavedWhenSet:
    def test_yaml_roundtrip_keeps_openhands(self, tmp_path):
        board = load_board_from_string(DEFAULT_TEMPLATE)
        assert board.agent_pattern is None
        board.agent_pattern = "openhands"
        path = tmp_path / "b.yaml"
        save_board_definition(board, path)
        assert "agent_pattern: openhands" in path.read_text()
        assert load_board_from_string(path.read_text()).agent_pattern == "openhands"

    def test_yaml_without_setting_writes_none(self, tmp_path):
        board = load_board_from_string(DEFAULT_TEMPLATE)
        path = tmp_path / "b.yaml"
        save_board_definition(board, path)
        assert "agent_pattern" not in path.read_text()

    def test_built_in_template_only_has_it_as_a_commented_example(self):
        lines = [ln for ln in DEFAULT_TEMPLATE.splitlines() if "agent_pattern" in ln]
        assert lines
        assert all(ln.lstrip().startswith("#") for ln in lines)
        assert get_default_board_definition().agent_pattern is None

    def test_gist_toml_roundtrip_keeps_openhands(self):
        config = BoardsConfig(
            default="b", boards={"b": BoardConfig(name="b", agent_username_pattern="openhands")}
        )
        toml = boards_config_to_toml(config)
        assert 'agent_username_pattern = "openhands"' in toml
        assert toml_to_boards_config(toml).boards["b"].agent_username_pattern == "openhands"

    def test_gist_toml_without_setting(self):
        config = BoardsConfig(default="b", boards={"b": BoardConfig(name="b")})
        toml = boards_config_to_toml(config)
        assert "agent_username_pattern" not in toml
        assert toml_to_boards_config(toml).boards["b"].agent_username_pattern is None
