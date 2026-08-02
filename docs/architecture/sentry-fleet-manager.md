# Sentry — Multi-Dongle SDR Fleet Manager

**Status:** Design — approved architecture, pending sign-off on the open questions in §13.
**Supersedes:** the earlier single-dongle stack (`rtl-tcp` + `rtl-relay` compose services).
**Audience:** the backend, database and frontend engineers building this in parallel.
**Needs sign-off before build:** the API contract (§7), the design direction (§9.5), and the open questions (§13).

---

## 1. Goal

Turn the proven single-dongle relay into a **managed fleet**. One Raspberry Pi, N RTL-SDR
dongles (some behind USB hubs/extenders), each independently named, port-assigned and tuned,
with a Vue operator console and a single JSON endpoint that Sentinel consumes to discover them.

### 1.1 Requirements traceability

| # | Requirement | Where it is satisfied |
|---|---|---|
| 1 | Live view of which USB ports hold dongles | §4 `usb_discovery` + `hotplug`; §7 `GET /api/events`; §9 `UsbTopologyTree` |
| 2 | Per-dongle name + output port, consumed exactly as today | §6 `sdr_devices`; §7 `PATCH /api/devices/{device_id}`; §8 port rules |
| 3 | Independent, concurrent tuning per dongle | §4 `supervisor` (one `rtl_tcp`+relay pair per dongle); wire contract §3.2 |
| 4 | Dongles behind hubs/extenders | §5 identity tier 2 (topology path encodes the hub tree) |
| 5 | Health endpoint (JSON) | §7.1 `GET /api/health` |
| 6 | Realtime per-SDR status (JSON) | §7.2 `GET /api/status`, §7.3 `GET /api/events` |
| 7 | Names/settings survive reboot | §6 SQLite + WAL, keyed by resolved identity (ADR-0005) |
| 8 | Web UI on the Pi's IP at a set port | §3.3 `SENTRY_HTTP_PORT`, SPA served by FastAPI |
| 9 | One endpoint for Sentinel to consume | §7.7 `GET /api/v1/sdrs` + §7.8 field mapping |

### 1.2 Non-goals

Demodulation, decoding, recording, spectrum display, any RF DSP. Sentry manages *plumbing*:
device identity, process lifecycle, ports, and status. All signal work stays in Sentinel.

---

## 2. What exists today, and what is reused

`rtl_tcp_relay.py` (675 lines) is proven in production and **is reused as the per-dongle worker
process, essentially unchanged**. It already provides everything a single dongle needs:

- fan-out of one single-client `rtl_tcp` stream to many consumers,
- dead-client reaping (TCP keepalive + bounded drop-oldest queues + drain timeout),
- the NDJSON tuning-ownership control channel on `LISTEN_PORT + 2`,
- reconnect with capped backoff and tuner-state replay on reconnect,
- full env-var configuration (`RELAY_UPSTREAM_HOST/PORT`, `RELAY_LISTEN_HOST/PORT`, `RELAY_CONTROL_PORT`).

**Exactly one change is permitted to the relay** (see §2.1). Everything else about it — protocol,
env vars, defaults, semantics — is frozen. Sentry configures N copies of it by environment and
supervises them; it does not import it, subclass it, or fork its logic.

### 2.1 The single permitted relay change: wedge exit code

The Docker socket mount is deleted (ADR-0002), so `UpstreamWatchdog` recovers a wedge by exiting
the relay process instead of calling the Docker Engine:

```
RELAY_EXIT_ON_WEDGE   = "1" | ""   (default "")
RELAY_WEDGE_EXIT_CODE = int        (default 75)
```

Once `consecutive_unhealthy >= restart_after_failures` and the cooldown has elapsed,
`note_unhealthy()` logs and calls `os._exit(RELAY_WEDGE_EXIT_CODE)`. Sentry's supervisor is the
parent, sees exit code 75, and kills+respawns the whole `rtl_tcp`+relay pair — strictly *more*
recovery than the container restart it replaced, because the wedged `rtl_tcp` is replaced too.

Sentry always sets `RELAY_EXIT_ON_WEDGE=1`. With it unset the watchdog only counts and never
acts, so the relay can still be run standalone under a supervisor that recovers it another way.

> **Amended after the initial build.** The Docker-restart branch was first kept alongside this
> one so the retained legacy compose stayed working. That compose has since been removed, leaving
> the branch with no consumer, so `_restart_container`, `RELAY_RESTART_CONTAINER` and
> `RELAY_DOCKER_SOCK` were deleted too. `enabled` is now simply `exit_on_wedge`.

`test_rtl_tcp_relay.py` moves to `tests/relay/test_rtl_tcp_relay.py` unmodified, plus new cases
for the exit branch (§12).

---

## 3. Stack and topology

### 3.1 Chosen stack

| Layer | Choice | Rationale |
|---|---|---|
| Backend | FastAPI (Python 3.12), async | Handed down by the orchestrator. Also: the relay, `librtlsdr` ctypes binding and `rtl_eeprom` glue are all Python, so one language runs the whole box. |
| ORM / migrations | SQLAlchemy 2.0 async + Alembic | Team default (`fastapi-standards`). Async so the DB never blocks the SSE event loop. |
| Database | SQLite, WAL, `synchronous=NORMAL` | Single-writer, single-host, tens of rows. The Pi loses power without warning — WAL survives it. ADR-0005. |
| Realtime | Server-Sent Events | One-way push only; native browser reconnect; no keepalive code. ADR-0004. |
| Frontend | Vue 3 + Vite + TypeScript strict + Tailwind + Pinia | Team default. |
| Serving | Production: FastAPI serves the built SPA as static files on `SENTRY_HTTP_PORT` (default **8000**). Dev: Vite on 3000 proxying `/api` → 8000. | One port on the Pi (requirement 8); no reverse proxy to install. |
| Container | One image, one container, subprocesses inside | ADR-0001. |

### 3.2 Per-dongle wire contract — byte-identical to today

For a dongle assigned output port `P`:

```
USB dongle
  └─ rtl_tcp  -a 127.0.0.1 -p 14000+slot   (loopback only, never on the LAN)
       └─ rtl_tcp_relay.py
            ├─ IQ       0.0.0.0:P       ← Sentinel / GQRX / SDR++ connect here
            └─ control  0.0.0.0:P+2     ← NDJSON claim/release/set/get + state push
```

Sentinel needs **zero protocol change per dongle**. Its existing
`settings.sdr_relay_control_port_offset = 2` already derives `P+2`. All Sentry adds is a way to
learn *which* `P` values exist.

### 3.3 Process tree inside the one container

```
PID 1  tini
  └─ uvicorn (FastAPI)                       ← API + SPA + SSE, :8000
       └─ supervisor task (asyncio, in-process)
            ├─ pair[slot 0]  rtl_tcp(:14000) + relay(:1234/:1236)
            ├─ pair[slot 1]  rtl_tcp(:14001) + relay(:1235/:1237)
            └─ …
```

The supervisor is an asyncio task inside the API process, but the **relays are real OS
subprocesses**, not asyncio tasks: ~4 MB/s per dongle must not contend with the HTTP event loop,
and a relay crash must not take the API down with it. The supervisor only spawns, watches
`wait()`, and kills — it never touches an IQ byte.

### 3.4 Configuration (env)

| Variable | Default | Purpose |
|---|---|---|
| `SENTRY_HTTP_HOST` | `0.0.0.0` | API/SPA bind |
| `SENTRY_HTTP_PORT` | `8000` | API/SPA port (requirement 8) |
| `SENTRY_ADVERTISED_HOST` | *unset* | Host published in `/api/v1/sdrs`; when unset, derived from the request `Host` header |
| `SENTRY_DATABASE_URL` | `sqlite+aiosqlite:////data/sentry.db` | Persistence (volume-mounted) |
| `SENTRY_AUTH_TOKEN` | *unset* | Unset ⇒ **no auth**. Set ⇒ bearer token required (§7.9) |
| `SENTRY_MAX_DEVICES` | `8` | Bounds the internal port range and USB bandwidth |
| `SENTRY_INTERNAL_PORT_BASE` | `14000` | Loopback `rtl_tcp` range `[base, base+MAX_DEVICES)` |
| `SENTRY_RESERVED_PORTS` | `""` | Extra operator deny-list, comma-separated |
| `SENTRY_SYSFS_ROOT` | `/sys` | Overridden by tests to a fixture tree |
| `SENTRY_RECONCILE_INTERVAL_S` | `2.0` | Sysfs sweep period (hotplug safety net) |
| `SENTRY_RTL_TCP_PATH` | `rtl_tcp` | Binary path |
| `SENTRY_RTL_EEPROM_PATH` | `rtl_eeprom` | Binary path |
| `SENTRY_RELAY_PATH` | `/app/relay/rtl_tcp_relay.py` | The unchanged relay |
| `SENTRY_LOG_LEVEL` | `INFO` | |

Nothing secret is ever committed; `.env` is git-ignored and `.env.example` documents every
variable with placeholders.

---

## 4. Module boundaries

Dependency rule, enforced by review and an import-linter check in CI:

```
routers  →  services  →  interfaces (Protocols)  ←  adapters
                    ↘  repositories → models
```

Routers never import adapters. Services never import `fastapi`. Adapters never import services.
Every service takes its collaborators through its constructor — there are no module-level
singletons except the composition root in `main.py`.

### 4.1 Interfaces — `backend/interfaces/`

Narrow Protocols. **This layer is the entire testability strategy**: swap the adapter and the
whole system runs on a developer macOS laptop with no dongles, no sysfs and no udev.

