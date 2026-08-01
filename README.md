# Sentry — multi-dongle RTL-SDR fleet manager

Runs a **fleet** of RTL-SDR dongles on a Raspberry Pi (or any Linux host) and
serves each one to the network as if it were a plain `rtl_tcp`. Give every
dongle a name and an output port in a web UI, and every consumer — SDR#, GQRX,
SDR++, or [Sentinel](https://github.com/barrygee/Sentinel) — connects to it
exactly as it would to a single dongle.

Each dongle tunes independently, several clients can share each one, and a
client that dies abruptly never locks anybody out.

```
                        ┌───────────────── sentry (one container) ─────────────┐
USB bus ──hotplug──►    │  discovery → identity → registry → supervisor        │
                        │                              │                       │
                        │                              ├─ rtl_tcp  ─┐          │
                        │                              ├─ relay  ◄──┘  :1234 IQ│──► clients
                        │                              │               :1236 ⌘ │
                        │                              ├─ rtl_tcp  ─┐          │
                        │                              └─ relay  ◄──┘  :1238 IQ│──► clients
                        │                                              :1240 ⌘ │
                        │  SQLite ◄── FastAPI ──► REST + SSE + Vue SPA   :8000 │
                        └──────────────────────────────────────────────────────┘
```

---

## Quick start

Plug the dongles in first, then:

```bash
git clone https://github.com/barrygee/rtl-sdr-controller.git sentry
cd sentry
docker compose up -d --build
```

Open **`http://<PI_IP>:8000`**, give each dongle a name and an output port, and
enable it.

> **First time on this Pi?** The DVB kernel driver will claim the dongles before
> Sentry can. Do the [host setup](#host-setup-on-the-pi-before-docker) once —
> blacklist the modules, raise the USB memory limit, reboot — then come back
> here. Skipping it looks like "no devices detected".

### Without compose

The options below are not optional — each one is load-bearing, and the container
will not work if you drop them:

```bash
docker build -t sentry .

docker run -d --name sentry --restart unless-stopped \
  --privileged \
  --device /dev/bus/usb:/dev/bus/usb \
  --device-cgroup-rule 'c 189:* rmw' \
  --network host \
  -v sentry-data:/data \
  sentry
```

| Option | Why it is required |
| ------ | ------------------ |
| `--privileged` | USB device access for dongles that re-enumerate at runtime. |
| `--device /dev/bus/usb:/dev/bus/usb` | Passes the whole USB bus. A bind-mount would snapshot the tree and go stale the moment a dongle re-enumerates. |
| `--device-cgroup-rule 'c 189:* rmw'` | Grants the whole USB char-major, not one node, so a re-enumerated dongle stays usable. |
| `--network host` | Each dongle's ports are assigned by you at runtime, so they cannot be published statically with `-p`. |
| `-v sentry-data:/data` | Device names and port assignments live here. Without it, all configuration is lost on container recreation. |

To require a token on the API, add `-e SENTRY_AUTH_TOKEN=<long-random-value>`
(see [Security](#security)).

---

## Why this exists

`rtl_tcp` serves exactly **one** TCP client and sets no keepalive on it, so a
client whose host sleeps, crashes, or drops off the network leaves it holding a
dead connection — locking everyone else out until it is restarted. Sentry puts a
**fan-out relay** in front of every dongle: the relay is the dongle's single
permanent client and re-serves the IQ stream to any number of consumers, reaping
dead ones via TCP keepalive.

On top of that, Sentry manages the fleet: it detects dongles as they are plugged
and unplugged, remembers what you called each one, assigns each a stable output
port, supervises the process pair behind it, and recovers a dongle that wedges
after a USB re-enumeration.

---

## Ports

Each dongle gets a pair, and the pair is the contract consumers rely on:

| Port    | Purpose                                                                 |
| ------- | ----------------------------------------------------------------------- |
| `P`     | IQ stream — a byte-identical `rtl_tcp` endpoint. Any client can use it.  |
| `P + 2` | NDJSON tuning-ownership control channel (`claim`/`release`/`set`/`get`). |

`P` is whatever you assign in the UI. Sentry reserves **both** `P` and `P+2`, so
two dongles on `1234` and `1236` collide — the UI rejects that for you.

There is one physical tuner per dongle, so simultaneous clients cannot each tune
freely. The control channel arbitrates a single **owner**: the owner drives
tuning, everyone else is a read-only follower that sees the real live tuning
rather than a stale guess. With no owner held, raw 5-byte `rtl_tcp` commands are
forwarded last-writer-wins, so SDR#/GQRX/SDR++ still tune normally.

Port **`8000`** serves the web UI and the API. The internal `rtl_tcp` processes
bind loopback-only from `127.0.0.1:14000` upward and are never exposed.

---

## The duplicate-serial problem — read this before you buy a second dongle

This is the single most important operational concept in Sentry.

Most RTL-SDR dongles ship with the **same factory serial number** (`00000001`),
and `rtl_tcp -d <index>` addresses devices by librtlsdr enumeration order, which
reshuffles whenever a dongle is added, removed, or re-enumerates. So "which
physical dongle is this?" is genuinely ambiguous out of the box.

Sentry resolves identity in three tiers:

| Tier | Basis                         | Survives                               |
| ---- | ----------------------------- | -------------------------------------- |
| 1    | A unique USB serial           | Reboot, replug, moving to any port     |
| 2    | USB topology path (`1-1.4.2`) | Reboot and replug **in the same port** |
| 3    | Unresolved                    | Surfaced in the UI, never guessed      |

Two dongles both reading the factory `00000001` resolve fine at tier 2 on their
distinct topology paths. Two dongles sharing a *non-default* serial are forced
to tier 3: guessing there risks migrating your configuration onto the wrong
physical dongle.

**The fix is to give each dongle a unique serial.** Sentry offers this in the UI
for any device flagged "needs identification" — it stops the device, writes the
new serial via `rtl_eeprom`, and asks you to replug. After that, identity is
permanent and you can move the dongle to any port.

> This writes permanently to the dongle's EEPROM, and an interrupted write can
> corrupt its USB descriptor. The UI requires explicit acknowledgement. You can
> also do it by hand:
> `docker compose exec sentry rtl_eeprom -d 0 -s ADSB-01`

---

## Hardware notes

These are not optional advice; ignoring them produces confusing failures.

- **Use a *powered* USB hub** for more than two dongles. RTL-SDR dongles draw
  meaningfully under load and a bus-powered hub will brown out, which presents
  as random disconnects and `Failed to submit transfer` errors, not as a power
  message.
- **Bandwidth is the real ceiling.** A Raspberry Pi shares one USB 2.0
  controller across all ports (~35 MB/s practical). Each dongle at 2.048 Msps is
  ~4 MB/s, so roughly **6–8 dongles** maximum — fewer at higher sample rates.
  `SENTRY_MAX_DEVICES` defaults to `8`.
- Dongles behind a USB extender or hub are fully supported — the UI shows the
  hub tree so you can see which physical port each one is on.

---

## Host setup (on the Pi, before Docker)

### 1. Blacklist the DVB kernel driver

The dongle is otherwise claimed by the Linux DVB modules before `rtl_tcp` can
reach it.

```bash
echo -e "blacklist dvb_usb_rtl28xxu\nblacklist rtl2832\nblacklist rtl2830" \
  | sudo tee /etc/modprobe.d/rtl-sdr-blacklist.conf

sudo rmmod dvb_usb_rtl28xxu 2>/dev/null
sudo rmmod rtl2832 2>/dev/null
sudo rmmod rtl2830 2>/dev/null

sudo update-initramfs -u
```

### 2. Raise the USB memory limit

Prevents buffer errors at high sample rates — and matters more with several
dongles, not less.

```bash
echo 0 | sudo tee /sys/module/usbcore/parameters/usbfs_memory_mb
```

To persist it, add this to `/etc/rc.local` before `exit 0`:

```bash
echo 'echo 0 | tee /sys/module/usbcore/parameters/usbfs_memory_mb' | sudo tee -a /etc/rc.local
```

### 3. Reboot

```bash
sudo reboot
```

### 4. Install Docker (if needed)

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
newgrp docker
sudo systemctl enable docker
```

---

## Running with Docker

```bash
docker compose up -d --build     # build and start
docker compose logs -f           # follow
docker compose down              # stop (configuration survives — named volume)
docker compose restart           # restart
```

Then open **`http://<PI_IP>:8000`**.

Configuration lives in the `sentry-data` named volume, so device names and port
assignments survive `down`, rebuilds, and reboots. To wipe it deliberately:
`docker compose down -v`.

### Rolling back

The previous single-dongle stack is retained for one release:

```bash
docker compose -f docker-compose.legacy.yml up -d --build
```

---

## Running without Docker

Requires Python 3.12+, Node 22+, and `rtl_tcp`/`rtl_eeprom` on `PATH`
(from [librtlsdr](https://github.com/steve-m/librtlsdr)).

```bash
# Backend dependencies
uv sync

# Database — creates the schema (SQLite, WAL mode)
uv run alembic upgrade head

# Backend, with live reload
uv run uvicorn app.backend.main:app --reload --port 8000

# Frontend dev server (separate terminal) — proxies /api to the backend
cd app/frontend && npm install && npm run dev
```

The SPA is then on `http://localhost:3000` and the API on `:8000`. If port 8000
is already taken, point the dev proxy elsewhere:

```bash
SENTRY_API_PROXY_TARGET=http://127.0.0.1:8010 npm run dev
```

Production build (FastAPI then serves the SPA from the same port):

```bash
cd app/frontend && npm run build     # -> app/frontend/dist
uv run uvicorn app.backend.main:app --host 0.0.0.0 --port 8000
```

### Database migrations

```bash
uv run alembic upgrade head                      # apply
uv run alembic downgrade base                    # revert
uv run alembic revision --autogenerate -m "..."  # new migration
```

### Tests

```bash
uv run pytest                    # backend + relay
cd app/frontend && npm test      # frontend (Vitest)
```

---

## Connecting clients

### Any RTL-TCP client (SDR#, GQRX, SDR++)

Point it at the Pi's IP and the dongle's assigned port `P`:

```
Host: <PI_IP>
Port: 1234
```

Multiple clients can share one dongle. They tune last-writer-wins unless a
consumer holds the ownership token on the control channel.

### Sentinel

Sentinel discovers the whole fleet from one endpoint:

```
GET http://<PI_IP>:8000/api/v1/sdrs
```

which returns one record per dongle, shaped to drop straight into Sentinel's
radio configuration:

| Field              | Meaning                                                |
| ------------------ | ------------------------------------------------------ |
| `name`             | The name you set in the UI                             |
| `host`, `port`     | Where to connect for IQ (`port` is `P`)                |
| `description`      | Free-text notes                                        |
| `enabled`          | Whether Sentry is serving it                           |
| `bandwidth`        | Sample rate, Hz                                        |
| `rf_gain`          | Gain in dB, or `null` when the tuner is in AGC         |
| `agc`              | Whether AGC is on                                      |
| `sentry_device_id` | Stable identity key — use it to re-import idempotently |

The control channel is at `port + 2`, exactly as for a single dongle, so
Sentinel's existing connection path needs no changes.

---

## API

| Endpoint                        | Purpose                                                                            |
| ------------------------------- | ---------------------------------------------------------------------------------- |
| `GET /api/health`               | Liveness. 200 while dongles are degraded; 503 only if the database is unreachable. |
| `GET /api/status`               | Full JSON snapshot of every device                                                 |
| `GET /api/events`               | SSE stream — `snapshot`, `device_changed`, `device_removed`, `health`, `notice`    |
| `GET /api/devices`              | Device configuration, including unconfigured ones                                  |
| `PATCH /api/devices/{id}`       | Set name, output port, enabled, tuning defaults                                    |
| `DELETE /api/devices/{id}`      | Forget an absent device's configuration                                            |
| `POST /api/devices/{id}/serial` | Write a unique serial via `rtl_eeprom`                                             |
| `GET /api/v1/sdrs`              | The fleet, for Sentinel                                                            |

`/api/health` deliberately stays healthy while an individual dongle is degraded —
otherwise a single wedged dongle would restart the container and take the healthy
ones down with it.

---

## Configuration

Every variable is prefixed `SENTRY_`. See `.env.example` for the full list with
defaults; copy it to `.env` (which is git-ignored) to override.

| Variable                      | Default                               | Purpose                                                |
| ----------------------------- | ------------------------------------- | ------------------------------------------------------ |
| `SENTRY_HTTP_HOST`            | `0.0.0.0`                             | API/SPA bind address                                   |
| `SENTRY_HTTP_PORT`            | `8000`                                | API/SPA port                                           |
| `SENTRY_ADVERTISED_HOST`      | *(from Host header)*                  | Host published in `/api/v1/sdrs`; set behind NAT       |
| `SENTRY_DATABASE_URL`         | `sqlite+aiosqlite:////data/sentry.db` | Database URL                                           |
| `SENTRY_AUTH_TOKEN`           | *(unset — auth off)*                  | Bearer token required on every route but `/api/health` |
| `SENTRY_MAX_DEVICES`          | `8`                                   | Device cap                                             |
| `SENTRY_INTERNAL_PORT_BASE`   | `14000`                               | Base of the loopback-only `rtl_tcp` range              |
| `SENTRY_RESERVED_PORTS`       | *(empty)*                             | Extra ports Sentry must never assign                   |
| `SENTRY_RECONCILE_INTERVAL_S` | `2.0`                                 | Sysfs sweep period (hotplug safety net)                |
| `SENTRY_LOG_LEVEL`            | `INFO`                                | Logging level                                          |
| `SENTRY_CORS_ORIGINS`         | *(empty — CORS closed)*               | Allow-list for a separately-hosted dev frontend        |

### Security

**Authentication is off by default**, which suits a trusted home LAN. Sentry can
spawn processes, bind ports, and write dongle firmware — if the Pi is reachable
from anywhere less trusted, set `SENTRY_AUTH_TOKEN` to a long random value. Every
route except `/api/health` then requires `Authorization: Bearer <token>`; the SSE
stream also accepts `?access_token=` because `EventSource` cannot set headers.

The container runs `privileged: true` with the whole USB bus passed through,
which is required for dongles that re-enumerate. It does **not** mount the Docker
socket — earlier versions did, which was root-equivalent host control; the
supervisor is now the parent of its own child processes and restarts them
directly (see `docs/adr/0002`).

---

## Architecture

Design documents live in `docs/`:

- `docs/architecture/sentry-fleet-manager.md` — the full design
- `docs/adr/0001` — one container with subprocess supervision, not a container per dongle
- `docs/adr/0002` — dropping the Docker socket
- `docs/adr/0003` — device identity strategy
- `docs/adr/0004` — SSE over WebSocket
- `docs/adr/0005` — SQLite with WAL

---

## Troubleshooting

**No devices detected.** Check the DVB blacklist took effect
(`lsmod | grep dvb`) and that the dongle is plugged in. `docker compose logs -f`
reports discovery.

**A dongle keeps restarting.** Usually power — try a powered hub. The UI shows
`error` with the last exit reason.

**A dongle streams then goes silent.** This is the classic USB re-enumeration
wedge: `rtl_tcp` stays alive but stops delivering. Sentry detects it (a streaming
dongle never goes quiet for 10s) and restarts the pair automatically.

**Devices swap names after a reboot.** Their serials are not unique — see
[the duplicate-serial problem](#the-duplicate-serial-problem--read-this-before-you-buy-a-second-dongle).

**Port rejected in the UI.** Remember each device reserves `P` *and* `P+2`, so
`1234` and `1236` conflict.
