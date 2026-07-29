# ADR-0005 — SQLite with WAL for configuration persistence

- **Status:** Accepted
- **Date:** 2026-07-29
- **Deciders:** project owner, architect
- **Context spec:** [`docs/architecture/sentry-fleet-manager.md`](../architecture/sentry-fleet-manager.md) §6

## Context

Requirement 7: dongle names and settings must persist across reboots. The data is one table, of
the order of ten rows, written only when an operator edits a device, and read on startup plus on
every status assembly. There is exactly one writer process, on one host, forever.

The critical environmental fact: **this is a Raspberry Pi that loses power without warning.** No
UPS, no clean shutdown, no operator present. The store must survive being switched off mid-write,
and it must come back up by itself with the configuration intact.

## Decision

**SQLite**, accessed through SQLAlchemy 2.0 async (`aiosqlite`) with Alembic migrations, using:

```sql
PRAGMA journal_mode  = WAL;      -- crash-safe; readers never block the writer
PRAGMA synchronous   = NORMAL;   -- WAL + NORMAL survives a power cut
PRAGMA busy_timeout  = 5000;     -- wait rather than fail under concurrent reads
PRAGMA foreign_keys  = ON;
```

The database file lives on a Docker named volume at `/data/sentry.db`. Migrations run
automatically in the FastAPI `lifespan` (`alembic upgrade head`); a migration failure aborts
startup loudly rather than serving a half-schema — there is no operator at a shell to notice
otherwise.

## Consequences

**Positive**

- **WAL is the specific answer to the power-cut requirement.** With rollback journalling, a power
  loss during a write can leave a `-journal` file whose recovery depends on the journal reaching
  the disk first. WAL appends to a separate log and commits by writing a frame header, so an
  interrupted write is simply not replayed — the database opens at the last committed state.
- **`synchronous=NORMAL` is safe under WAL specifically.** WAL frames are checksummed, so a torn
  final frame is detected and discarded; the worst case is losing the last transaction on an OS
  crash, not corruption. Under rollback journalling, `NORMAL` would not be safe — this is why the
  two pragmas are set together and must not be separated.
- **Readers never block the writer, and vice versa.** The SSE loop and `/api/status` read
  continuously while an operator PATCHes a device; under the default rollback journal those would
  contend, and on an SD card that contention is measured in tens of milliseconds.
- **Zero operational surface.** No server process, no port, no credentials, no backup daemon. On
  an appliance that must boot unattended, every service that could fail to start is a liability.
  Backup is `cp sentry.db*`, and restore is copying it back.
- **SD-card friendly.** WAL batches writes into an appended log and checkpoints periodically,
  producing markedly less write amplification than a rollback journal's write-journal-then-
  write-page-then-delete-journal cycle. SD cards die from writes.
- Real SQL constraints do real work: `UNIQUE(identity_kind, identity_key)` and
  `UNIQUE(output_port)` are the last line of defence behind the port allocator, catching a race
  that application-level validation cannot.
- SQLAlchemy + Alembic keeps the door open — moving to PostgreSQL later would be a config change
  and a migration re-generation, not a rewrite.
- Tests run against an on-disk temp SQLite file identical to production, including the pragmas, so
  the tested behaviour is the deployed behaviour.

**Negative**

- **Single writer.** Concurrent writes serialise. Irrelevant at ten rows and human-paced edits, and
  `busy_timeout=5000` turns a theoretical `SQLITE_BUSY` into a brief wait. This *would* matter if
  Sentry ever became multi-host — it is explicitly a single-appliance design.
- **`render_as_batch=True` is required in Alembic** because SQLite cannot drop or alter a column
  in place; future migrations rebuild the table. Noted in `env.py`; harmless at this size.
- **The volume must actually be a volume.** A `sentry.db` inside the container's writable layer
  would vanish on `docker compose up --build`, silently losing every device name. Called out in
  the compose file, the README and the smoke test.
- **WAL leaves `-wal` and `-shm` sidecar files.** Backup must copy all three, or use
  `VACUUM INTO`. Documented in the README's backup section.
- No network access to the data. Accepted — the API is the interface.

**Rejected alternatives**

- **A JSON file on disk.** Tempting for ten rows, and it is what Sentinel currently does for its
  radio list. Rejected precisely because of the power-cut requirement: a naive rewrite truncates
  the file and can leave it empty or half-written after a power loss, and doing it *safely*
  (write-temp, fsync, atomic rename, fsync the directory) is reimplementing a fraction of what
  SQLite already does correctly. It also gives up uniqueness constraints, which are load-bearing
  for port allocation.
- **PostgreSQL / MariaDB.** A second container, a second thing that must come up before the API,
  credentials to manage, and meaningful RAM on a Pi — all to store ten rows. Rejected as wildly
  disproportionate.
- **Redis or another in-memory store with periodic snapshots.** Snapshot-based persistence is
  exactly the durability model the power-cut requirement rules out.
- **SQLite with the default rollback journal.** The default, and the trap. Loses the reader/writer
  concurrency the SSE path benefits from, and pairs badly with `synchronous=NORMAL`. WAL is the
  whole point of this ADR.