| File | Protocol | Contract |
|---|---|---|
| `usb.py` | `UsbDiscovery` | `enumerate() -> Sequence[UsbDeviceSnapshot]` — one synchronous, side-effect-free snapshot of every USB device currently present |
| `usb.py` | `HotplugSource` | `async events() -> AsyncIterator[HotplugEvent]`, `close()` — a stream of add/remove notifications |
| `process.py` | `ProcessSpawner` | `async spawn(argv: Sequence[str], env: Mapping[str,str], name: str) -> ManagedProcess` |
| `process.py` | `ManagedProcess` | `pid: int`, `returncode: int \| None`, `async wait() -> int`, `terminate()`, `kill()` |
| `rtlsdr.py` | `RtlSdrLibrary` | `device_count() -> int`, `usb_strings(index: int) -> RtlSdrUsbStrings` — the librtlsdr enumeration used to resolve a serial to an index |
| `netprobe.py` | `PortProber` | `is_bindable(host: str, port: int) -> bool` — pre-flight TCP bind test |
| `netprobe.py` | `SocketStatsSource` | `established_peers(port: int) -> int \| None` — connected-client counts; `None` when unsupported |
| `clock.py` | `Clock` | `now_ms() -> int`, `monotonic() -> float`, `async sleep(seconds: float)` — makes backoff, debounce and cooldown deterministic in tests |

Value types (all frozen dataclasses, no behaviour, defined in `interfaces/types.py`):

```python
@dataclass(frozen=True, slots=True)
class UsbDeviceSnapshot:
    topology_path: str          # "1-1.4.2" — bus-port.port.port, encodes the hub tree
    bus_number: int             # 1
    port_chain: tuple[int, ...] # (1, 4, 2)
    device_address: int         # kernel devnum; UNSTABLE, display only
    vendor_id: str              # "0bda" lowercase hex, no 0x
    product_id: str             # "2838"
    serial: str | None          # iSerial, None when absent
    manufacturer: str | None
    product: str | None
    driver: str | None          # bound kernel driver, e.g. "dvb_usb_rtl28xxu" ⇒ blacklist not applied
    sysfs_path: str             # absolute, for diagnostics only

@dataclass(frozen=True, slots=True)
class HotplugEvent:
    action: Literal["add", "remove"]
    topology_path: str
    source: Literal["udev", "reconcile"]
    observed_at_ms: int
```

### 4.2 Adapters — `backend/adapters/`

| File | Class | Notes |
|---|---|---|
| `sysfs_usb.py` | `SysfsUsbDiscovery(root: Path)` | Real `UsbDiscovery`. Walks `{root}/bus/usb/devices/*`, skips roothubs and interface nodes (`:` in the name), reads `busnum`/`devnum`/`idVendor`/`idProduct`/`serial`/`manufacturer`/`product`, resolves the bound driver via the interface subdirectory symlink. **Parameterising the root is what makes it testable**: production passes `/sys`, tests pass `tests/fixtures/sysfs/<scenario>/`. The production code path and the tested code path are the same code. |
| `fixture_usb.py` | `ScriptedUsbDiscovery(snapshots: Sequence[Sequence[UsbDeviceSnapshot]])` | Returns a different snapshot on each `enumerate()` call, then repeats the last. Drives reconcile-sweep and plug/unplug tests without touching a filesystem. |
| `udev_netlink.py` | `UdevNetlinkHotplugSource` | Real `HotplugSource`. `AF_NETLINK`/`NETLINK_KOBJECT_UEVENT` socket, group 2 (udev). **Split deliberately**: `parse_uevent(payload: bytes) -> HotplugEvent \| None` is a pure module-level function tested against captured real payloads; only the socket `bind`/`recv` loop is untestable (§12.9). |
| `reconcile_hotplug.py` | `ReconcileHotplugSource(discovery, clock, interval_s)` | The safety net. Diffs consecutive `enumerate()` snapshots every ~2 s and emits `source="reconcile"` events for anything netlink missed. Fully testable with `ScriptedUsbDiscovery` + a fake `Clock`. |
| `composite_hotplug.py` | `CompositeHotplugSource(primary, fallback)` | Merges both streams and de-duplicates by `(action, topology_path)` within a 1 s window, so a device seen by both produces one event. If the primary raises on construction (no netlink — macOS), it degrades to fallback-only and reports `source: "reconcile"` in `/api/health`. |
| `asyncio_process.py` | `AsyncioProcessSpawner` | Real `ProcessSpawner` over `asyncio.create_subprocess_exec`. Always a list argv, never `shell=True`. Sets `start_new_session=True` so a pair can be killed as a process group. |
| `fake_process.py` | `FakeProcessSpawner` | Records every `(argv, env, name)`; hands back `FakeManagedProcess` whose exit code and timing the test drives. The supervisor's crash/backoff/wedge logic is exercised entirely through this. |
| `ctypes_rtlsdr.py` | `CtypesRtlSdrLibrary` | Real `RtlSdrLibrary`. `CDLL("librtlsdr.so.0")`; `rtlsdr_get_device_count()`, `rtlsdr_get_device_usb_strings(index, buf256×3)`. Only the `CDLL` load and symbol binding are untestable (§12.9); buffer decoding is a pure helper and is tested. |
| `fake_rtlsdr.py` | `FakeRtlSdrLibrary(entries)` | Scriptable enumeration order, duplicate serials, and mid-run reordering. |
| `net.py` | `SocketPortProber`, `ProcNetTcpSocketStats(proc_root: Path)` | Real bind probe; `/proc/net/tcp{,6}` parser (root-parameterised, so a fixture file tests the parser). Returns `None` on non-Linux. |
| `system_clock.py` | `SystemClock` | Real `Clock`. Tests use `FakeClock` from `tests/fakes/`. |

### 4.3 Services — `backend/services/`

Each has exactly one responsibility and takes its dependencies by constructor injection.

| Module | Single responsibility | Depends on |
|---|---|---|
| `usb_discovery.py` | Turn raw `UsbDeviceSnapshot`s into *candidate SDRs*: filter to known RTL-SDR USB IDs (`0bda:2832`, `0bda:2838`, `0bda:2834`, `0bda:2837`, `1d19:1101`, `0ccd:00a9`, plus an env-extendable allow-list), normalise fields, and flag `driver_conflict` when the DVB kernel driver is still bound. | `UsbDiscovery` |
| `hotplug.py` | Own the event stream. Consume `HotplugSource`, debounce bursty re-enumeration (200 ms coalesce window per topology path), and publish `DeviceArrived`/`DeviceDeparted` on the event bus. Also owns the health signal "is the primary source alive". | `HotplugSource`, `usb_discovery`, `Clock`, `event_bus` |
| `identity.py` | The three-tier identity decision, and only that. Pure functions over snapshots — no I/O. Produces a `DeviceIdentity(kind, key, confidence)` or `None` (⇒ needs identification). §5. | — (pure) |
| `device_registry.py` | The in-memory authoritative fleet state: merge *persisted config* (from the repository) with *live presence* (from hotplug) into `DeviceStatus` records; own the state machine transitions (§10); emit `device_changed` on the event bus. The single source of truth every router reads. | `identity`, `DeviceRepository`, `event_bus`, `Clock` |
| `port_allocator.py` | Validate and reserve `(P, P+2)`. Pure rule evaluation plus one optional bind probe. Never picks a port on its own — it validates a user's choice and *suggests* a next free one. §8. | `PortProber`, `DeviceRepository` |
| `supervisor.py` | Process lifecycle only. For each enabled+present+configured device: resolve the librtlsdr index by serial *at spawn time*, spawn `rtl_tcp` then the relay, watch both, restart the pair on any exit with capped backoff, stop pairs whose device left or was disabled, and reconcile the running set against the desired set on every registry change. | `ProcessSpawner`, `RtlSdrLibrary`, `device_registry`, `Clock`, `event_bus` |
| `control_follower.py` | One NDJSON follower connection per running relay's `P+2`. Connects, **never claims the token**, reads `state` events, and feeds live `center_hz`/`sample_rate`/`gain_db`/`gain_auto`/`locked` into the registry. Reconnects with backoff. This is how the UI shows real tuning without fighting Sentinel for ownership. | `device_registry`, `Clock` |
| `eeprom.py` | The guarded `rtl_eeprom -s` flow: validate charset, assert the device is quiesced, take a per-device lock, stop the pair, exec with list args, parse the result, migrate the persisted identity, mark `requires_replug`. §7.6. | `ProcessSpawner`, `RtlSdrLibrary`, `supervisor`, `device_registry` |
| `event_bus.py` | In-process fan-out to SSE subscribers. Bounded per-subscriber queue with drop-oldest (same discipline the relay already uses for IQ clients — a slow browser must never stall the bus). Coalesces repeated `device_changed` for the same device within 100 ms. | — |
| `health.py` | Assemble the health snapshot from the registry, the hotplug source and a DB ping. | `device_registry`, `hotplug`, `DeviceRepository` |

**Explicitly not a service:** anything that formats JSON for HTTP. That is the schema layer.

### 4.4 Repository, models, schemas, routers

```
backend/
  main.py                  composition root: build adapters, wire services, mount routers, lifespan
  config.py                pydantic-settings Settings; the ONLY place os.environ is read
  db.py                    async engine + sessionmaker + the WAL PRAGMA connect hook
  models.py                SQLAlchemy 2.0 DeclarativeBase models (§6)
  repositories/
    device_repository.py   the only module that writes sdr_devices
  schemas/
    device.py              DeviceStatus, DeviceRecord, DevicePatch, UsbInfo, OutputInfo, TunerInfo, ProcessInfo
    health.py              HealthResponse
    events.py              SSE payload envelopes
    serial.py              SerialFlashRequest / SerialFlashAccepted
    sdr_export.py          SdrExportResponse / SdrExportItem  ← the versioned Sentinel contract
  routers/
    api.py                 aggregator: include_router for each domain under /api
    health.py              GET /api/health
    status.py              GET /api/status
    events.py              GET /api/events   (SSE)
    devices.py             GET/PATCH/DELETE /api/devices…, POST …/serial
    sdrs.py                GET /api/v1/sdrs  (+ /api/sdrs alias)
  security.py              bearer-token dependency (no-op when SENTRY_AUTH_TOKEN unset)
  relay/rtl_tcp_relay.py   VENDORED, frozen except §2.1
```

