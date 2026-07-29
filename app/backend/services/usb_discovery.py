"""Turn raw USB snapshots into candidate SDRs (architecture §4.3).

Filters `UsbDiscovery.enumerate()` output to known RTL-SDR USB IDs, normalises
fields, and flags a bound DVB kernel driver as a conflict. Contains no
identity logic — that is `services.identity`'s job — and no hotplug/event
logic — that is `services.hotplug`'s job.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from app.backend.interfaces.types import UsbDeviceSnapshot
from app.backend.interfaces.usb import UsbDiscovery

# Known RTL-SDR-compatible USB vendor:product ID pairs, lowercase hex, no "0x".
KNOWN_RTL_SDR_USB_IDS: frozenset[tuple[str, str]] = frozenset(
    {
        ("0bda", "2832"),
        ("0bda", "2838"),
        ("0bda", "2834"),
        ("0bda", "2837"),
        ("1d19", "1101"),
        ("0ccd", "00a9"),
    }
)


# Kernel driver names bound by the in-tree DVB-T stack that claims RTL-SDR
# dongles before the blacklist documented in the README is applied. A device
# bound to one of these (rather than left driverless, or bound to a
# userspace-friendly driver) cannot be opened by librtlsdr.
DVB_KERNEL_DRIVER_NAMES: frozenset[str] = frozenset({"dvb_usb_rtl28xxu", "rtl2832u_sdr"})


def _has_driver_conflict(snapshot: UsbDeviceSnapshot) -> bool:
    """Return whether `snapshot`'s bound kernel driver blocks userspace access."""
    return snapshot.driver in DVB_KERNEL_DRIVER_NAMES


@dataclass(frozen=True, slots=True)
class CandidateSdr:
    """One USB device recognised as an RTL-SDR-compatible dongle."""

    snapshot: UsbDeviceSnapshot
    """The raw USB snapshot this candidate was derived from."""

    driver_conflict: bool
    """True when a DVB kernel driver is bound instead of the userspace driver."""


class UsbDiscoveryService:
    """Filters and annotates raw USB snapshots into RTL-SDR candidates.

    Takes the extra allow-listed IDs from configuration so an operator can
    add an uncommon but compatible dongle without a code change.
    """

    def __init__(
        self,
        usb_discovery: UsbDiscovery,
        extra_allowed_ids: frozenset[tuple[str, str]] = frozenset(),
    ) -> None:
        """`extra_allowed_ids` extends `KNOWN_RTL_SDR_USB_IDS` for this instance."""
        self._usb_discovery = usb_discovery
        self._extra_allowed_ids = extra_allowed_ids

    def discover_candidates(self) -> Sequence[CandidateSdr]:
        """Return every currently-present device recognised as an RTL-SDR-compatible dongle.

        Devices whose `(vendor_id, product_id)` is not in the allow-list are
        silently omitted (they are not SDR hardware Sentry manages). A device
        is flagged `driver_conflict` when its bound kernel driver is a DVB
        driver rather than the userspace `rtl2832u`/no-driver state RTL-SDR
        tooling expects — the common "forgot to blacklist dvb_usb_rtl28xxu"
        misconfiguration.
        """
        allowed_ids = KNOWN_RTL_SDR_USB_IDS | self._extra_allowed_ids
        candidates: list[CandidateSdr] = []
        for snapshot in self._usb_discovery.enumerate():
            if (snapshot.vendor_id, snapshot.product_id) not in allowed_ids:
                continue
            candidates.append(
                CandidateSdr(snapshot=snapshot, driver_conflict=_has_driver_conflict(snapshot))
            )
        return candidates
