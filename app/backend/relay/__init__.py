"""Vendored per-dongle relay worker.

``rtl_tcp_relay.py`` is reused unchanged (see architecture §2) except for the
single additive wedge-exit diff permitted by ADR-0002. Sentry's supervisor
configures and spawns it as a subprocess by environment variable — it is never
imported by application code.
"""