One router per resource, aggregated under `/api` — never one overloaded router.

---

## 5. Device identity — three tiers

RTL-SDR dongles routinely ship with the factory serial `00000001`, and `rtl_tcp -d <index>`
addresses by **librtlsdr enumeration order, which is not stable across reboots or replugs**.
Identity therefore has two independent jobs, and conflating them is the classic bug here:

- **Persistence key** — what a saved name and port are attached to. Stable across reboots.
- **Spawn address** — the `-d <index>` passed to `rtl_tcp`. Valid only for this instant.

### 5.1 Persistence key (tiers)

| Tier | Key form | Chosen when | Survives |
|---|---|---|---|
| 1 | `serial:<value>` | The device reports a serial that is **non-empty, not in the known-default set** (`00000001`, `00000000`, `0000001`, empty, whitespace), and is **unique among all currently present devices** | Replugging into any port, reboot, hub changes |
| 2 | `usb:<topology_path>` e.g. `usb:1-1.4.2` | Tier 1 unavailable, but the topology path is unambiguous | Reboot, and any hub topology that is not rewired. Naturally handles extenders — `1-1.4.2` *is* "bus 1, root port 1, hub port 4, hub port 2" |
| 3 | *none* | Two present devices collapse to the same key (duplicate factory serials plugged into a hub whose path also can't disambiguate — e.g. an unenumerated topology), or sysfs data is incomplete | Nothing — surfaced in the UI as **needs identification** with a "give this dongle a unique serial" call to action |

Tier 3 is **never silently guessed**. A tier-3 device gets `needs_identification: true`, no
persisted row, no spawned pair, and a UI prompt to flash a serial (§7.6). Guessing here means a
user's "ADSB SDR" name silently migrates to their AIS dongle after a reboot — unacceptable.

`identity.resolve(snapshots) -> dict[topology_path, DeviceIdentity | None]` is a **pure
function over the whole snapshot set** (uniqueness is a set-wide property, so it cannot be
decided per-device). It is the highest-value unit-test target in the codebase.

### 5.2 Identity migration

Tier promotion is allowed and expected; demotion is not.

- A `usb:1-1.4.2` row whose device later reports a unique serial (because the user flashed it)
  is **migrated to `serial:<new>`**, preserving `id`, name, port and tuning. `eeprom.py` performs
  this write inside the flash transaction.
- A `serial:X` row whose device stops reporting a serial is **not** demoted — it is simply
  reported absent, so a firmware glitch never orphans configuration.

### 5.3 Spawn address — resolved every time, cached never

At spawn, `supervisor` calls `RtlSdrLibrary.device_count()` and
`usb_strings(i)` for each index, matching on `(serial, manufacturer, product)` to find the index
for this device *right now*. Failure modes and their handling:

| Situation | Handling |
|---|---|
| Exactly one index matches the serial | Spawn `rtl_tcp -d <index>` |
| No index matches | Do not spawn. `state=error`, `state_reason=index_unresolved` |
| Multiple indices match (duplicate serials) | Do not spawn. `state=error`, `state_reason=ambiguous_index`, UI offers serial flashing |
| `device_count()` == 0 but sysfs shows a device | `state=error`, `state_reason=driver_conflict` (DVB module bound — README's blacklist step not applied). The message names the fix. |

The index is **never cached** between spawns, not even for a restart-after-crash.

---

## 6. Data model

One table. The DB holds **user intent**, not observed reality — detected-but-unconfigured
devices exist only in memory, so a row's existence means "the operator configured this".

### 6.1 `sdr_devices`

| Column | Type | Constraints | Purpose |
|---|---|---|---|
| `id` | INTEGER | PK autoincrement | Internal surrogate key |
| `identity_kind` | TEXT | NOT NULL, CHECK IN (`serial`,`usb`) | Which tier this row is keyed by |
| `identity_key` | TEXT | NOT NULL | The serial value or topology path |
| `name` | TEXT | NOT NULL | Operator label, e.g. "ADSB SDR" |
| `description` | TEXT | NOT NULL DEFAULT `''` | Free text, exported to Sentinel |
| `output_port` | INTEGER | NOT NULL | `P`. `P+2` is implicitly reserved |
| `enabled` | BOOLEAN | NOT NULL DEFAULT 1 | Whether the supervisor should run a pair |
| `center_hz` | INTEGER | NULL | Startup tuning; NULL ⇒ relay default (100 MHz) |
| `sample_rate` | INTEGER | NULL | NULL ⇒ relay default (2 048 000) |
| `gain_db` | REAL | NULL | NULL ⇒ relay default (30.0) |
| `gain_auto` | BOOLEAN | NOT NULL DEFAULT 1 | |
| `ppm_correction` | INTEGER | NOT NULL DEFAULT 0 | Passed as `rtl_tcp -P <ppm>` |
| `last_topology_path` | TEXT | NOT NULL DEFAULT `''` | Last-seen USB path, even for serial-keyed rows — lets the UI show "was in port 1-1.4.2" while absent |
| `last_vendor_id` | TEXT | NOT NULL DEFAULT `''` | Cached hardware description so an absent device still renders |
| `last_product_id` | TEXT | NOT NULL DEFAULT `''` | |
| `last_manufacturer` | TEXT | NOT NULL DEFAULT `''` | |
| `last_product` | TEXT | NOT NULL DEFAULT `''` | |
| `last_serial` | TEXT | NOT NULL DEFAULT `''` | The raw reported serial, even when tier 2 |
| `last_seen_at` | INTEGER | NULL | Unix ms |
| `pending_replug_until` | INTEGER | NULL | Unix ms; set after a serial flash, suppresses "missing device" alarms |
| `created_at` | INTEGER | NOT NULL | Unix ms |
| `updated_at` | INTEGER | NOT NULL | Unix ms |

Indexes / constraints:

```
UNIQUE INDEX ux_sdr_devices_identity  ON sdr_devices (identity_kind, identity_key)
UNIQUE INDEX ux_sdr_devices_port      ON sdr_devices (output_port)
CHECK (output_port BETWEEN 1024 AND 65533)
CHECK (length(name) BETWEEN 1 AND 64)
```

`ux_sdr_devices_port` is the last line of defence behind the allocator: a race between two
concurrent PATCHes cannot produce two dongles on one port. The router catches `IntegrityError`
and returns `409 port_conflict`.

Note there is deliberately **no `slot` column**. The internal loopback port is
`SENTRY_INTERNAL_PORT_BASE + slot` where `slot` is assigned by the supervisor at runtime from
the set of running pairs — it is ephemeral and must not persist.

### 6.2 Migration plan

Single initial migration `alembic/versions/0001_initial_fleet.py`:

- `op.create_table("sdr_devices", …)` with every column, both unique indexes and both CHECKs.
- No data migration. The existing deployment has no database; the one hard-wired dongle is
  re-registered through the UI (a one-time, ~30-second operator action, documented in the README
  migration section).
- Downgrade drops the table.

`alembic/env.py` runs in async mode (`run_sync` inside `async_engine.connect()`), imports
`Base.metadata` from `backend/models.py`, and enables `render_as_batch=True` so future SQLite
ALTERs work (SQLite cannot drop or alter a column in place).

Migrations run **on startup** in `lifespan` (`command.upgrade(config, "head")`) — the Pi has no
operator shell in the normal path, so an unattended reboot must self-heal the schema. A
migration failure aborts startup loudly rather than serving a half-schema.

### 6.3 WAL and durability

`db.py` registers a `connect` event on the sync engine:

```
PRAGMA journal_mode  = WAL;        -- survives a power cut mid-write; readers never block the writer
PRAGMA synchronous   = NORMAL;     -- WAL + NORMAL is crash-safe (loses at most the last txn on OS crash)
PRAGMA busy_timeout  = 5000;       -- 5 s, rather than an instant SQLITE_BUSY under concurrent SSE reads
PRAGMA foreign_keys  = ON;
```

Rationale and the alternatives considered: ADR-0005.

---

## 7. API contract

Two independently-versioned surfaces:

- **Internal UI API** — `/api/health`, `/api/status`, `/api/events`, `/api/devices*`. Ships with
  the SPA in the same image, so it is unversioned and may change freely between releases.
- **Consumer API** — `/api/v1/sdrs`. Consumed by a *separately deployed* Sentinel, so it is
  versioned, additive-only within a major, and never changed to suit the UI. `/api/sdrs` is a
  permanent convenience alias serving the current stable version; both responses carry
  `X-Sentry-Sdr-Api-Version: 1`.

Conventions: all timestamps are integer Unix **milliseconds** (matching Sentinel). All errors
use `{"detail": {"code": "<machine_code>", "message": "<human>", …context}}`. `device_id` is the
public key everywhere: the string `serial:<value>` or `usb:<path>`; the DB integer appears only
as `record_id`.

### 7.1 `GET /api/health`

Auth-exempt (the Docker healthcheck must reach it). 200 unless the database is unreachable, in
which case 503 with the same body shape — a flapping healthcheck on a degraded dongle would
restart the container and take the *healthy* dongles down with it.

```json
{
  "status": "ok",
  "version": "1.0.0",
  "started_at": 1753789000000,
  "uptime_s": 3612.4,
  "database": "ok",
  "hotplug": { "source": "udev", "healthy": true, "last_event_at": 1753790100000 },
  "devices": { "present": 3, "configured": 3, "streaming": 2, "degraded": 1, "error": 0, "needs_identification": 0 }
}
```

`status` is `"ok"` | `"degraded"` (any device in `degraded`/`error`, or hotplug fell back to
reconcile-only) | `"unhealthy"` (database down, HTTP 503). `hotplug.source` is `"udev"` |
`"reconcile"`.

### 7.2 `GET /api/status`

The realtime per-SDR view (requirement 6). Identical payload to the SSE `snapshot` event.

```json
{
  "generated_at": 1753790123456,
  "sdrs": [
    {
      "device_id": "serial:ADSB-01",
      "record_id": 3,
      "identity_kind": "serial",
      "identity_key": "ADSB-01",
      "needs_identification": false,
      "name": "ADSB SDR",
      "description": "Roof, 1090 MHz",
      "state": "streaming",
      "state_since": 1753789200000,
      "state_reason": null,
      "present": true,
      "enabled": true,
      "usb": {
        "topology_path": "1-1.4.2",
        "bus_number": 1,
        "port_chain": [1, 4, 2],
        "hub_depth": 2,
        "device_address": 7,
        "vendor_id": "0bda",
        "product_id": "2838",
        "manufacturer": "Realtek",
        "product": "RTL2838UHIDIR",
        "serial": "ADSB-01",
        "driver": "rtl2832u",
        "driver_conflict": false
      },
      "output": { "host": "192.168.1.45", "iq_port": 1234, "control_port": 1236 },
      "tuner": {
        "center_hz": 1090000000,
        "sample_rate": 2400000,
        "gain_db": 40.2,
        "gain_auto": false,
        "locked": true,
        "observed_at": 1753790120000
      },
      "processes": {
        "rtl_tcp_pid": 812,
        "relay_pid": 813,
        "internal_port": 14000,
        "restarts": 0,
        "last_restart_at": null,
        "last_exit_code": null
      },
      "clients": { "iq": 2, "control": 1 },
      "last_seen_at": 1753790123000
    }
  ]
}
```

Notes for implementers:

- `usb` is `null` when the device is configured but absent; the `last_*` columns then populate a
  reduced `usb_last_known` object instead.
- `tuner` is `null` until `control_follower` has received its first `state` event.
- `clients` comes from `SocketStatsSource` (`/proc/net/tcp`); it is `null` on platforms where
  that is unavailable, and consumers must treat it as advisory.
- Devices detected but not configured appear with `record_id: null`, `state: "detected"` and no
  `output` block. The array is sorted by `usb.topology_path`, absent devices last.

### 7.3 `GET /api/events` — SSE

`Content-Type: text/event-stream`, `Cache-Control: no-store`, `X-Accel-Buffering: no`. The
stream opens with `retry: 3000` and a full `snapshot`.

| Event | Payload | When |
|---|---|---|
| `snapshot` | The whole `GET /api/status` body | On connect, and after any internal resubscribe |
| `device_changed` | One `DeviceStatus` object | Any field change, coalesced per device over 100 ms |
| `device_removed` | `{"device_id": "usb:1-1.4.3", "record_id": null}` | An unconfigured device is unplugged (configured ones become `state: "stopped"`, `present: false` via `device_changed` — they are never removed) |
| `health` | The `GET /api/health` body | Every 5 s; doubles as the keepalive |
| `notice` | `{"level":"info"\|"warn"\|"error","code":"…","message":"…","device_id":…\|null,"ts":…}` | Serial-flash progress, spawn failures, port conflicts, driver conflicts |

`Last-Event-ID` is accepted and **ignored**: there is no replay buffer, and every reconnect gets
a fresh `snapshot`, which is strictly more correct than replaying a partial delta log. Each
subscriber has a bounded queue with drop-oldest; overflow forces a `snapshot` on the next flush
so a slow client self-heals instead of drifting. Rationale for SSE over WebSocket: ADR-0004.

### 7.4 `GET /api/devices`

Configuration-centric list — includes configured-but-absent devices and detected-but-unconfigured
ones, so the UI can render the whole picture from one call.

```json
{
  "devices": [
    {
      "device_id": "serial:ADSB-01",
      "record_id": 3,
      "identity_kind": "serial",
      "identity_key": "ADSB-01",
      "name": "ADSB SDR",
      "description": "Roof, 1090 MHz",
      "output_port": 1234,
      "control_port": 1236,
      "enabled": true,
      "center_hz": 1090000000,
      "sample_rate": 2400000,
      "gain_db": 40.2,
      "gain_auto": false,
      "ppm_correction": 0,
      "present": true,
      "needs_identification": false,
      "state": "streaming",
      "last_topology_path": "1-1.4.2",
      "last_serial": "ADSB-01",
      "last_seen_at": 1753790123000,
      "created_at": 1753000000000,
      "updated_at": 1753789000000
    }
  ],
  "port_suggestion": 1238,
  "constraints": {
    "port_min": 1024, "port_max": 65533,
    "reserved": [8000],
    "internal_range": [14000, 14008],
    "in_use": [1234, 1236]
  }
}
```

`constraints` lets the frontend mirror the allocator rules for instant inline validation without
duplicating the rule *table* — the server remains the authority and re-validates everything.

### 7.5 `PATCH /api/devices/{device_id}`

Creates the row on first call for a detected device (upsert) and updates it thereafter. All
fields optional; at least one required.

```json
{
  "name": "ADSB SDR",
  "description": "Roof, 1090 MHz",
  "output_port": 1234,
  "enabled": true,
  "center_hz": 1090000000,
  "sample_rate": 2400000,
  "gain_db": 40.2,
  "gain_auto": false,
  "ppm_correction": 0
}
```

Validation (Pydantic, all bounds enforced at the edge):

| Field | Rule |
|---|---|
| `name` | 1–64 chars after strip; allow-list `^[A-Za-z0-9 _.\-()/]+$`; must be unique across devices (case-insensitive) |
| `description` | ≤ 256 chars |
| `output_port` | §8 rules; `409` on conflict |
| `center_hz` | 24 000 000 – 1 766 000 000 (R820T tuning range) |
| `sample_rate` | Must be one of the librtlsdr-supported rates: 250000, 1024000, 1200000, 1536000, 1800000, 1920000, 2048000, 2160000, 2400000, 2560000, 2880000, 3200000. Rates above 2 400 000 are accepted but return a `notice` warning about USB sample drops on a Pi. |
| `gain_db` | 0.0 – 50.0 |
| `ppm_correction` | −200 – 200 |

Responses: `200` with the `DeviceRecord`; `400 validation_error`; `404 unknown_device` (the
device_id is neither persisted nor currently detected); `409 port_conflict` with
`{"code":"port_conflict","port":1234,"conflicts_with":"serial:AIS-02"}`; `409 name_conflict`;
`422 device_unidentified` (attempt to configure a tier-3 device).

**Side effects.** Changing `output_port`, `ppm_correction` or `enabled` restarts *only that
device's pair* (`state → starting`). Changing `center_hz`/`sample_rate`/`gain_db`/`gain_auto`
does **not** restart: `control_follower` briefly claims the token, issues one `set`, releases —
so a live Sentinel consumer sees the retune rather than a stream drop. If Sentinel currently
holds the token, the request returns `200` with `"tuning_deferred": true` and the value is
applied at the next pair start. Changing `name`/`description` has no process side effect.

### 7.6 `POST /api/devices/{device_id}/serial`

Writes a unique serial to the dongle's EEPROM so it can be promoted to identity tier 1.

```json
{ "serial": "SENTRY-ADSB-01", "confirm": true }
```

Guards, all enforced server-side:

1. `confirm` must be exactly `true`.
2. `serial` must match `^[A-Za-z0-9_-]{1,32}$` — a strict allow-list, not a deny-list.
3. `serial` must not equal any other known device's serial or persisted `identity_key`.
4. The device must be present and **idle**: `state` in `{detected, configured, stopped}`. A
   `streaming`/`starting` device returns `409 device_busy` — the operator must disable it first.
   The endpoint never silently interrupts a live feed.
5. A per-device asyncio lock is held for the whole operation so hotplug cannot respawn a pair
   mid-write, and two flashes cannot race.
6. Execution is `ProcessSpawner.spawn(["rtl_eeprom", "-d", str(resolved_index), "-s", serial])` —
   **a list argv, never a shell string**, with the index resolved immediately beforehand (§5.3)
   and a 30 s timeout. `rtl_eeprom`'s interactive confirmation is fed a literal `y\n` on stdin.

`202 Accepted`:

```json
{ "device_id": "usb:1-1.4.2", "operation_id": "0f3c…", "status": "in_progress", "requires_replug": true }
```

Progress and outcome arrive as SSE `notice` events keyed by `operation_id`. On success the
persisted row's identity is migrated to `serial:<new>` and `pending_replug_until` is set to
now + 120 s, during which the device's absence is reported as `state: "stopped"`,
`state_reason: "awaiting_replug"` rather than an alarm. **A physical replug (or a USB port power
cycle) is required** before the new serial is visible — the UI says so plainly.

Errors: `400 invalid_serial`; `409 device_busy`; `409 serial_in_use`; `422 device_unidentified`
when the index cannot be resolved; `503 rtl_eeprom_unavailable`; `500 flash_failed` with a
truncated (≤ 500 char) stderr tail. Stderr is truncated and never echoed as HTML.

### 7.7 `GET /api/v1/sdrs` — the Sentinel contract

The single endpoint of requirement 9. Lists every **configured** device, whether or not it is
currently present, each with an `available` flag — so a briefly-unplugged dongle does not
disappear from Sentinel's radio list and lose the user's selection.

```json
{
  "api_version": 1,
  "generated_at": 1753790123456,
  "source": { "name": "sentry", "version": "1.0.0", "host": "192.168.1.45", "http_port": 8000 },
  "control_port_offset": 2,
  "sdrs": [
    {
      "sentry_device_id": "serial:ADSB-01",
      "name": "ADSB SDR",
      "host": "192.168.1.45",
      "port": 1234,
      "control_port": 1236,
      "description": "RTL2838UHIDIR @ USB 1-1.4.2",
      "enabled": true,
      "bandwidth": 2400000,
      "rf_gain": 40.2,
      "agc": false,
      "available": true,
      "state": "streaming"
    }
  ]
}
```

Query parameters: `?include_disabled=true` (default `false`) adds rows with `enabled: false`;
`?available_only=true` (default `false`) drops absent devices.

`host` resolution order: `SENTRY_ADVERTISED_HOST` if set, else the request's `Host` header with
any port stripped. Never `0.0.0.0` and never a container-internal address — Sentinel dials this
value from another machine.

### 7.8 Field mapping onto Sentinel's model

Sentinel's radio shape is defined by `backend/routers/sdr.py::RadioIn` and mirrored by
`backend/models.py::SdrRadio` (identical field sets). Note that in the *current* Sentinel code
the `SdrRadio` **table is declared but unused** — radios are persisted as a JSON array under
`UserSettings` key `sdr.radios` via `_get_radios`/`_save_radios`, and the frontend type is
`stores/sdr.ts::SdrRadio`. The mapping below is designed so it lands cleanly on **either**
store, because the field names are the same in both (see open question §13.4).

| `/api/v1/sdrs` field | Sentinel `SdrRadio` / `RadioIn` field | Notes |
|---|---|---|
| `name` | `name` (TEXT NOT NULL) | Direct. Sentry constrains to 1–64 chars, so it always fits. |
| `host` | `host` (TEXT NOT NULL) | The Pi's LAN address. Direct. |
| `port` | `port` (INTEGER DEFAULT 1234) | The relay's IQ port `P`. Direct — Sentinel connects exactly as it does today. |
| `description` | `description` (TEXT DEFAULT `''`) | Sentry composes `"<product> @ USB <topology_path>"` when the operator left it blank, so the dropdown is self-explaining. |
| `enabled` | `enabled` (BOOLEAN DEFAULT 1) | Direct. |
| `bandwidth` | `bandwidth` (INTEGER NULL) | Sentry's `sample_rate`. Sentinel's column is documented as "Hz sample rate; None = rtl_tcp default" — semantically identical. `null` maps to `null`. |
| `rf_gain` | `rf_gain` (FLOAT NULL) | Sentry's `gain_db`. `null` when `gain_auto` is true. |
| `agc` | `agc` (BOOLEAN NULL) | Sentry's `gain_auto`. |
| `sentry_device_id` | **new field** | The idempotency key. Sentinel stores it so a re-import updates rather than duplicates. Additive: a new nullable `TEXT` column on `SdrRadio`, or simply a new key in the `sdr.radios` JSON object — no migration needed in the JSON case. |
| `control_port` | *derived, not stored* | Sentinel already computes `port + settings.sdr_relay_control_port_offset` (= 2). Sent for verification only; if it ever disagrees with `port + 2`, Sentinel should trust this field. |
| `available`, `state` | *not persisted* | Display-only: grey out an unavailable radio in `SdrDeviceSelector.vue` rather than hiding it. |
| — | `id` (INTEGER PK) | **Sentinel-owned.** Sentry never sends it. Sentinel allocates on import, matched on `sentry_device_id`. |
| — | `created_at` (INTEGER) | **Sentinel-owned.** Set at import time. |

Import algorithm Sentinel should use (one loop, idempotent, no deletions without confirmation):

```
for item in sentry.sdrs:
    existing = find(radios, r.sentry_device_id == item.sentry_device_id)
    if existing: update mapped fields, keep id/created_at
    else:        append {id: next_id, created_at: now_ms(), sentry_device_id: …, …mapped}
mark radios whose sentry_device_id is absent from the response as stale (do not auto-delete)
```

The total churn in Sentinel is: one fetch, one field added to `RadioIn`/`SdrRadio`/`SdrRadio.ts`,
and one "Import from Sentry" button. Nothing about the rtl_tcp connection path changes at all.

### 7.9 Authentication

`SENTRY_AUTH_TOKEN` unset ⇒ **auth is off** and every endpoint is open (the default; a
single-purpose device on a trusted LAN). Set ⇒ a FastAPI dependency requires
`Authorization: Bearer <token>` on every `/api/**` route, compared with
`secrets.compare_digest`, returning `401` with `WWW-Authenticate: Bearer` and no detail about
why. `GET /api/health` is always exempt.

`EventSource` cannot set headers, so when auth is on `GET /api/events` **additionally** accepts
`?access_token=<token>`. This is a documented, deliberate trade-off: query strings can leak into
access logs, so Sentry's uvicorn access-log format is configured to strip query strings, and the
token is compared with the same constant-time function. See §13.3 — an alternative
cookie-session design is offered for sign-off.

CORS is closed by default (`allow_origins=[]`); the SPA is same-origin. `SENTRY_CORS_ORIGINS`
allows an explicit list for a separately-hosted Sentinel dev server. Never `*`.

---

## 8. Port allocation rules

Assignment is **manual with validation** — the operator types the port, Sentry accepts or
rejects with a specific reason and offers a suggestion. Auto-assignment was rejected because the
port number is part of Sentinel's stored configuration; a silently-reassigned port breaks a
consumer that was working yesterday.

For a proposed `P`, reserving `{P, P+2}`, reject if **any** of:

| # | Rule | Error code |
|---|---|---|
| 1 | `P < 1024` or `P + 2 > 65535` | `port_out_of_range` |
| 2 | `P` or `P+2` equals another device's `P_i` or `P_i + 2` — including **disabled and absent** devices, whose reservations persist | `port_conflict` |
| 3 | `P` or `P+2` equals `SENTRY_HTTP_PORT` | `port_reserved_http` |
| 4 | `P` or `P+2` falls in `[SENTRY_INTERNAL_PORT_BASE, SENTRY_INTERNAL_PORT_BASE + SENTRY_MAX_DEVICES)` — the loopback `rtl_tcp` range | `port_reserved_internal` |
| 5 | `P` or `P+2` appears in `SENTRY_RESERVED_PORTS` | `port_reserved_operator` |
| 6 | `PortProber.is_bindable("0.0.0.0", P)` or `(…, P+2)` is false **and** the port is not already held by this device's own running pair | `port_in_use` |

Note that `P+1` is **not** reserved — the relay uses only `P` and `P+2`. Consecutive assignments
`1234, 1235` are therefore legal (`{1234,1236}` and `{1235,1237}` are disjoint), while
`1234, 1236` is not. The rule engine handles this naturally by comparing the two-element sets;
do not implement it as a "+4 stride" heuristic.

`suggest_next()` returns the lowest `P ≥ 1234` passing all six rules, which yields the familiar
1234, 1238, 1242… sequence on a fresh install while remaining correct after arbitrary manual
assignment. The suggestion is advisory and appears as placeholder text, never as a silent default.

Rule 6 is a probe, not a lock: the port could be taken between validation and spawn. The
supervisor therefore treats a spawn-time `EADDRINUSE` as `state=error`,
`state_reason=port_in_use` with a `notice` — belt and braces.

---

## 9. Frontend

### 9.1 Structure

```
frontend/
  src/
    api/            client.ts, types.ts (generated from OpenAPI), sse.ts
    stores/         fleet.ts
    composables/    useServerSentEvents.ts  useFleetStream.ts  useLiveAnnouncer.ts
                    usePortValidation.ts    useTreeNavigation.ts  useDeviceActions.ts
    components/
      base/         BaseButton BaseDialog BaseField BaseBadge BaseToggle
                    StatusDot EmptyState LiveRegion CopyButton MonoValue
      fleet/        FleetHeader ConnectionPill FleetToolbar FleetLayout
      topology/     UsbTopologyTree UsbTopologyNode HubBadge PortLug TopologyLegend
      device/       DeviceCard DeviceIdentityBlock DeviceStateBadge DevicePortPair
                    DeviceTunerReadout DeviceProcessStats DeviceActionsBar
                    NeedsIdentificationNotice DeviceAbsentNotice
      forms/        DeviceConfigForm DeviceNameField OutputPortField
                    TuningFieldset EnabledToggle
      serial/       SerialFlashDialog SerialFlashWarning SerialFlashSerialField
      health/       HealthSummaryBar HealthMetric
      consumer/     SentinelEndpointCard
    views/          FleetView.vue
```

Every component is single-responsibility and composes the `base/` primitives — `DeviceCard` is
layout and composition only, holding no formatting logic of its own. `MonoValue` (tabular-figure
numeric display) and `StatusDot` are the shared atoms used everywhere a port, frequency, PID or
state appears; nothing re-implements them.

### 9.2 Pinia store — `stores/fleet.ts`

```ts
// state
devicesById: Record<string, DeviceStatus>     // keyed by device_id
order: string[]                               // stable sort by usb.topology_path, absent last
health: HealthSnapshot | null
constraints: PortConstraints | null
connection: 'connecting' | 'live' | 'reconnecting' | 'offline'
lastSnapshotAt: number | null
pendingPatchesByDeviceId: Record<string, Partial<DeviceConfig>>   // optimistic UI
notices: NoticeItem[]                                             // capped at 50, drop-oldest

// getters
presentDevices, absentConfiguredDevices, unidentifiedDevices,
topologyTree            // devices → nested hub tree, derived from port_chain
portsInUse, streamingCount, hasErrors, isDeviceBusy(deviceId)

// actions
applySnapshot(payload)      // wholesale replace; the reconnect path
applyDeviceChanged(device)  // merge one device, clearing its pending patch on match
applyDeviceRemoved(id)
applyHealth(payload)
applyNotice(notice)
patchDevice(deviceId, patch)     // optimistic; rolls back and raises a notice on failure
flashSerial(deviceId, serial)
dismissNotice(id)
```

The store never calls `EventSource` itself — `useFleetStream` owns the subscription and calls
store actions, so the store is trivially unit-testable with plain objects.

### 9.3 `useServerSentEvents` composable

Generic, app-agnostic:

```ts
useServerSentEvents(url: Ref<string> | string, handlers: Record<string, (data: unknown) => void>, options?)
  → { connection: Ref<ConnectionState>, lastEventAt: Ref<number | null>, close(): void, reopen(): void }
```

- Registers one `addEventListener` per named handler; parses JSON in one place with a typed
  guard, so a malformed frame logs a notice instead of throwing into the browser.
- Relies on the browser's native reconnect (the server sends `retry: 3000`), and layers a
  **stall detector** on top: if no event of any kind arrives within 15 s (the server sends
  `health` every 5 s), it force-closes and reopens — this catches the case the native reconnect
  misses, a proxy holding a dead-but-open stream.
- Reports `connection` as `connecting | live | reconnecting | offline`, which `ConnectionPill`
  renders and `useLiveAnnouncer` announces.
- Closes on `onScopeDispose` and on `visibilitychange` → hidden for > 60 s (a phone in a pocket
  should not hold a stream open), reopening on visible with a fresh snapshot.

### 9.4 USB topology tree — accessibility

The tree is the app's primary navigation surface, is rebuilt live as devices are plugged, and is
therefore where accessibility is easiest to get wrong. Required behaviour (WCAG 2.2 AA, ARIA
Authoring Practices *Tree View* pattern):

**Roles and structure.** Container `role="tree"` with `aria-label="USB topology"`. Each node
`role="treeitem"` with `aria-level`, `aria-setsize`, `aria-posinset`, and `aria-selected`. Hub
nodes additionally carry `aria-expanded`; leaf (dongle) nodes must **not**. Children are wrapped
in `role="group"`. The connector lines and port lugs are pure CSS/`aria-hidden` decoration.

**Keyboard.** Exactly one tab stop for the whole tree (roving `tabindex`, managed by
`useTreeNavigation`):

| Key | Action |
|---|---|
| `↓` / `↑` | Next / previous *visible* node |
| `→` | Collapsed hub → expand; expanded hub → first child; leaf → no-op |
| `←` | Expanded hub → collapse; otherwise → parent |
| `Home` / `End` | First / last visible node |
| `*` | Expand all siblings at the current level |
| `Enter` / `Space` | Select — moves focus to the matching `DeviceCard` (the node carries `aria-controls` pointing at the card's id) |
| Type-ahead | Printable characters jump to the next node whose name starts with them |

**Live updates.** Nodes appearing or disappearing must never steal or destroy focus. If the
focused node's device is unplugged, focus moves to the nearest surviving sibling, else the
parent, else the tree container, and the move is announced. Keys are `device_id`, never array
index, so Vue never recycles a DOM node between two different dongles.

**Announcements.** Two regions, both rendered once at app root by `LiveRegion`:

- `aria-live="polite"` — plug/unplug and state changes: *"AIS SDR connected on USB port 1-1.4.3,
  now streaming on port 1238."* Announcements are debounced 500 ms and coalesced ("3 devices
  connected") so a hub power-cycle does not produce a torrent.
- `role="alert"` (assertive) — errors and serial-flash outcomes only.

**Colour is never the sole indicator.** Every `DeviceStateBadge` carries a text label *and* a
distinct glyph as well as its colour; `StatusDot` is always accompanied by a visible or
screen-reader-only label. Contrast is verified ≥ 4.5:1 for text and ≥ 3:1 for the state stripes
and focus rings.

**Forms.** `OutputPortField` validates on blur (not per keystroke — a partially typed port is
not an error), links its message with `aria-describedby`, sets `aria-invalid`, and moves focus to
the first invalid field on submit. The server's `409` reason is rendered in the same message
slot as client-side validation, so there is one place to look.

**Serial-flash dialog.** `BaseDialog` provides a focus trap, `Escape` to close, focus return to
the trigger, `aria-labelledby`/`aria-describedby`, and an explicitly-checked destructive
confirmation. The warning text is in the accessible description, not only in a coloured banner.

**Reduced motion.** `prefers-reduced-motion: reduce` disables the streaming flow tick and all
enter/leave transitions; state changes become instant swaps.

---

### 9.5 Design direction — Sentinel's settings language

> **This section was rewritten by [ADR-0006](../adr/0006-adopt-sentinel-settings-visual-language.md).**
> It previously specified "Patch Bay": a near-black instrument panel with a signal-amber accent,
> chosen as a *sibling* to Sentinel so an operator with both windows open could tell them apart at
> a glance. That direction was built, then reversed — the two tools are one system and should not
> look like two products. Read the ADR for the reasoning, the risk that was accepted, and the
> alternatives rejected; this section now describes only what the UI is.

Sentry is styled as **Sentinel's settings section**: the same card grid, square corners, flat
fills, uppercase Barlow legends and light canvas. Structure, typography and palette are all
Sentinel's. Sentry identifies itself by its content — a device grid and a USB tree, unlike any
Sentinel screen — not by its chrome.

The canonical values live in `app/frontend/tailwind.config.ts`, whose header comment carries the
full contrast table. The table below is the direction, not the source of truth.

| Aspect | Direction |
|---|---|
| **Tone** | Instrument panel, restated in daylight. Dense, precise, calm at rest — on a healthy screen the only saturated colour is the accent fill on a control the operator can act on. |
| **Ground** | `#f6f6f4` canvas, `#ffffff` card, `#e8eaed` input and flat-row fill, `#e2e2df` hairlines. Sentinel's own surface values. |
| **Accent** | Lime `#c8ff00`, **as a fill only, never text or a border.** It is 1.18:1 on white — below the 3:1 non-text floor, so it can never carry meaning alone. It appears behind `#0a0c10` text (16.55:1) on the primary button, the active toggle, the heading dot and the skip link, exactly as Sentinel uses it. Where the accent is needed *as* a colour, `signal.ok` `#4a7200` is its text-safe form. |
| **Semantics** | `streaming` = `ok` `#4a7200`; `degraded` = `warn` `#8a5a00`; `error` = `danger` `#b8352a`; `starting` and structural chrome = `info` `#0c6a84`; `stopped`/`detected`/`configured` = `muted` `#66686e` for the label with `faint` `#8a8d92` for the stripe. Tokens are named for meaning, not hue, because on this palette the tone that means "lime" is an olive. Every state also carries a text label and a distinct glyph — colour is never the sole indicator. |
| **Typography** | Barlow Condensed 600 uppercase for every legend, on Sentinel's five-step tracking scale: `0.1em` card titles, `0.14em` captions, `0.16em` headings and buttons, `0.18em` control labels, `0.22em` muted group labels. Barlow 400 for prose. A true monospace with **tabular figures** (JetBrains Mono, `ui-monospace` fallback) for every port, frequency, PID, USB path and byte count — digits must not shift width as they tick. This is the one place Sentry keeps its own choice: Sentinel sets these in Barlow. |
| **Layout** | Two columns on a 44px gutter. **Left rail (320px):** the USB topology as flat data rows — 1px connector line, a neutral port lug carrying the port number, hairline-gapped rows on a faint wash. **Right:** device cards in an auto-filling grid, `minmax(min(300px,100%), 1fr)` with a 16px gutter, capped at a 1480px measure; each card spans two columns to fit its side-by-side name and port fields. Each card carries a 3px left-edge state stripe. Square corners throughout, bar 4px status chips and 6px buttons. |
| **Signature element** | The **jack pair**: `P` and `P+2` as a paired readout, IQ and CTRL, on one flat square surface split by a hairline. Its legends are neutral grey — Sentinel keeps the equivalent element (`.settings-location-label`) muted, and an accent fill repeated on every card would shout. |
| **Motion** | Near-zero, by intent — a monitoring surface that animates is one you stop trusting. Colour and background transitions only, ~150ms, matching Sentinel's controls. All of it disabled under `prefers-reduced-motion: reduce`. |
| **Density** | Desktop-class density, but **mobile-first**: below `md` the layout collapses to one column and the topology becomes a disclosure above the cards; below `sm` cards drop to a single column and their fields stack. Buttons are 44px on touch and Sentinel's 38px from `sm` up. An operator will stand next to the Pi with a phone while plugging dongles in — a primary use case, not a fallback. |
| **Empty state** | A dashed blank plate reading "NO DEVICES DETECTED", with one line of detail. No illustration, no mascot, no marketing tone. |
| **Voice** | Terse and technical. "STREAMING · 1234/1236 · 2.400 MS/s", not "Your device is working correctly!". Errors state the fix: "DVB kernel driver bound — blacklist `dvb_usb_rtl28xxu` on the host and reboot." |

**Accessibility is a gate, not a finish.** Every semantic tone is verified ≥ 4.5:1 against all
three grounds — the `#e8eaed` input fill binds, since field labels and badge text sit on it —
computed from relative luminance, not eyeballed. `signal.faint` is the single sub-threshold tone
(3.08:1) and is restricted to non-text use with its label rendered in `muted` alongside. The focus
ring is 2px ink `#23262f` at a 2px offset (13.96:1) and is never removed; it is ink rather than
the accent because a lime ring is not a focus indicator.

Sentinel's own settings CSS runs secondary text at 3.49:1 and muted labels at ~2.6:1. Those fail
AA, so Sentry's equivalents are darkened rather than copied — the one place the match is
deliberately inexact. ADR-0006 lists every such deviation.

---

## 10. Device status state machine

States: `detected → configured → starting → streaming → degraded → stopped → error`.
`needs_identification` and `present` are orthogonal **flags**, not states.

The registry owns every transition. Each carries a `state_reason` (a machine code) and
`state_since` (Unix ms).

| From | To | Trigger | `state_reason` |
|---|---|---|---|
| — | `detected` | Hotplug add (or startup sweep) matches an SDR USB ID and has no persisted row | — |
| `detected` | `configured` | `PATCH /api/devices/{id}` creates the row with a valid name + port | — |
| `detected` | *(removed)* | Hotplug remove, no persisted row | — |
| `detected` | `detected` (flag set) | Identity resolves to tier 3 | `needs_identification` flag ⇒ true |
| `configured` | `starting` | Device present **and** `enabled` **and** supervisor has spawned both processes | — |
| `configured` | `stopped` | `enabled` set false, or device absent | `disabled` / `device_absent` |
| `starting` | `streaming` | Both PIDs alive past the 3 s settle window **and** `control_follower` has received one `state` event on `P+2` | — |
| `starting` | `error` | Either process exits during the settle window, `rtl_tcp` cannot bind, or the librtlsdr index cannot be resolved | `spawn_failed` / `port_in_use` / `index_unresolved` / `ambiguous_index` / `driver_conflict` |
| `starting` | `stopped` | Device unplugged or disabled before settle | `device_absent` / `disabled` |
| `streaming` | `degraded` | Control-follower connection lost, **or** relay logged a reconnect, **or** a pair restart succeeded within the last 60 s | `control_lost` / `upstream_reconnecting` / `recent_restart` |
| `streaming` | `starting` | Supervisor restarts the pair after a process exit (including relay exit 75 = wedge), while under the restart budget | `restarting` |
| `streaming` | `stopped` | Device unplugged, or disabled by the operator | `device_absent` / `disabled` |
| `degraded` | `streaming` | Control follower reconnected and 60 s have passed with no restart | — |
| `degraded` | `starting` | Supervisor restarts the pair | `restarting` |
| `degraded` | `error` | Restart budget exhausted: 5 restarts within 120 s | `crash_loop` |
| `degraded` | `stopped` | Unplugged or disabled | `device_absent` / `disabled` |
| `stopped` | `starting` | Device replugged while `enabled`, or re-enabled while present | — |
| `stopped` | `configured` | Config edited while stopped | — |
| `error` | `starting` | Operator retry (`PATCH` with any field, or an explicit re-enable), **or** the exponential backoff timer expires (1 s → 2 → 4 → 8 → capped 60 s) | `retry` / `backoff_elapsed` |
| `error` | `stopped` | Disabled, or device unplugged | `disabled` / `device_absent` |
| `error` | `configured` | Device replugged after an `index_unresolved`/`driver_conflict` error | — |
| *(any)* | `stopped` | Application shutdown; every pair is `terminate()`d then `kill()`ed after a 5 s grace | `shutting_down` |

Invariants a test must prove:

- A device with no persisted row can never reach `starting` or beyond.
- `present: false` implies `state ∈ {stopped, configured, error}` — never `streaming`.
- `error` always carries a non-null `state_reason`.
- The restart budget is per device; one crash-looping dongle never affects another's state.
- Every transition emits exactly one `device_changed` (coalescing may merge two within 100 ms).

---

## 11. Build phases and parallelisation

### Phase 0 — Contract freeze *(one engineer, blocking, ~half a day)*

The parallelisation seam. Nothing else starts until this lands.

- Repo rename to Sentry; `docs/architecture/`, `docs/adr/`; `.env.example`; tooling (ruff,
  ESLint + Prettier, `tsc`/`vue-tsc` strict, pre-commit hooks, CI skeleton).
- Backend package skeleton with **every Protocol, dataclass and Pydantic schema written in full
  and every service a typed stub raising `NotImplementedError`.**
- Export `docs/api/openapi.json` from the stubbed app and generate `frontend/src/api/types.ts`
  from it. Both are committed and CI-checked for drift.
- A mock server (`tools/mock_sentry.py`) serving the frozen contract with scripted fixture data
  including SSE, so the frontend is never blocked on hardware or backend.

**After Phase 0 the schemas are frozen.** Any change is a deliberate, announced re-freeze.

### Phase 1 — three fully parallel tracks

| Track | Owner | Scope | Depends on |
|---|---|---|---|
| **1A Hardware edge** | backend-engineer | `interfaces/*`, `adapters/*` (sysfs, scripted, udev parse, reconcile, composite, process, ctypes, fakes), `services/usb_discovery`, `services/identity`, `services/hotplug`, `tests/fixtures/sysfs/*`, `tests/fakes/fake_rtl_tcp.py` | Phase 0 |
| **1B Persistence** | database-engineer | `models.py`, `db.py` + WAL hook, `alembic/` + `0001_initial_fleet`, `repositories/device_repository.py`, `config.py`, `services/port_allocator` | Phase 0 |
| **1C Frontend shell** | frontend-engineer | Vite + TS strict scaffold, Tailwind tokens for the design direction, all `base/` components, `stores/fleet.ts`, `useServerSentEvents`, `useLiveAnnouncer`, `useTreeNavigation`, `UsbTopologyTree`, `DeviceCard` and children — all against the Phase 0 mock server | Phase 0 |

No file is touched by two tracks. 1A owns `interfaces/`+`adapters/`+those three services; 1B owns
`models/db/alembic/repositories`+`port_allocator`; 1C owns `frontend/`.

### Phase 2 — parallel *(needs 1A + 1B)*

| Track | Owner | Scope |
|---|---|---|
| **2A Runtime** | backend-engineer | `services/device_registry` (state machine), `services/supervisor` (index resolution, spawn, restart budget, slot allocation), the §2.1 relay wedge-exit change, `services/control_follower`, `services/event_bus` |
| **2B HTTP** | backend-engineer (2nd) or 1B owner | `routers/health|status|events|devices`, `services/health`, `security.py`, `main.py` composition root, SPA static mount |
| **2C Frontend integration** | frontend-engineer | Swap mock → real API, `forms/*` with live validation off `constraints`, `SerialFlashDialog` (backend stubbed `501`), `health/*`, `consumer/SentinelEndpointCard` |

2A and 2B share only the schemas (frozen) and `device_registry`'s public interface (defined in
Phase 0), so they can interleave commits safely.

### Phase 3 — parallel

- **3A** `services/eeprom` + `POST /api/devices/{id}/serial` *(backend)*
- **3B** `GET /api/v1/sdrs` + the auth dependency *(backend)*
- **3C** Docker: multi-stage image (node build → debian runtime with librtlsdr + rtl_eeprom +
  tini), `docker-compose.yml` **without the Docker socket**, healthcheck on `/api/health`, named
  volume for `/data` *(any engineer)*
- **3D** README rewrite covering Docker and non-Docker commands for dev, build, tests and Alembic
  migrations, plus the migration guide from the legacy single-dongle stack *(onboarding-writer)*

### Phase 4 — sequential, at commit/push time

Per the project testing rule, tests are written **at commit/push time, on confirmation** — not
during Phases 1–3. Phase 4 is that pass: unit tests to 100 % of new code against §12, `vitest-axe`
accessibility tests, a keyboard + screen-reader pass, a Playwright e2e against the fake rtl_tcp
stack (no hardware), then code review, security review and the accessibility audit.

---

## 12. Test surface per module

What must be covered when the test pass runs. Enumeration only — no tests are written now.

**12.1 `adapters/sysfs_usb`** *(fixture trees under `tests/fixtures/sysfs/`)* — single dongle;
two dongles on one root port via a hub (`1-1.4.1`, `1-1.4.2`); three-level hub chain; roothub
nodes skipped; interface nodes (`1-1.4.2:1.0`) skipped; missing `serial` file → `None`; missing
`idVendor` → device skipped, not crashed; unreadable file (permission error) → skipped with a
log; non-numeric `busnum`; empty devices directory → `[]`; nonexistent root → `[]`; symlinked
driver resolution, and a device with no bound driver; a trailing-newline/UTF-8-with-BOM sysfs
value; `port_chain` parsed correctly for `1-1`, `1-1.4`, `1-1.4.2.3`.

**12.2 `adapters/udev_netlink.parse_uevent`** — real captured `add`/`remove` payloads; a
`change` action ignored; a `bind`/`unbind` action ignored; a non-USB subsystem ignored; a
truncated payload; a payload with no `DEVPATH`; a `DEVPATH` for an interface not a device; a
payload with embedded NULs and no trailing NUL; a garbage/binary payload → `None`, never raise.

**12.3 `adapters/reconcile_hotplug` + `composite_hotplug`** — device added between sweeps;
removed between sweeps; added and removed within one sweep interval (no event, by design —
document it); simultaneous add of two devices; unchanged snapshot → no events; the same event
from both sources within 1 s → emitted once; the same event from both sources 3 s apart →
emitted twice; primary source constructor raising → falls back and reports `source: "reconcile"`;
primary going silent mid-run.

**12.4 `services/identity`** *(pure, exhaustive)* — unique real serial → tier 1; the factory
default `00000001` → tier 2; empty/whitespace serial → tier 2; two devices with the *same*
unique-looking serial → **both** tier 3, neither tier 1; two devices with the same default serial
on different paths → both tier 2, distinct keys; identical topology path in a snapshot (should be
impossible — assert it degrades to tier 3, not a crash); serial containing a colon or a slash
(must not corrupt the `serial:<v>` key format — assert encoding); case sensitivity of serials;
empty snapshot set; single device; promotion `usb:` → `serial:` preserves the record; demotion
`serial:` → `usb:` is refused.

**12.5 `services/port_allocator`** — each of the six reject rules independently; a valid port;
`P+2` colliding with another device's `P`; `P` colliding with another device's `P+2`;
`1234`+`1235` both accepted (adjacent but disjoint); a *disabled* device's reservation still
blocking; an *absent* device's reservation still blocking; `P = 1023`; `P = 65534` (so `P+2`
overflows); `P` == HTTP port; `P+2` == HTTP port; the internal range at both boundaries
(`13999` allowed, `14000` rejected, `14007` rejected, `14008` allowed with `MAX_DEVICES=8`);
prober returning false; prober returning false for a port held by *this* device (accepted);
`suggest_next` on an empty fleet, a full-ish fleet, and a fleet with a gap; `suggest_next` when
no port is available.

**12.6 `services/device_registry`** — every row of the §10 transition table, one test each;
every invariant listed under it; a device configured while absent; a device unplugged while
`streaming`; replug of a serial-keyed device into a *different* USB port (config follows it);
replug of a topology-keyed device into a different port (treated as a *new* device — assert the
old row goes absent and is not silently re-bound); duplicate `device_changed` coalescing; a
`state_reason` present on every `error` transition; concurrent hotplug + PATCH on the same
device.

**12.7 `services/supervisor`** *(all against `FakeProcessSpawner` + `FakeRtlSdrLibrary`)* — spawns
the correct argv and env for a device (assert the relay env is exactly
`RELAY_UPSTREAM_HOST/PORT`, `RELAY_LISTEN_HOST/PORT`, `RELAY_CONTROL_PORT`, `RELAY_EXIT_ON_WEDGE`
and nothing else); internal port slot allocation and reuse after a device is removed; `rtl_tcp`
exits → pair restarted; relay exits 0 → pair restarted; relay exits **75** → pair restarted and a
`notice` raised; both exit simultaneously; restart budget exhausted → `error` + `crash_loop`, and
no further spawns; backoff schedule exact under `FakeClock` (1,2,4,8,16,32,60,60…); index
resolution with a unique serial; with no match; with two matches; `device_count()==0`;
enable→disable→enable cycles; device removed while `starting`; shutdown terminates every pair and
escalates to `kill` after the grace period; spawn raising `FileNotFoundError` (missing `rtl_tcp`
binary) → `error`, not a crash; **argv is always a list and no code path builds a shell string**.

**12.8 `services/control_follower`** *(against `tests/fakes/fake_rtl_tcp.py` + a real relay
subprocess)* — connects and parses `state`; never sends `claim` unsolicited; a deliberate
claim/set/release round-trip applies and is released even on exception; malformed NDJSON line
ignored without dropping the connection; the relay dropping the connection → reconnect with
backoff; `locked: true` from another owner → tuning request returns `tuning_deferred`; a partial
line split across two TCP reads.

**12.9 `tests/fakes/fake_rtl_tcp.py`** — the fake itself needs coverage as test infrastructure:
serves the 12-byte `RTL0` header; streams synthetic IQ at a configurable rate; records the 5-byte
commands it receives; modes `normal`, `wedge` (accepts, never streams — drives the exit-75 path),
`no_header`, `refuse_connection`, `drop_after_n_bytes`. This is what makes a **full relay path
end-to-end test possible with no hardware**: fake rtl_tcp → real unmodified relay subprocess →
test client asserting header replay, fan-out to two clients, and control-channel ownership.

**12.10 `services/eeprom`** — the charset allow-list accepts valid serials and rejects each of:
empty, 33 chars, a space, `;`, `$(…)`, a backtick, a newline, a NUL, unicode; `confirm: false`
rejected; a `streaming` device rejected with `device_busy`; a serial colliding with another
device rejected; the spawned argv is exactly the expected **list** (assert no `shell=True` on any
path); a timeout → `flash_failed`; a non-zero exit → `flash_failed` with truncated stderr; stderr
longer than 500 chars truncated; success → identity migrated and `pending_replug_until` set;
the per-device lock preventing a concurrent second flash; the pair stopped before and not
restarted during the flash.

**12.11 `services/event_bus`** — fan-out to N subscribers; slow subscriber's queue overflows and
drops oldest without stalling the others; overflow forces a `snapshot` on next flush; unsubscribe
on disconnect leaves nothing behind; coalescing two `device_changed` for one device within 100 ms
and *not* coalescing two for different devices; publish with zero subscribers.

**12.12 Routers** *(httpx `ASGITransport`, no network)* — for each endpoint: the happy path
shape; every documented error code; auth off → 200; auth on, no header → 401; auth on, wrong
token → 401; auth on, correct token → 200; `/api/health` reachable without a token in both modes;
SSE emits `snapshot` first then a `device_changed` on a registry change; SSE client disconnect
cleans up the subscriber; `PATCH` with an empty body → 400; `PATCH` with an unknown field →
rejected (`model_config = {"extra": "forbid"}`); `PATCH` name at 0, 1, 64, 65 chars; each
disallowed name character; each `sample_rate` boundary; `center_hz` at 23 999 999 / 24 000 000 /
1 766 000 000 / 1 766 000 001; `409` on the DB unique constraint (simulate the race);
`/api/v1/sdrs` field-by-field against the §7.8 mapping table; `/api/v1/sdrs` host derivation with
and without `SENTRY_ADVERTISED_HOST`; `include_disabled` and `available_only` combinations;
`X-Sentry-Sdr-Api-Version` header present.

**12.13 Repository / migrations** — `0001` upgrade then downgrade is clean; WAL PRAGMAs actually
applied on a real connection (`PRAGMA journal_mode` returns `wal`); both unique indexes enforced;
both CHECK constraints enforced; upsert-by-identity semantics; `updated_at` maintained; a
simulated crash (connection killed mid-transaction) leaves the DB readable and consistent.

**12.14 Frontend** — `stores/fleet` actions against plain fixture objects, including
`applySnapshot` replacing a stale device and `applyDeviceChanged` clearing a matching pending
patch and *not* clearing a non-matching one; `useServerSentEvents` open/named-event/parse-
error/stall-detector/close paths against a mocked `EventSource`; `useTreeNavigation` for every
key in the §9.4 table plus focus recovery when the focused node is removed; `usePortValidation`
mirroring each server rule; `OutputPortField` rendering a server `409` in the same slot as client
validation; `SerialFlashDialog` focus trap, Escape, and focus return; `vitest-axe` on every
component plus the assembled `FleetView` in the states empty / one streaming device / a
needs-identification device / an error device; a reduced-motion snapshot; the tree's ARIA
attributes (`aria-level`/`setsize`/`posinset`/`expanded`) asserted against a three-level fixture.

**12.15 Explicitly untestable thin edges** — these carry `# pragma: no cover` with a one-line
justification, are kept to a handful of statements each, and contain **no branching logic**:

| Edge | Why | Mitigation |
|---|---|---|
| `UdevNetlinkHotplugSource` socket `bind`/`recv` loop | Requires `AF_NETLINK`, Linux-only, root-adjacent | All parsing is the pure, fully-tested `parse_uevent`; the loop is 6 lines with no conditionals |
| `CtypesRtlSdrLibrary.__init__` `CDLL` load + symbol binding | Requires the real `librtlsdr.so` | Buffer→string decoding is a separately tested pure helper |
| `AsyncioProcessSpawner.spawn`'s `create_subprocess_exec` call | Actually forks | argv/env construction is in the supervisor and fully tested via `FakeProcessSpawner` |
| Real `rtl_eeprom` invocation | Writes to physical hardware | Argv construction, validation and result parsing are all tested; only the exec is not |
| `uvicorn.run` in `__main__` | Process bootstrap | — |
| The `/proc/net/tcp` file open in `ProcNetTcpSocketStats` | Linux-only path | The parser is root-parameterised and tested against a fixture file |

Everything else — every service, every router, every schema, the whole state machine, the whole
allocator, the whole frontend — is reachable in a test on macOS with no hardware. That is the
point of §4.1.

---

## 13. Open questions

These materially change scope or contract and need a decision rather than a guess.

1. **The relay is "reused unchanged" but must also exit on wedge.** §2.1 proposes the minimal
   additive diff (two new env vars, one new branch in `note_unhealthy`, Docker path retained and
   still tested). *Confirm this is the only relay change permitted.*

2. **Per-port client counts.** The relay does not report how many consumers are connected. §7.2
   proposes deriving it from `/proc/net/tcp` (Linux-only, `null` elsewhere, testable via a fixture
   file). The alternative is a second relay change to publish counts on the control channel.
   *Choose: /proc parsing, relay change, or drop `clients` from v1.*

3. **SSE auth when the bearer token is enabled.** `EventSource` cannot send headers. §7.9
   proposes an `?access_token=` query parameter with query strings stripped from access logs. The
   alternative is a short-lived same-origin `HttpOnly` cookie minted by a new
   `POST /api/session`, which is cleaner but adds an endpoint, CSRF considerations and SPA login
   state. *Choose.*

4. **Which Sentinel store is authoritative for radios?** `backend/models.py::SdrRadio` exists but
   is **unused** — `backend/routers/sdr.py` persists radios as JSON under `UserSettings`
   `sdr.radios`. §7.8's mapping is designed to satisfy both (the field names are identical), but
   the Sentinel-side import work differs: a JSON key addition versus an Alembic migration on
   `sdr_radios`. *Confirm which Sentry should target — and whether the Sentinel-side "Import from
   Sentry" button is in this project's scope or a follow-up in the Sentinel repo.*

5. **Bias-T and direct sampling.** Some SDR use cases (active antennas, HF) need `rtl_biast` and
   `-D` direct sampling. Neither is in the current design. *In scope now, or a later additive
   PATCH field?* Adding them later is cheap (two nullable columns); adding them now costs a day.

6. **Device cap.** `SENTRY_MAX_DEVICES` defaults to 8. A Pi's USB bandwidth realistically supports
   ~4 dongles at 2.4 MS/s before drops. *Should Sentry warn above a configured threshold, or hard-
   cap it?* Recommend: warn (a `notice` when total configured sample rate exceeds a budget), never
   hard-cap — the operator may run several at 250 kS/s.

7. **Restart-budget escalation.** Five restarts in 120 s → `error` with exponential backoff. On a
   marginal USB power supply this could leave a dongle stuck in `error` overnight. *Should Sentry
   keep retrying at the 60 s cap forever (current design), or stop entirely and require an
   operator action?* Current design keeps retrying, which is the right default for an unattended
   Pi, but it is worth an explicit yes.

8. **Removing the last of the old stack.** The current `docker-compose.yml` and `Dockerfile` are
   replaced wholesale. *Resolved:* the old single-dongle compose was retained briefly as a rollback
   path, then removed — Sentry is a standalone project and no longer ships the stack it replaced.

---

## 14. ADR index

| ADR | Decision |
|---|---|
| [ADR-0001](../adr/0001-one-container-subprocess-supervision.md) | One container with subprocess supervision, not a container per dongle |
| [ADR-0002](../adr/0002-drop-docker-socket-wedge-recovery.md) | Drop the Docker socket; recover a wedged dongle by process exit |
| [ADR-0003](../adr/0003-device-identity-strategy.md) | Three-tier device identity; librtlsdr index resolved at spawn, never cached |
| [ADR-0004](../adr/0004-sse-over-websocket.md) | Server-Sent Events, not WebSocket, for realtime status |
| [ADR-0005](../adr/0005-sqlite-wal-persistence.md) | SQLite with WAL for configuration persistence |
