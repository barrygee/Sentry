"""Tests for the import-only hotspot passphrase and the 422 redaction guarding it.

The feature is a deliberate asymmetry: a config file may carry a WiFi password
*inwards*, so a fresh Pi can be provisioned in one import, but no file Sentry
produces may ever contain one. Both halves are security properties rather than
conveniences, so both are pinned here — the export half especially, since it
holds by construction (`exclude=True`) and a future refactor could silently
remove that without any other test noticing.

Run with:  uv run pytest tests/config
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import pytest
from pydantic import ValidationError

from app.backend.routers.config import _import_hotspot
from app.backend.schemas.config import HotspotConfigEntry, SentryConfig

SECRET = "field-kit-2026"
"""A valid WPA passphrase, used verbatim so a leak assertion can search for it."""


# ── The export half: the secret must not survive serialisation ────────────────


def test_passphrase_is_parsed_from_an_inbound_file() -> None:
    """The whole point of the field: a hand-written file can set a password."""
    entry = HotspotConfigEntry.model_validate({"ssid": "Field", "passphrase": SECRET})

    assert entry.passphrase is not None
    assert entry.passphrase.get_secret_value() == SECRET


def test_passphrase_is_absent_from_model_dump() -> None:
    """`exclude=True` is the structural guarantee; this is what it buys."""
    entry = HotspotConfigEntry.model_validate({"ssid": "Field", "passphrase": SECRET})

    assert "passphrase" not in entry.model_dump()
    assert SECRET not in json.dumps(entry.model_dump())


def test_passphrase_is_absent_from_model_dump_json() -> None:
    """The JSON path is separate from `model_dump`, so it is asserted separately."""
    entry = HotspotConfigEntry.model_validate({"ssid": "Field", "passphrase": SECRET})

    assert SECRET not in entry.model_dump_json()
    assert "passphrase" not in json.loads(entry.model_dump_json())


def test_passphrase_does_not_survive_a_whole_config_round_trip() -> None:
    """Parse a provisioning file, re-serialise it: the *key* must be gone.

    This is the copy-and-share scenario the design is defending — an operator
    importing a file with a password and exporting from that instance later.

    Asserting the key rather than the value is deliberate, and the stronger
    check of the two. `SecretStr` alone would render the field as
    `"passphrase": "**********"`, which hides the secret but leaves a key that
    *passes validation* on the way back in — re-importing such a file would
    silently set the password to ten literal asterisks. Absence is the only
    safe state, so absence is what is asserted.
    """
    parsed = SentryConfig.model_validate(
        {"version": 1, "hotspot": {"ssid": "Field", "passphrase": SECRET}}
    )
    exported = json.loads(parsed.model_dump_json())

    assert "passphrase" not in exported["hotspot"]
    assert SECRET not in parsed.model_dump_json()


def test_masking_alone_would_not_be_enough() -> None:
    """Pins the reasoning above: a masked passphrase is a valid one.

    If `exclude=True` were ever swapped for "it's a SecretStr, it's masked",
    this is the failure that would follow — so the hazard is asserted directly
    rather than left in a comment.
    """
    masked = HotspotConfigEntry.model_validate({"ssid": "Field", "passphrase": "**********"})

    assert masked.passphrase is not None
    assert masked.passphrase.get_secret_value() == "**********"


def test_passphrase_does_not_appear_in_repr() -> None:
    """`SecretStr`'s own guarantee, relied on so a traceback cannot print it."""
    entry = HotspotConfigEntry.model_validate({"ssid": "Field", "passphrase": SECRET})

    assert SECRET not in repr(entry)
    assert SECRET not in str(entry)


def test_a_file_without_a_passphrase_parses_to_none() -> None:
    """An export-shaped file — the common case — leaves the stored password alone."""
    assert HotspotConfigEntry.model_validate({"ssid": "Field"}).passphrase is None


def test_the_shipped_example_file_still_imports() -> None:
    """`config.example.json` is documentation that must stay loadable.

    `extra="forbid"` means any illustrative key added to it becomes a parse
    error for anyone who imports the file as-is.
    """
    with open("config.example.json", encoding="utf-8") as handle:
        SentryConfig.model_validate(json.load(handle))


# ── Validation: the same rule PUT /api/hotspot applies ────────────────────────


@pytest.mark.parametrize(
    "passphrase",
    [
        pytest.param("short12", id="seven-characters"),
        pytest.param("", id="empty"),
        pytest.param("x" * 64, id="sixty-four-non-hex"),
        pytest.param("pässwörd123", id="non-ascii"),
    ],
)
def test_an_invalid_passphrase_is_rejected(passphrase: str) -> None:
    """Rejected at parse time, so a typo reads as a typo rather than an nmcli failure."""
    with pytest.raises(ValidationError):
        HotspotConfigEntry.model_validate({"ssid": "Field", "passphrase": passphrase})


@pytest.mark.parametrize(
    "passphrase",
    [
        pytest.param("eightchr", id="minimum-eight"),
        pytest.param("x" * 63, id="maximum-sixty-three"),
        pytest.param("a" * 64, id="raw-hex-psk"),
    ],
)
def test_a_valid_passphrase_is_accepted(passphrase: str) -> None:
    """The boundaries WPA-Personal actually defines, including a raw 64-hex PSK."""
    entry = HotspotConfigEntry.model_validate({"ssid": "Field", "passphrase": passphrase})

    assert entry.passphrase is not None


