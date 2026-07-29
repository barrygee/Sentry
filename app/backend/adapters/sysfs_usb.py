"""Real `UsbDiscovery` walking a sysfs `bus/usb/devices` tree (architecture §4.2).

Root-parameterised so the exact same code path runs against `/sys` in
production and a fixture directory tree in tests
(`tests/fixtures/sysfs/<scenario>/`) — there is no separate "test mode".

Sysfs device node names encode USB topology directly: `busnum-port.port.port`
(e.g. `1-1.4.2` for a device on hub port 2, itself on hub port 4, on root
port 1 of bus 1). Roothub pseudo-devices (named e.g. `usb1`) and USB
*interface* nodes (named e.g. `1-1.4.2:1.0`, with a colon) are not
device-level nodes and are skipped.
"""

from __future__ import annotations

import logging
from pathlib import Path

from app.backend.interfaces.types import UsbDeviceSnapshot

_logger = logging.getLogger(__name__)


def parse_port_chain(topology_path: str) -> tuple[int, ...] | None:
    """Parse the port-path suffix of a sysfs device name into an integer tuple.

    `"1-1.4.2"` -> `(1, 4, 2)`. Returns `None` if `topology_path` is not of
    the `<bus>-<port>[.<port>...]` shape sysfs uses for real device nodes
    (e.g. a bare roothub name like `"usb1"`), so callers can skip it rather
    than crash.
    """
    if "-" not in topology_path:
        return None
    _bus, _, port_path = topology_path.partition("-")
    if not port_path:
        return None
    try:
        return tuple(int(segment) for segment in port_path.split("."))
    except ValueError:
        return None


def _is_interface_node(device_name: str) -> bool:
    """Return whether a sysfs device-directory name is a USB *interface* node.

    Interface nodes are named `<device>:<config>.<interface>`, e.g.
    `"1-1.4.2:1.0"` — the colon only ever appears in this position for USB
    device nodes, so its presence is sufficient to identify and skip them.
    """
    return ":" in device_name


def _is_roothub_node(device_name: str) -> bool:
    """Return whether a sysfs device-directory name is a roothub pseudo-device.

    Roothub nodes are named `usbN` (e.g. `"usb1"`) rather than
    `<bus>-<port...>`, and represent the host controller itself, not a
    physical downstream device.
    """
    return device_name.startswith("usb") and "-" not in device_name


def _read_attribute(device_dir: Path, filename: str) -> str | None:
    """Read and strip one sysfs attribute file, returning `None` if unavailable.

    Sysfs attribute files can be missing (an optional descriptor field, e.g.
    no `serial` string), or unreadable (a permission error, or a transient
    `OSError` if the device vanished between listing the directory and
    reading its attributes) — both are treated identically: the attribute is
    simply absent, and the device is not dropped just because one field
    could not be read.
    """
    path = device_dir / filename
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    # Sysfs values are newline-terminated; some also carry a leading BOM from
    # tests that authored fixtures with a text editor that added one.
    return content.strip().lstrip("﻿") or None


def _resolve_driver(device_dir: Path, device_name: str) -> str | None:
    """Resolve the kernel driver bound to a USB device's first interface, if any.

    The driver binds to the *interface* node, not the device node, so this
    looks for `<device_dir>/<device_name>:1.0/driver` — a symlink whose
    target's basename is the driver name — trying interface `1.0` first (the
    common single-interface RTL-SDR case) and falling back to scanning any
    `<device_name>:*` subdirectory for a bound driver.
    """
    candidates = [device_dir / f"{device_name}:1.0"] + sorted(
        candidate
        for candidate in device_dir.glob(f"{device_name}:*")
        if candidate.name != f"{device_name}:1.0"
    )
    for interface_dir in candidates:
        driver_link = interface_dir / "driver"
        try:
            if driver_link.is_symlink() or driver_link.exists():
                return driver_link.resolve().name
        except OSError:
            continue
    return None


def _parse_int_attribute(value: str | None) -> int | None:
    """Parse a sysfs integer attribute (decimal or `0x`-prefixed hex), or `None` if malformed."""
    if value is None:
        return None
    try:
        return int(value, 0) if value.lower().startswith("0x") else int(value)
    except ValueError:
        return None


def _read_device_snapshot(device_dir: Path) -> UsbDeviceSnapshot | None:
    """Build one `UsbDeviceSnapshot` from a sysfs device directory, or `None` if unusable.

    A device is skipped (not raised for — architecture §12.1) when its
    topology path cannot be parsed, or when the mandatory `busnum`/`devnum`/
    `idVendor`/`idProduct` attributes are missing or malformed. `serial`,
    `manufacturer`, `product` and `driver` are all individually optional.
    """
    device_name = device_dir.name
    port_chain = parse_port_chain(device_name)
    if port_chain is None:
        return None

    bus_number = _parse_int_attribute(_read_attribute(device_dir, "busnum"))
    device_address = _parse_int_attribute(_read_attribute(device_dir, "devnum"))
    vendor_id = _read_attribute(device_dir, "idVendor")
    product_id = _read_attribute(device_dir, "idProduct")
    if bus_number is None or device_address is None or vendor_id is None or product_id is None:
        _logger.debug("skipping sysfs device %s: missing mandatory attribute", device_dir)
        return None

    return UsbDeviceSnapshot(
        topology_path=device_name,
        bus_number=bus_number,
        port_chain=port_chain,
        device_address=device_address,
        vendor_id=vendor_id.lower(),
        product_id=product_id.lower(),
        serial=_read_attribute(device_dir, "serial"),
        manufacturer=_read_attribute(device_dir, "manufacturer"),
        product=_read_attribute(device_dir, "product"),
        driver=_resolve_driver(device_dir, device_name),
        sysfs_path=str(device_dir),
    )


class SysfsUsbDiscovery:
    """Real `UsbDiscovery` walking `<root>/bus/usb/devices/*`.

    `root` is injected (production passes `Path("/sys")`, tests pass a
    fixture directory) so the exact same traversal code is exercised in both
    contexts — parameterising the root is the entire testability strategy
    for this adapter.
    """

    def __init__(self, root: Path) -> None:
        self._devices_dir = root / "bus" / "usb" / "devices"

    def enumerate(self) -> list[UsbDeviceSnapshot]:
        """Return a snapshot of every present, decodable USB device under `root`.

        A nonexistent devices directory (no USB subsystem, or a fixture
        scenario for an empty bus) yields an empty list rather than raising.
        Any single device that vanishes mid-enumeration (its directory
        disappears between `iterdir()` and reading its attributes) is
        silently omitted rather than aborting the whole sweep.
        """
        try:
            device_dirs = sorted(self._devices_dir.iterdir())
        except OSError:
            return []

        snapshots: list[UsbDeviceSnapshot] = []
        for device_dir in device_dirs:
            device_name = device_dir.name
            if _is_roothub_node(device_name) or _is_interface_node(device_name):
                continue
            try:
                if not device_dir.is_dir():
                    continue
            except OSError:
                # The device vanished (or became unreadable) between listing
                # the directory and stat-ing this entry.
                continue
            snapshot = _read_device_snapshot(device_dir)
            if snapshot is not None:
                snapshots.append(snapshot)
        return snapshots
