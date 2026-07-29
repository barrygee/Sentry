"""Business logic, one responsibility per module (architecture §4.3).

Services depend only on `interfaces/` Protocols and other services via
constructor injection — never on FastAPI, never on ctypes/sysfs/udev/
subprocess directly, and never on each other's private state.
"""
