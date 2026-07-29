"""The three-tier device identity decision (architecture §5, ADR-0003).

Pure functions over a whole snapshot set — no I/O, no state, nothing
injected. Uniqueness of a serial is a set-wide property, so it cannot be
decided per-device; this is deliberately the single highest-value unit-test
target in the project (architecture §12.4).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from app.backend.interfaces.types import UsbDeviceSnapshot

IdentityTier = Literal["serial", "usb"]

KNOWN_DEFAULT_SERIALS: frozenset[str] = frozenset({"00000001", "00000000", "0000001"})
"""Factory-default serials that never count as a unique tier-1 identity."""


@dataclass(frozen=True, slots=True)
class DeviceIdentity:
    """The resolved persistence key for one device, or the absence of one (tier 3)."""

    kind: IdentityTier
    """Which tier this identity was resolved at."""

    key: str
    """The serial value (tier "serial") or topology path (tier "usb")."""

    @property
    def device_id(self) -> str:
        """The public `device_id` string: `"serial:<value>"` or `"usb:<path>"`.

        Built with a single `f"{kind}:{key}"` join rather than any escaping
        scheme: `key` may itself contain a colon or slash (a serial an
        operator flashed, or a topology path), but since every consumer that
        recovers `(kind, key)` from a `device_id` does so with
        `device_id.split(":", 1)` (split on the *first* colon only), an
        embedded colon in `key` lands entirely inside the recovered `key` and
        never corrupts the `kind` prefix (architecture §12.4).
        """
        return f"{self.kind}:{self.key}"


def is_tier1_eligible(serial: str | None) -> bool:
    """Return whether `serial` could be a tier-1 key in isolation (non-empty, non-default).

    Does not check set-wide uniqueness — that is `resolve`'s job, since
    uniqueness can only be decided across the whole snapshot set.
    """
    if serial is None:
        return False
    stripped = serial.strip()
    if not stripped:
        return False
    return stripped not in KNOWN_DEFAULT_SERIALS


def resolve(
    snapshots: Sequence[UsbDeviceSnapshot],
) -> dict[str, DeviceIdentity | None]:
    """Resolve a persistence identity for every device in one snapshot set.

    Returns a mapping keyed by each snapshot's `topology_path` (the only
    universally-present key at resolution time) to its resolved
    `DeviceIdentity`, or `None` when the device collapses to tier 3 ("needs
    identification" — architecture §5.1, never silently guessed).

    Tier 1 requires the serial to be non-empty, outside
    `KNOWN_DEFAULT_SERIALS`, and unique among every device in `snapshots`.
    Tier 2 requires the topology path itself to be unique in `snapshots`.
    Neither holding is tier 3.

    Duplicate serials are **not** treated uniformly, and this asymmetry is
    deliberate (architecture §12.4): a duplicated *known-default* serial
    (e.g. two never-configured dongles both reporting "00000001") is the
    ordinary, expected case and falls straight through to tier 2 — the
    topology path disambiguates it perfectly well. A duplicated serial that
    otherwise *looked* tier-1-eligible (two devices somehow reporting the
    identical non-default serial) is a genuine identity ambiguity and is
    forced to tier 3 outright, never silently demoted to tier 2, because
    guessing here risks a name/config silently migrating onto the wrong
    physical dongle after a future replug.
    """
    # Tier 1 candidacy is evaluated against the *stripped* serial (matching
    # `is_tier1_eligible`), but serials are compared for uniqueness
    # case-sensitively and without further normalisation — two visually
    # similar serials that differ only in case are treated as distinct
    # dongles, never silently merged.
    serial_occurrences: dict[str, int] = {}
    for snapshot in snapshots:
        if is_tier1_eligible(snapshot.serial):
            stripped_serial = (snapshot.serial or "").strip()
            serial_occurrences[stripped_serial] = serial_occurrences.get(stripped_serial, 0) + 1

    # Topology paths are, in principle, unique within one real snapshot set
    # (sysfs cannot enumerate two devices under the same bus-port path
    # simultaneously). A duplicate here would mean malformed input rather
    # than real hardware; it is still handled without crashing, by forcing
    # every snapshot sharing a duplicated path to tier 3 up front, below
    # (architecture §12.4 "should be impossible — assert it degrades to tier
    # 3, not a crash").
    topology_occurrences: dict[str, int] = {}
    for snapshot in snapshots:
        topology_occurrences[snapshot.topology_path] = (
            topology_occurrences.get(snapshot.topology_path, 0) + 1
        )

    resolved: dict[str, DeviceIdentity | None] = {}
    for snapshot in snapshots:
        if topology_occurrences[snapshot.topology_path] > 1:
            # A duplicated topology path can never be trusted as a tier-2
            # key, and a serial-based resolution alongside a malformed
            # topology reading is not trustworthy either — this input is
            # simply broken, so every affected snapshot degrades to tier 3.
            resolved[snapshot.topology_path] = None
            continue

        if is_tier1_eligible(snapshot.serial):
            stripped_serial = (snapshot.serial or "").strip()
            if serial_occurrences[stripped_serial] == 1:
                resolved[snapshot.topology_path] = DeviceIdentity(
                    kind="serial", key=stripped_serial
                )
            else:
                resolved[snapshot.topology_path] = None
        else:
            resolved[snapshot.topology_path] = DeviceIdentity(
                kind="usb", key=snapshot.topology_path
            )
    return resolved
