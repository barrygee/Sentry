"""Tests for `NmcliWifiApController.deactivate()` tolerating an already-down profile.

`nmcli connection down` treats a profile that is not up as an error:

    Error: 'sentry-hotspot' is not an active connection.
    Error: no active connection provided.

But this method's postcondition — the profile is not active — is already met in
that case. Saving hotspot settings with "Run the hotspot" switched off calls it
unconditionally, so every such save failed with a 500 *after* the profile had
already been written: the change landed and the operator was told it had not.

The distinction that matters, and the reason this is not simply a swallowed
error: a teardown that genuinely fails while the hotspot is **active** leaves a
network on the air, and must still raise. So the already-down case is confirmed
by re-reading state, not by matching nmcli's wording — that text is not API and
is one translation away from changing.

Run with:  uv run pytest tests/hotspot/test_nmcli_deactivate.py
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import cast

import pytest

from app.backend.adapters.nmcli_wifi_ap import NmcliWifiApController
from app.backend.interfaces.process import ManagedProcess, ProcessSpawner
from app.backend.interfaces.wifi_ap import WifiApCommandError

CONNECTION_NAME = "sentry-hotspot"
NMCLI_PATH = "/usr/bin/nmcli"

# Verbatim from the Pi, via `last_error.stderr_tail`.
NOT_ACTIVE_STDERR = (
    b"Error: 'sentry-hotspot' is not an active connection.\nError: no active connection provided.\n"
)

FIXTURE_ROOT = Path("tests/fixtures/nmcli")


def connection_show_output(*, activation_state: str) -> bytes:
    """`nmcli connection show` output for the profile, with a chosen GENERAL.STATE."""
    rows = FIXTURE_ROOT.joinpath("connection_show_hotspot.txt").read_text(encoding="utf-8")
    return rows.replace("GENERAL.STATE:activated", f"GENERAL.STATE:{activation_state}").encode()


class FakeProcess:
    """A finished process with a scripted exit code and captured output."""

    def __init__(self, exit_code: int, stdout: bytes = b"", stderr: bytes = b"") -> None:
        self.pid = 4242
        self._exit_code = exit_code
        self._stdout = stdout
        self._stderr = stderr

    @property
    def returncode(self) -> int | None:
        return self._exit_code

    async def wait(self) -> int:
        return self._exit_code

    def terminate(self) -> None:
        pass

    def kill(self) -> None:
        pass

    def resume(self) -> None:
        pass

    async def communicate(self) -> tuple[bytes, bytes]:
        return (self._stdout, self._stderr)


class ScriptedNmcli:
    """Answers each `nmcli` invocation by which subcommand it carries.

    Keyed on the argv rather than call order, because `deactivate()`'s recovery
    path issues a *second*, different command and an order-keyed double would
    pass just as happily if the two were swapped.
    """

    def __init__(self, *, down_exit_code: int, activation_state: str) -> None:
        self._down_exit_code = down_exit_code
        self._activation_state = activation_state
        self.commands: list[list[str]] = []

    async def spawn(
        self,
        argv: Sequence[str],
        env: Mapping[str, str],
        name: str,
        capture_output: bool = False,
    ) -> ManagedProcess:
        arguments = list(argv)
        self.commands.append(arguments)

        if "down" in arguments:
            return cast(
                ManagedProcess,
                FakeProcess(
                    self._down_exit_code,
                    stderr=NOT_ACTIVE_STDERR if self._down_exit_code != 0 else b"",
                ),
            )
        if "show" in arguments:
            return cast(
                ManagedProcess,
                FakeProcess(
                    0, stdout=connection_show_output(activation_state=self._activation_state)
                ),
            )
        raise AssertionError(f"unexpected nmcli invocation: {arguments}")

    def ran_down(self) -> bool:
        return any("down" in command for command in self.commands)

    def re_read_state(self) -> bool:
        return any("show" in command for command in self.commands)


def controller(spawner: ScriptedNmcli) -> NmcliWifiApController:
    return NmcliWifiApController(
        process_spawner=cast(ProcessSpawner, spawner),
        nmcli_path=NMCLI_PATH,
        connection_name=CONNECTION_NAME,
        nm_state_root=FIXTURE_ROOT,
        timeout_s=30.0,
    )


@pytest.mark.asyncio
async def test_bringing_down_an_already_down_profile_succeeds() -> None:
    """The bug: saving with the hotspot switched off must not report failure."""
    spawner = ScriptedNmcli(down_exit_code=4, activation_state="")

    await controller(spawner).deactivate()

    assert spawner.ran_down(), "it must still attempt the teardown"


@pytest.mark.asyncio
async def test_the_already_down_case_is_confirmed_by_re_reading_state() -> None:
    """Not by matching nmcli's wording, which is localised and not API."""
    spawner = ScriptedNmcli(down_exit_code=4, activation_state="")

    await controller(spawner).deactivate()

    assert spawner.re_read_state()


@pytest.mark.asyncio
async def test_a_failed_teardown_of_an_active_hotspot_still_raises() -> None:
    """The case that must not be swallowed — it leaves a network on the air.

    Same non-zero exit as above; the only difference is that the profile is
    still reporting `activated` afterwards. If this ever stops raising, a
    hotspot an operator asked to stop keeps broadcasting while the UI says it
    stopped.
    """
    spawner = ScriptedNmcli(down_exit_code=4, activation_state="activated")

    with pytest.raises(WifiApCommandError):
        await controller(spawner).deactivate()


@pytest.mark.asyncio
async def test_a_clean_teardown_does_not_re_read_state() -> None:
    """The success path is unchanged: one command, no recovery probe."""
    spawner = ScriptedNmcli(down_exit_code=0, activation_state="")

    await controller(spawner).deactivate()

    assert spawner.ran_down()
    assert not spawner.re_read_state()
