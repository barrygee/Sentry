"""Tests for the `nmcli connection modify` argv the hotspot adapter builds.

`_modify_argv` is split out of `apply_profile` specifically so this property
set is inspectable on its own, and then nothing inspected it. The gap cost a
working feature: Sentry models "let the driver choose" as channel `0`, the argv
passed that through as the literal string `"0"`, and nmcli refuses it —

    Error: failed to modify 802-11-wireless.channel: '0' is not a valid channel.

`connection modify` is all-or-nothing, so the whole save failed with a 500.
Automatic being the default, *no* hotspot could be saved on a fresh install.

These assert argv construction, which is where the bug was. They cannot prove
nmcli accepts what is emitted — that needs a real NetworkManager.

Run with:  uv run pytest tests/hotspot/test_nmcli_modify_argv.py
"""

from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest

from app.backend.adapters.nmcli_wifi_ap import NmcliWifiApController
from app.backend.interfaces.process import ProcessSpawner
from app.backend.interfaces.types import HotspotBand, HotspotProfile

CONNECTION_NAME = "sentry-hotspot"
PASSPHRASE = "field-kit-2026"
CHANNEL_PROPERTY = "802-11-wireless.channel"
PSK_PROPERTY = "802-11-wireless-security.psk"


def profile(*, channel: int = 0, band: HotspotBand = "bg") -> HotspotProfile:
    return HotspotProfile(
        ssid="Sentry",
        hidden=False,
        security="wpa2",
        band=band,
        channel=channel,
        gateway_cidr="10.42.0.1/24",
        interface="wlan0",
        autoconnect=False,
    )


def controller() -> NmcliWifiApController:
    """Nothing here spawns: `_modify_argv` is pure, so the spawner is never touched."""
    return NmcliWifiApController(
        process_spawner=cast(ProcessSpawner, None),
        nmcli_path="/usr/bin/nmcli",
        connection_name=CONNECTION_NAME,
        nm_state_root=Path("/var/lib/NetworkManager"),
        timeout_s=30.0,
    )


def value_after(argv: list[str], property_name: str) -> str:
    """Return the value nmcli would receive for `property_name`."""
    return argv[argv.index(property_name) + 1]


class TestChannel:
    def test_automatic_is_sent_as_an_empty_string_not_a_literal_zero(self) -> None:
        """The actual bug. `"0"` is rejected outright; `""` resets to the default, auto."""
        argv = controller()._modify_argv(profile(channel=0), None)  # noqa: SLF001

        assert value_after(argv, CHANNEL_PROPERTY) == ""

    def test_a_chosen_channel_is_sent_as_its_number(self) -> None:
        """The counterpart — clearing must not swallow a deliberate choice."""
        argv = controller()._modify_argv(profile(channel=6), None)  # noqa: SLF001

        assert value_after(argv, CHANNEL_PROPERTY) == "6"

    def test_the_channel_property_is_always_written_even_when_automatic(self) -> None:
        """Omitting it would leave a previously-pinned channel in place.

        Switching Channel 6 back to Automatic has to actually clear the stored
        value, so the property must be present in the argv with an empty value
        rather than dropped from it.
        """
        argv = controller()._modify_argv(profile(channel=0), None)  # noqa: SLF001

        assert CHANNEL_PROPERTY in argv

    @pytest.mark.parametrize("band", ["bg", "a"])
    def test_automatic_clears_the_channel_on_either_band(self, band: HotspotBand) -> None:
        """Band and channel are set together; neither band may reintroduce the `0`."""
        argv = controller()._modify_argv(profile(channel=0, band=band), None)  # noqa: SLF001

        assert value_after(argv, CHANNEL_PROPERTY) == ""
        assert value_after(argv, "802-11-wireless.band") == band


class TestPassphrase:
    def test_the_psk_pair_is_absent_when_the_passphrase_is_unchanged(self) -> None:
        """Its absence is the "keep the stored password" signal — a placeholder would set one."""
        argv = controller()._modify_argv(profile(), None)  # noqa: SLF001

        assert PSK_PROPERTY not in argv

    def test_the_psk_pair_is_appended_when_a_passphrase_is_supplied(self) -> None:
        argv = controller()._modify_argv(profile(), PASSPHRASE)  # noqa: SLF001

        assert value_after(argv, PSK_PROPERTY) == PASSPHRASE

    def test_the_secret_is_never_the_only_thing_distinguishing_two_calls(self) -> None:
        """Supplying a key must change *only* the key — not silently alter other properties.

        A save that carried a passphrase once reconfigured more than the
        operator asked for; pinning the rest of the argv keeps that honest.
        """
        without_key = controller()._modify_argv(profile(), None)  # noqa: SLF001
        with_key = controller()._modify_argv(profile(), PASSPHRASE)  # noqa: SLF001

        assert with_key[: len(without_key)] == without_key
        assert with_key[len(without_key) :] == [PSK_PROPERTY, PASSPHRASE]