# ── The import half: which combinations apply, and which refuse ───────────────


@dataclass
class _StubHotspotState:
    passphrase_set: bool


@dataclass
class _StubSnapshot:
    state: _StubHotspotState


class _StubHotspotService:
    """Records what `_import_hotspot` passed through, without touching a radio."""

    def __init__(self, *, passphrase_set: bool) -> None:
        self._passphrase_set = passphrase_set
        self.applied_with: dict[str, Any] | None = None

    async def get_snapshot(self) -> _StubSnapshot:
        return _StubSnapshot(_StubHotspotState(self._passphrase_set))

    async def apply_configuration(self, **kwargs: Any) -> None:
        self.applied_with = kwargs


class _StubSettings:
    """Only the two settings `_import_hotspot` reads.

    Whether a console password exists is no longer a setting — it is a database
    fact (ADR-0010) — so it is passed to `_import_hotspot` directly rather than
    being stubbed here.
    """

    def __init__(
        self,
        *,
        control_enabled: bool = True,
        require_auth_token: bool = True,
    ) -> None:
        self.hotspot_control_enabled = control_enabled
        self.hotspot_require_auth_token = require_auth_token


def _entry(**overrides: Any) -> HotspotConfigEntry:
    return HotspotConfigEntry.model_validate({"ssid": "Field", **overrides})


@pytest.mark.asyncio
async def test_a_file_passphrase_provisions_an_instance_with_none_stored() -> None:
    """The feature's reason to exist: one import takes a bare Pi to a working hotspot."""
    service = _StubHotspotService(passphrase_set=False)

    applied, detail = await _import_hotspot(
        _entry(passphrase=SECRET), service, _StubSettings(), True
    )

    assert applied is True
    assert detail == ""
    assert service.applied_with is not None
    assert service.applied_with["passphrase"] == SECRET


@pytest.mark.asyncio
async def test_no_file_passphrase_keeps_the_stored_one() -> None:
    """`None` means "leave it alone" — an export-shaped file must not clear a password."""
    service = _StubHotspotService(passphrase_set=True)

    applied, _ = await _import_hotspot(_entry(), service, _StubSettings(), True)

    assert applied is True
    assert service.applied_with is not None
    assert service.applied_with["passphrase"] is None


@pytest.mark.asyncio
async def test_an_import_never_starts_the_hotspot() -> None:
    """Even when the file supplies everything needed to raise the network.

    A file import must not put a network on the air; an operator turns it on
    from a UI that shows them what they are about to broadcast.
    """
    service = _StubHotspotService(passphrase_set=False)

    await _import_hotspot(_entry(passphrase=SECRET), service, _StubSettings(), True)

    assert service.applied_with is not None
    assert service.applied_with["enabled"] is False


@pytest.mark.asyncio
async def test_no_passphrase_anywhere_refuses_rather_than_half_applying() -> None:
    """Writing an SSID the instance can never raise would be a silent half-success."""
    service = _StubHotspotService(passphrase_set=False)

    applied, detail = await _import_hotspot(_entry(), service, _StubSettings(), True)

    assert applied is False
    assert "does not carry one" in detail
    assert service.applied_with is None


@pytest.mark.asyncio
async def test_importing_a_passphrase_requires_a_console_password() -> None:
    """The same gate every other hotspot mutation passes (ADR-0010: a console password).

    Without it, config import would be a way around the rule that a hotspot
    cannot start while the API it exposes has no credentials.
    """
    service = _StubHotspotService(passphrase_set=False)

    applied, detail = await _import_hotspot(
        _entry(passphrase=SECRET), service, _StubSettings(), False
    )

    assert applied is False
    assert "console password" in detail
    assert service.applied_with is None


@pytest.mark.asyncio
async def test_the_password_gate_does_not_apply_when_the_deployment_waives_it() -> None:
    """`hotspot_require_auth_token=false` is an operator's explicit choice."""
    service = _StubHotspotService(passphrase_set=False)

    applied, _ = await _import_hotspot(
        _entry(passphrase=SECRET), service, _StubSettings(require_auth_token=False), False
    )

    assert applied is True


@pytest.mark.asyncio
async def test_the_password_gate_does_not_block_a_file_without_a_passphrase() -> None:
    """A settings-only import is not a credential change, so it is not gated as one."""
    service = _StubHotspotService(passphrase_set=True)

    applied, _ = await _import_hotspot(_entry(), service, _StubSettings(), False)

    assert applied is True


@pytest.mark.asyncio
async def test_hotspot_control_disabled_refuses_first() -> None:
    """The deploy-time gate outranks everything the file says."""
    service = _StubHotspotService(passphrase_set=True)

    applied, detail = await _import_hotspot(
        _entry(passphrase=SECRET), service, _StubSettings(control_enabled=False), True
    )

    assert applied is False
    assert "switched off" in detail
    assert service.applied_with is None


@pytest.mark.asyncio
async def test_a_file_with_no_ssid_is_refused() -> None:
    """There is nothing to name the network, so there is nothing to write."""
    service = _StubHotspotService(passphrase_set=True)
    entry = HotspotConfigEntry.model_validate({"passphrase": SECRET})

    applied, detail = await _import_hotspot(entry, service, _StubSettings(), True)

    assert applied is False
    assert "no hotspot network name" in detail
    assert service.applied_with is None
