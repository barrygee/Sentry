"""Tests for the operator-flippable hotspot switch and the gate it drives (ADR-0013).

Three properties matter here, and each would fail silently:

* **`.env` can only enable, never disable.** An operator who set
  `SENTRY_HOTSPOT_CONTROL_ENABLED=true` is depending on it; a UI toggle that
  could override a deploy-time decision would defeat the point of having one.
* **A switched-off Sentry reaches no nmcli and no D-Bus.** This is ADR-0007's
  central property, preserved through the move, and the reason the gate is a
  delegating controller rather than a boolean inside the real adapter. Nothing
  else enforces it.
* **The stored value is written even while `.env` forces control on**, so an
  operator who later tidies their `.env` gets what the console shows rather
  than a surprise.

Run with:  uv run pytest tests/services/test_host_control_settings.py
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.backend.adapters.gated_wifi_ap import GatedWifiApController
from app.backend.interfaces.types import HotspotClient, HotspotProfile, HotspotRuntimeState
from app.backend.interfaces.wifi_ap import WifiApController
from app.backend.models import Base, HostControlSettingsModel
from app.backend.services.host_control_settings import HostControlSettingsService

from ..fakes.clock import FakeClock


@pytest_asyncio.fixture
async def session_factory(tmp_path: Path) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """A throwaway SQLite file with the single settings row seeded, as migration 0005 does."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'settings.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        session.add(HostControlSettingsModel(id=1, hotspot_control_enabled=False, updated_at=0))
        await session.commit()
    yield factory
    await engine.dispose()


def build_service(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    forced: bool = False,
    clock: FakeClock | None = None,
) -> HostControlSettingsService:
    return HostControlSettingsService(
        session_factory, clock or FakeClock(), forced_hotspot_control_enabled=forced
    )


