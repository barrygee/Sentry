"""Injectable seams between Sentry's services and the outside world.

Every Protocol in this package is the entire testability strategy for the
project (architecture §4.1): services depend only on these narrow interfaces,
never on ctypes, sysfs paths, udev, or subprocess directly, so the whole
system can run — and be tested — on a developer laptop with no hardware.
"""
