"""Tests that `.env.example` cannot silently break a fresh install.

`.env.example` is not documentation that sits still: the README tells an
operator to copy it to `.env`, so every line in it is executed on a real Pi.
A wrong value there is a wrong value in production, on first boot, for everyone.

This suite exists because that happened. `.env.example` shipped

    SENTRY_RELAY_PATH=/app/relay/rtl_tcp_relay.py

while the relay is actually at `/app/app/backend/relay/rtl_tcp_relay.py` in the
image. Copying the file overrode a default that derives the path from the
package — and is therefore right in both Docker and a checkout — with an
absolute one that is right in neither. Every dongle then failed identically:
`rtl_tcp` started, the relay could not be found, the pair died, and the
supervisor reported a crash loop indistinguishable from a hardware fault.

Run with:  uv run pytest tests/config
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.backend.config import Settings

ENV_EXAMPLE = Path(".env.example")

SETTING_BY_ENV_NAME = {f"SENTRY_{name.upper()}": name for name in Settings.model_fields}


def _declared_values() -> dict[str, str]:
    """Every uncommented `SENTRY_*=value` line in `.env.example`."""
    return dict(re.findall(r"^(SENTRY_[A-Z0-9_]+)=(.*)$", ENV_EXAMPLE.read_text(), re.M))


def test_every_declared_key_is_a_real_setting() -> None:
    """A typo'd key is silently ignored by pydantic-settings, so nothing would report it."""
    unknown = sorted(set(_declared_values()) - set(SETTING_BY_ENV_NAME))

    assert unknown == [], f".env.example declares settings that do not exist: {unknown}"


@pytest.mark.parametrize(
    ("env_name", "value"),
    [(key, value) for key, value in _declared_values().items() if value.startswith("/")],
)
def test_absolute_paths_match_the_code_default(env_name: str, value: str) -> None:
    """An absolute path may only appear here if it is already the default.

    This is the exact rule the relay path broke. A default that differs from
    what this file sets means the file is overriding the code's own answer with
    a hard-coded guess about the filesystem — which cannot be right in both the
    container and a non-Docker checkout, because their layouts differ.

    Paths whose default genuinely is absolute and environment-independent
    (`/sys`, NetworkManager's state directory) are unaffected: they match.
    """
    default = Settings.model_fields[SETTING_BY_ENV_NAME[env_name]].default

    assert value == str(default), (
        f"{env_name} is set to {value!r} in .env.example but the code default is "
        f"{default!r}. Copying .env.example to .env would override a correct, "
        f"derived value with a hard-coded one. Remove the line instead."
    )


def test_relay_path_is_not_pinned_in_the_example() -> None:
    """The specific regression, asserted by name.

    The rule above already covers it, but only while the wrong value happens to
    be absolute. Naming the setting keeps the case pinned even if someone
    reintroduces it as a relative path.
    """
    assert "SENTRY_RELAY_PATH" not in _declared_values(), (
        "SENTRY_RELAY_PATH must not be set in .env.example. The relay ships inside "
        "the backend package and its location is derived from the package, so it is "
        "correct in both the container and a checkout. Pinning it broke every dongle."
    )


def test_the_derived_relay_default_points_at_a_real_file() -> None:
    """The other half of the failure: a correct-looking path that resolves nowhere.

    Guards the packaging as well as the config — if the relay is ever moved
    within the package, or dropped from what the image copies, this fails here
    rather than as a crash loop on a Pi.
    """
    relay_path = Path(str(Settings.model_fields["relay_path"].default))

    assert relay_path.is_file(), f"the relay default resolves to {relay_path}, which does not exist"