class TestStoredSwitch:
    @pytest.mark.asyncio
    async def test_a_fresh_install_has_hotspot_control_off(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        """The same default the environment variable always had."""
        assert await build_service(session_factory).hotspot_control_enabled() is False

    @pytest.mark.asyncio
    async def test_switching_it_on_takes_effect(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        service = build_service(session_factory)

        await service.set_hotspot_control_enabled(True)

        assert await service.hotspot_control_enabled() is True

    @pytest.mark.asyncio
    async def test_switching_it_off_again_takes_effect(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        service = build_service(session_factory)
        await service.set_hotspot_control_enabled(True)

        await service.set_hotspot_control_enabled(False)

        assert await service.hotspot_control_enabled() is False

    @pytest.mark.asyncio
    async def test_the_value_survives_a_new_service_instance(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        """It is a database fact, not process state — a restart must not reset it."""
        await build_service(session_factory).set_hotspot_control_enabled(True)

        assert await build_service(session_factory).hotspot_control_enabled() is True

    @pytest.mark.asyncio
    async def test_a_change_is_timestamped(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        """The only record that the switch moved, now that no `.env` edit is involved."""
        clock = FakeClock(start_ms=1_700_000_000_000)
        service = build_service(session_factory, clock=clock)

        await service.set_hotspot_control_enabled(True)

        async with session_factory() as session:
            row = await session.get(HostControlSettingsModel, 1)
        assert row is not None
        assert row.updated_at == 1_700_000_000_000


class TestEnvironmentOverride:
    @pytest.mark.asyncio
    async def test_the_environment_variable_forces_control_on(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        service = build_service(session_factory, forced=True)

        assert await service.hotspot_control_enabled() is True

    @pytest.mark.asyncio
    async def test_the_console_cannot_switch_off_what_the_environment_forces_on(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        """`.env` enables only. A toggle able to override it would defeat having one."""
        service = build_service(session_factory, forced=True)

        await service.set_hotspot_control_enabled(False)

        assert await service.hotspot_control_enabled() is True

    @pytest.mark.asyncio
    async def test_the_stored_value_is_still_written_while_forced(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        """So removing the variable later yields what the console showed, not a surprise."""
        await build_service(session_factory, forced=True).set_hotspot_control_enabled(False)

        assert await build_service(session_factory, forced=False).hotspot_control_enabled() is False

    @pytest.mark.asyncio
    async def test_forcing_is_reported_so_the_ui_can_explain_itself(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        """A switch that refuses to move and says nothing is worse than no switch."""
        assert build_service(session_factory, forced=True).hotspot_control_is_forced is True
        assert build_service(session_factory, forced=False).hotspot_control_is_forced is False


class RecordingWifiApController:
    """A `WifiApController` that records every call rather than making one."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.calls: list[str] = []

    async def is_available(self) -> bool:
        self.calls.append("is_available")
        return True

    async def list_wireless_interfaces(self) -> tuple[()]:
        self.calls.append("list_wireless_interfaces")
        return ()

    async def read_state(self) -> HotspotRuntimeState:
        self.calls.append("read_state")
        raise NotImplementedError

    async def apply_profile(self, profile: HotspotProfile, passphrase: str | None) -> None:
        self.calls.append("apply_profile")

    async def activate(self) -> None:
        self.calls.append("activate")

    async def deactivate(self) -> None:
        self.calls.append("deactivate")

    async def set_autoconnect(self, autoconnect: bool) -> None:
        self.calls.append("set_autoconnect")

    async def delete_profile(self) -> None:
        self.calls.append("delete_profile")

    async def release_lease(self, interface: str, ip_address: str, mac_address: str) -> None:
        self.calls.append("release_lease")

    async def active_connection_on(self, interface: str) -> str | None:
        self.calls.append("active_connection_on")
        return None

    async def activate_named(self, connection_name: str) -> None:
        self.calls.append("activate_named")

    def list_clients(self, interface: str | None = None) -> tuple[HotspotClient, ...] | None:
        self.calls.append("list_clients")
        return None


class TestGatedController:
    """ADR-0007's central property, preserved through the move to a runtime switch."""

    def build_gate(
        self, enabled: bool
    ) -> tuple[GatedWifiApController, RecordingWifiApController, RecordingWifiApController]:
        real = RecordingWifiApController("real")
        disabled = RecordingWifiApController("disabled")

        async def control_enabled() -> bool:
            return enabled

        gate = GatedWifiApController(
            enabled_controller=real,
            disabled_controller=disabled,
            control_enabled=control_enabled,
        )
        return gate, real, disabled

    def test_the_recording_double_satisfies_the_protocol(self) -> None:
        """Otherwise a drifted seam would make every assertion below vacuous."""
        assert isinstance(RecordingWifiApController("x"), WifiApController)

    @pytest.mark.asyncio
    async def test_a_switched_off_sentry_never_reaches_the_real_controller(self) -> None:
        """The whole point: no nmcli execution, no D-Bus call, exactly as ADR-0007 promised."""
        gate, real, disabled = self.build_gate(enabled=False)

        await gate.is_available()
        await gate.activate()
        await gate.deactivate()
        await gate.delete_profile()
        await gate.set_autoconnect(True)
        await gate.activate_named("something")
        await gate.list_wireless_interfaces()
        await gate.active_connection_on("wlan0")

        assert real.calls == []
        assert len(disabled.calls) == 8

    @pytest.mark.asyncio
    async def test_a_switched_on_sentry_reaches_the_real_controller(self) -> None:
        gate, real, disabled = self.build_gate(enabled=True)

        await gate.activate()

        assert real.calls == ["activate"]
        assert disabled.calls == []

    @pytest.mark.asyncio
    async def test_the_switch_is_consulted_per_call_not_cached(self) -> None:
        """A switch flipped in the UI must take effect without a restart."""
        real = RecordingWifiApController("real")
        disabled = RecordingWifiApController("disabled")
        enabled = False

        async def control_enabled() -> bool:
            return enabled

        gate = GatedWifiApController(
            enabled_controller=real,
            disabled_controller=disabled,
            control_enabled=control_enabled,
        )

        await gate.activate()
        enabled = True
        await gate.activate()

        assert real.calls == ["activate"]
        assert disabled.calls == ["activate"]

    def test_lease_reading_is_never_gated(self) -> None:
        """It touches no network stack — it reads dnsmasq's lease file — so it cannot await."""
        gate, real, _ = self.build_gate(enabled=False)

        gate.list_clients()

        assert real.calls == ["list_clients"]
