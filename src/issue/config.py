"""Issue-specific configuration management.

Configuration is stored in ~/.tkt/config.toml under the [issue] section.

Configuration structure:
    [issue]
    bot_usernames = ["some-automation"]

Any login ending in [bot] is a bot without being listed. A repo's
.agents/tickster.toml [actors] bots adds to this, and [actors] agent_logins
turns a login into an AI actor instead.
"""

from src.board.config import CONFIG_FILE
from src.norms.model import Norms

try:
    import tomllib
except ImportError:
    import tomli as tomllib  # type: ignore[import-not-found]


def _load_issue_section() -> dict:
    """Load the [issue] section from config file."""
    if not CONFIG_FILE.exists():
        return {}
    with open(CONFIG_FILE, "rb") as f:
        data = tomllib.load(f)
    return data.get("issue", {})


def get_bot_usernames() -> list[str]:
    """Get the bot usernames listed under [issue] bot_usernames (none by default)."""
    return _load_issue_section().get("bot_usernames", [])


_bot_usernames_lower: set[str] | None = None


def is_bot_user(username: str, norms: Norms | None = None) -> bool:
    """Check if a username belongs to a bot.

    A bot is the union of: a login ending in [bot], the [issue] bot_usernames list
    and the repo's [actors] bots. A login in the repo's [actors] agent_logins is an
    AI actor, not a bot, even when it ends in [bot].
    """
    if norms is not None and norms.is_agent(username):
        return False
    username_lower = username.lower()
    if username_lower.endswith("[bot]"):
        return True
    global _bot_usernames_lower
    if _bot_usernames_lower is None:
        _bot_usernames_lower = {b.lower() for b in get_bot_usernames()}
    if username_lower in _bot_usernames_lower:
        return True
    return norms is not None and norms.is_listed_bot(username)
