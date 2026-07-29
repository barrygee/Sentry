"""Scriptable, in-process test doubles for Sentry's hardware-edge Protocols.

Distinct from `app/backend/adapters/` (which holds fakes that ship as part of
the application package, e.g. `FakeProcessSpawner` and `FakeRtlSdrLibrary`,
because `main.py`'s composition root may select them via configuration for a
demo/dev mode) — this package holds pure test infrastructure that only the
test suite imports: `FakeClock` and the fake `rtl_tcp` server.
"""
