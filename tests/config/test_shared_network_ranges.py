"""Tests for the hotspot and wired-share address ranges not colliding.

Both features raise a NetworkManager `shared` connection with its own DHCP
server, and both can be up at once on the target Pi. Overlapping ranges give the
host the same address on two interfaces and route one into the other — a failure
that presents as "the hotspot randomly stopped working" long after the config
change that caused it, with nothing in the logs connecting the two.

So it is refused at startup, where the message can name both variables. These
pin that, and pin the per-range rules that keep either from stranding the very
clients it exists to serve.

Run with:  uv run pytest tests/config
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from app.backend.config import Settings


def _settings(**overrides: str) -> Settings:
    """Build `Settings` from explicit values, ignoring any ambient `.env`.

    The overrides are passed as strings throughout — including for the numeric
    fields — because that is how they arrive from the environment in
    production, so the coercion each field declares is exercised rather than
    bypassed. `Any` is needed to say that to mypy, which otherwise checks the
    kwargs against each field's post-coercion type.
    """
    settings_factory: Any = Settings
    built: Settings = settings_factory(_env_file=None, **overrides)
    return built


class TestTheDefaults:
    """The out-of-the-box pair, which has to be usable with no configuration."""

    def test_the_shipped_defaults_do_not_overlap(self) -> None:
        settings = _settings()

        assert settings.hotspot_gateway_cidr == "10.42.0.1/24"
        assert settings.wired_gateway_cidr == "10.10.10.1/24"

    def test_the_wired_gateway_address_drops_its_prefix_length(self) -> None:
        """This is the value a human types into Sentinel, so it is surfaced alone."""
        assert _settings().wired_gateway_address() == "10.10.10.1"

    def test_the_hotspot_gateway_address_still_drops_its_prefix_length(self) -> None:
        assert _settings().hotspot_gateway_address() == "10.42.0.1"


class TestOverlapIsRefused:
    """The cross-feature check, which only startup is in a position to make."""

    def test_identical_ranges_are_refused(self) -> None:
        with pytest.raises(ValidationError) as raised:
            _settings(wired_gateway_cidr="10.42.0.1/24")

        message = str(raised.value)
        # Both variables are named, because the fix could be to either one.
        assert "SENTRY_WIRED_GATEWAY_CIDR" in message
        assert "SENTRY_HOTSPOT_GATEWAY_CIDR" in message

    def test_a_different_address_in_the_same_subnet_is_still_an_overlap(self) -> None:
        """Distinct addresses are not enough — the *networks* must not intersect."""
        with pytest.raises(ValidationError):
            _settings(wired_gateway_cidr="10.42.0.9/24")

    def test_a_wired_range_containing_the_hotspots_is_refused(self) -> None:
        """A wider prefix that swallows the other range is an overlap too."""
        with pytest.raises(ValidationError):
            _settings(wired_gateway_cidr="10.42.0.1/16")

    def test_a_hotspot_range_moved_onto_the_wired_one_is_refused(self) -> None:
        """The check is symmetric: either variable can be the one that moved."""
        with pytest.raises(ValidationError):
            _settings(hotspot_gateway_cidr="10.10.10.1/24")

    def test_adjacent_ranges_are_allowed(self) -> None:
        """Touching is not overlapping; refusing it would be needlessly strict."""
        settings = _settings(hotspot_gateway_cidr="10.42.0.1/24", wired_gateway_cidr="10.42.1.1/24")

        assert settings.wired_gateway_cidr == "10.42.1.1/24"


class TestEachRangeOnItsOwn:
    """Rules that keep a range from stranding the clients it is meant to serve."""

    @pytest.mark.parametrize(
        "gateway_cidr",
        [
            "not-an-address",
            "10.10.10.1",  # no prefix length at all
            "8.8.8.8/24",  # public: would blackhole real destinations for clients
            "10.10.10.0/24",  # the network address itself
            "10.10.10.255/24",  # the broadcast address
            "10.10.10.1/31",  # no usable host range
            "10.10.10.1/32",
            "10.10.10.1/8",  # wider than the /16 floor
        ],
    )
    def test_an_unusable_wired_range_is_refused_at_startup(self, gateway_cidr: str) -> None:
        """Refused here, not left to surface as leases nothing can use."""
        with pytest.raises(ValidationError):
            _settings(wired_gateway_cidr=gateway_cidr)

    @pytest.mark.parametrize(
        "gateway_cidr",
        ["172.16.5.1/24", "192.168.99.1/24", "10.10.10.1/30", "10.10.10.1/16"],
    )
    def test_a_usable_private_wired_range_is_accepted(self, gateway_cidr: str) -> None:
        assert _settings(wired_gateway_cidr=gateway_cidr).wired_gateway_cidr == gateway_cidr

    def test_an_unusable_hotspot_range_is_still_refused(self) -> None:
        """The pre-existing rule must survive the new cross-check being added."""
        with pytest.raises(ValidationError):
            _settings(hotspot_gateway_cidr="8.8.8.8/24")


class TestTheWiredSettingsThemselves:
    """The remaining wired knobs, and the bounds that keep them sane."""

    def test_the_connection_name_defaults_to_the_profile_sentry_owns(self) -> None:
        assert _settings().wired_connection_name == "sentry-wired"

    @pytest.mark.parametrize("connection_name", ["", "has spaces", "a" * 33, "semi;colon"])
    def test_a_connection_name_that_is_not_a_plain_token_is_refused(
        self, connection_name: str
    ) -> None:
        """This value becomes an nmcli argv element; the check is an allow-list."""
        with pytest.raises(ValidationError):
            _settings(wired_connection_name=connection_name)

    def test_no_interface_is_configured_by_default(self) -> None:
        """Unset means "choose automatically", which never takes a busy port."""
        assert _settings().wired_interface is None

    @pytest.mark.parametrize("interface", ["e" * 16, "eth 0", "eth;0"])
    def test_an_invalid_interface_name_is_refused(self, interface: str) -> None:
        with pytest.raises(ValidationError):
            _settings(wired_interface=interface)

    def test_a_valid_interface_name_is_accepted(self) -> None:
        assert _settings(wired_interface="enxb827eb").wired_interface == "enxb827eb"

    def test_the_confirm_timeout_defaults_to_two_minutes(self) -> None:
        assert _settings().wired_confirm_timeout_s == 120.0

    @pytest.mark.parametrize("timeout_s", ["1", "5000"])
    def test_a_confirm_timeout_outside_its_bounds_is_refused(self, timeout_s: str) -> None:
        """Too short to act on, or so long a lockout persists — both are refused."""
        with pytest.raises(ValidationError):
            _settings(wired_confirm_timeout_s=timeout_s)
