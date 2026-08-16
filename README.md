# Sentry — multi-dongle RTL-SDR controller

[![CI](https://github.com/barrygee/Sentry/actions/workflows/ci.yml/badge.svg)](https://github.com/barrygee/Sentry/actions/workflows/ci.yml)

Runs a **set** of RTL-SDR dongles on a Raspberry Pi (or any Linux host) and
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
                        │  SQLite ◄── FastAPI ──► REST + SSE + static UI :8000 │
                        └──────────────────────────────────────────────────────┘
```

---

## Quick start

Plug the dongles in first, then:

```bash
git clone https://github.com/barrygee/Sentry.git
cd Sentry
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
  -v /dev/bus/usb:/dev/bus/usb \
  --device-cgroup-rule 'c 189:* rmw' \
  --network host \
  -v sentry-data:/data \
  sentry
```

| Option | Why it is required |
| ------ | ------------------ |
| `--privileged` | USB device access for dongles that re-enumerate at runtime. |
| `-v /dev/bus/usb:/dev/bus/usb` | Passes the whole USB bus as a bind mount, so nodes created when a dongle re-enumerates appear inside the container. Must not be `--device`: pointed at a directory, that expands to a fixed list of nodes at container start and goes stale on the next replug. |
| `--device-cgroup-rule 'c 189:* rmw'` | Grants the whole USB char-major, not one node, so a re-enumerated dongle stays usable. |
| `--network host` | Each dongle's ports are assigned by you at runtime, so they cannot be published statically with `-p`. |
| `-v sentry-data:/data` | Device names and port assignments live here. Without it, all configuration is lost on container recreation. |

To protect the controller, set a password in its UI once it is running (see
[Security](#security)) — there is nothing to configure here.

---

## Why this exists

`rtl_tcp` serves exactly **one** TCP client and sets no keepalive on it, so a
client whose host sleeps, crashes, or drops off the network leaves it holding a
dead connection — locking everyone else out until it is restarted. Sentry puts a
**fan-out relay** in front of every dongle: the relay is the dongle's single
permanent client and re-serves the IQ stream to any number of consumers, reaping
dead ones via TCP keepalive.

On top of that, Sentry manages the SDRs: it detects dongles as they are plugged
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

The UI is then on `http://localhost:3000` and the API on `:8000`. The dev server
rebuilds on change by re-running the same `npm run build` the image uses, so
there is no second code path that only exists in development. If port 8000 is
already taken, point the dev proxy elsewhere:

```bash
SENTRY_API_PROXY_TARGET=http://127.0.0.1:8010 npm run dev
```

Production build (FastAPI then serves the UI from the same port). There is no
bundler: `tsc` emits browser-native ES modules, the Tailwind CLI compiles one
stylesheet, and `index.html` plus the vendored fonts are copied across:

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

### Tests and checks

```bash
uv run pytest                            # backend + relay
cd app/frontend && npm test              # frontend (Vitest + jsdom)
cd app/frontend && npm run test:coverage # the same, with the coverage gate
cd app/frontend && npm run typecheck     # frontend types — app and test suite
cd app/frontend && npm run lint          # frontend lint + format check
```

Frontend coverage thresholds are **per file** (`app/frontend/vitest.config.ts`):
100% on files that have a suite, and a file joins the gate as tests for it land.
A repo-wide threshold on a codebase whose test pass is still in progress fails on
day one and gets switched off on day two.

### CI

`.github/workflows/ci.yml` runs on every pull request and every push to `main`,
in three parallel jobs so a red check names its own half:

| Job | What it runs |
| --- | --- |
| **backend** | `ruff check`, `ruff format --check`, `mypy`, `pytest` |
| **frontend** | `npm ci`, `npm run lint`, `npm run typecheck`, `npm run test:coverage`, `npm run build` |
| **docker** | `docker build` of the production image — never pushed |

Nothing there is new: these are the same commands listed above. The Docker job
earns its place by catching the one failure neither other job can — a Dockerfile
that no longer assembles even though both halves of the source are green.

Python and Node versions are pinned in the workflow to match the Dockerfile's
stages, so CI cannot pass on a version the image does not ship.

### Changelog

`CHANGELOG.md` is **generated, not written** — by `git-cliff` from the
repository's Conventional Commits, configured in `cliff.toml`. Two things follow:

- **Never hand-edit it.** The next regeneration overwrites the file. To fix a
  changelog line, fix the commit message it came from.
- **A vague commit becomes a vague changelog line.** The commit subjects are the
  input, which is the practical reason commit hygiene matters here.

Merge commits are filtered out — every PR lands as one, and `main` keeps the
original commits, so the individual changes are already listed.

#### Regenerating it

Part of cutting a release, run locally and landed through a normal pull request:

```bash
git-cliff --config cliff.toml --output CHANGELOG.md
```

Run it **after** the version tag exists, so the tagged commits fold into a dated
section and anything newer stays under `Unreleased`. Don't pass `--tag` to force
a version — it labels commits made *after* the tag with that version too, which
produces two sections with the same number.

#### Why this is not automated

It was, briefly: a workflow regenerated the file on every push to `main` and
committed it back. Branch protection ended that. `main` requires the three CI
checks, the bot's commit carries `[skip ci]` so it can never have any, and the
push is rejected:

```
remote: error: GH013: Repository rule violations found for refs/heads/main.
remote: - 3 of 3 required status checks are expected.
```

The usual fix — exempting the Actions app in the ruleset — **is not available on
a user-owned repository**; GitHub restricts that bypass to organisations. The
remaining options were a bot-opened pull request per merge, or a deploy key with
write access that bypasses protection. Neither is worth it for a file that only
needs to be right when a release goes out, so it is a release step instead.

To run the whole set locally before pushing:

```bash
uv run ruff check app/backend tests tools && \
uv run ruff format --check app/backend tests tools && \
uv run mypy app/backend && \
uv run pytest -q && \
(cd app/frontend && npm run lint && npm run typecheck && npm run test:coverage && npm run build)
```

> Use `ruff format` on those directories rather than `.` — at repo root it also
> reformats Python fenced in `docs/`, which mangles the architecture spec's
> deliberately aligned comments.

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

Sentinel discovers the SDRs from one endpoint:

```
GET http://<PI_IP>:8000/api/v1/sdrs
```

which returns one record per **public** dongle, shaped to drop straight into
Sentinel's radio configuration:

| Field              | Meaning                                                |
| ------------------ | ------------------------------------------------------ |
| `name`             | The name you set in the UI                             |
| `host`, `port`     | Where to connect for IQ (`port` is `P`)                |
| `description`      | The device's free-text description                     |
| `notes`            | The operator's notes for the device                    |
| `antenna`          | The antenna feeding it                                 |
| `enabled`          | Whether Sentry is serving it                           |
| `bandwidth`        | Sample rate, Hz                                        |
| `rf_gain`          | Gain in dB, or `null` when the tuner is in AGC         |
| `agc`              | Whether AGC is on                                      |
| `sentry_device_id` | Stable identity key — use it to re-import idempotently |

The control channel is at `port + 2`, exactly as for a single dongle, so
Sentinel's existing connection path needs no changes.

#### Choosing which dongles to publish

Each device card has a **Private** switch. It decides one thing: whether that
dongle appears in `GET /api/v1/sdrs`.

- **Switched on (private)** — omitted from the export entirely. No query
  parameter brings it back.
- **Switched off** — listed in the export, so any Sentinel that queries this
  Sentry can see it and connect to it.

So a Sentry running four dongles can offer any two of them to other Sentinel
instances and keep the rest to itself. Newly configured devices start private,
and devices that existed before this feature stay private until you switch them
off — publishing hands out a reachable IQ endpoint, so it is always a
deliberate choice.

Every field on a published device goes into the export, including its notes and
antenna.

---

## WiFi hotspot

Sentry can run **its own WiFi network**, so a Sentinel client joins that and
reaches the SDRs with no LAN in between — in a vehicle, in a field, anywhere you
carry the Pi to. The network is **hidden by default**: it does not appear in a
device's WiFi list, so a client has to be told the name and password in advance.

This is purely additive. Everything above keeps working exactly as it does now,
and a Sentry that never enables the hotspot behaves identically to one without
this feature.

Everything is done from the **hotspot control in the top-right of the header**.
See [turning it on](#turning-the-hotspot-on) and
[turning it off](#turning-the-hotspot-off) below.

### Before you start

On the Pi:

```bash
nmcli -v                                        # NetworkManager must be present
dpkg -s dnsmasq-base | grep Status              # supplies the hotspot's DHCP/DNS
iw list | grep -A8 "Supported interface modes"  # must list "AP"
iw reg get                                      # your regulatory domain
```

Raspberry Pi OS Bookworm ships NetworkManager by default. A host using `dhcpcd`
or `systemd-networkd` instead will report the hotspot as unavailable rather than
failing.

Then, in `.env`:

```bash
SENTRY_HOTSPOT_CONTROL_ENABLED=true
```

Both are required. Control is off by default because it is the one setting that
hands a LAN-facing API control of the host's networking, and Sentry refuses every
hotspot change while the auth token is unset — an access point puts anyone in
radio range who has the passphrase on the same network as an API that spawns
processes and writes dongle firmware.

### Do the first run over Ethernet

A Pi with a single radio cannot be both a WiFi client and an access point. Making
`wlan0` a hotspot therefore **drops the Pi's own WiFi connection** — including,
quite possibly, the one your browser is using.

Sentry will not do that quietly:

- Automatic interface selection never picks a radio that is already carrying a
  connection.
- Choosing one anyway requires ticking an acknowledgement that names the network
  it will disconnect.
- Starting a hotspot is **provisional**. It rolls itself back and restores the
  previous connection after `SENTRY_HOTSPOT_CONFIRM_TIMEOUT_S` (120s by default)
  unless you press **Keep this hotspot** — and only then does it start on boot.
  So a hotspot nobody can reach cannot survive a reboot.

If you do lock yourself out, plug in Ethernet, or attach a keyboard and monitor
and run:

```bash
sudo nmcli connection down sentry-hotspot
```

### Turning the hotspot on

1. Open the **hotspot control in the top-right of the header**.
2. **Network name (SSID)** — what clients will look for. Up to 32 bytes; accented
   and emoji characters cost more than one byte each, and the panel counts them
   for you. Because the network is hidden, clients type this by hand, so avoid
   anything ambiguous.
3. **Password** — 8 to 63 characters. This is the only thing protecting the
   network, so make it long. Sentry will never show it back to you afterwards.
4. **Hide this network** — on by default. Leave it on unless you want the network
   to appear in normal WiFi scans.
5. **Wireless interface** — leave on *Choose automatically*. It picks a radio that
   is not already carrying a connection. Pick one explicitly only if you know you
   want it; if that radio is in use you will have to tick an acknowledgement
   naming the network it is about to disconnect.
6. **Band and channel** — 2.4 GHz and *Automatic* are right unless you are working
   around a specific congested channel.
7. Switch **Run the hotspot** on and press **Save hotspot settings**.

The hotspot comes up straight away, but as **ON TRIAL**: a countdown appears and
Sentry will undo the change and restore the previous connection when it expires.

8. Press **Keep this hotspot** before the countdown runs out.

Only then does *Starts on boot* flip to **Yes**. That is the point of the
countdown — a hotspot that has locked everyone out cannot survive a reboot,
because nobody was able to reach the API to confirm it.

If the countdown expires, nothing is lost: the settings are still saved and the
previous connection comes back. Switch **Run the hotspot** on and save again.

### Turning the hotspot off

**To stop it but keep the settings** — open the hotspot control, switch **Run the
hotspot** off and press **Save hotspot settings**. The network drops immediately
and will not start on boot. The name and password are remembered, so switching it
back on later needs no re-entry.

During the confirmation countdown there is a shortcut: press **Stop it now**.

**To forget it entirely** — `DELETE /api/hotspot` removes the NetworkManager
profile, including the stored password:

```bash
curl -X DELETE http://<PI_IP>:8000/api/hotspot \
  -b sentry-cookies.txt
```

**To turn the whole feature off** — set `SENTRY_HOTSPOT_CONTROL_ENABLED=false` in
`.env` and restart. Sentry then refuses every hotspot change, runs no `nmcli`, and
makes no D-Bus call. Note this does *not* take down a hotspot that is already
running, because the profile belongs to NetworkManager rather than to Sentry —
stop it first, or bring it down on the Pi directly.

**From the Pi, when the UI is unreachable** — the usual case is having just
disconnected yourself. Over Ethernet, or with a keyboard and monitor:

```bash
sudo nmcli connection down sentry-hotspot          # stop it now
sudo nmcli connection modify sentry-hotspot \
     connection.autoconnect no                     # and stop it starting on boot
sudo nmcli connection up "<your usual network>"    # reconnect the Pi
```

### Connecting a client

1. On the client, add the network **manually** — hidden networks never appear in
   a scan. On macOS that is Wi-Fi → *Other…*; on iOS, Settings → Wi-Fi → *Other*.
   Enter the exact network name, WPA2/WPA3-Personal, and the password.
2. Read the **address for clients** off the hotspot panel (`10.42.0.1` by
   default) and enter it, with each device's port, in Sentinel's SDR settings.
   The control channel is still `port + 2`, exactly as on a LAN.

The panel also lists **recent DHCP leases** so you can see which machines were
given an address. A lease is not a live connection: a client that has walked out
of range keeps its lease until it expires, and one with a static address never
appears at all.

### Things worth knowing

- **Hiding the network is not a security control.** It defeats casual scanning
  and nothing else — the network is still discoverable to anyone watching a
  client associate. The password is what protects it.
- **Sentry never shows a saved password back to you.** It is write-only: the API
  reports only whether one is set, and there is no endpoint that returns it. If
  it is forgotten, set a new one.
- **Hotspot clients can reach your uplink LAN.** The hotspot uses
  NetworkManager's shared mode, which provides DHCP, DNS and NAT — and NAT
  routes joined clients out toward whatever network the Pi is on.
- **WPA3 is experimental.** It is unreliable on some Raspberry Pi radios. WPA2 is
  the default and the safe choice.
- **If `SENTRY_ADVERTISED_HOST` is set**, it is published to hotspot-joined
  clients too, who cannot reach a LAN address. Sentry warns about this rather
  than overriding your setting; use the address shown on the hotspot panel.
- Sentry owns exactly one NetworkManager profile (`sentry-hotspot`) and never
  reads, edits or deletes any other.

---

## Wired (Ethernet) sharing

The hotspot's twin, over a cable (ADR-0014). Plug a laptop straight into one of
the Pi's Ethernet ports and Sentry hands it an address, so it reaches Sentry and
Sentinel exactly as a hotspot client does — no router, no switch, no passphrase.

Everything is done from the **Wired (Ethernet) sharing** box in Settings, below
the hotspot.

### Read this before you start

**On a Pi with one Ethernet port, that port is the uplink.** Sharing it stops the
Pi being a client of your network and makes it *be* the network for whatever is
plugged in — so its LAN address goes away, and the browser you are reading this
in loses the Pi if you are reaching it over that cable.

Two things make that survivable, and you should have at least one of them:

- **Sharing is provisional.** It comes up on trial and rolls itself back after
  the confirmation window unless you press **Confirm** — so a share nobody can
  reach cannot survive, and cannot start on boot.
- **Confirm from the other side.** Start the hotspot first and confirm over that,
  or plug the laptop in and confirm from the new address, or keep a keyboard and
  monitor on the Pi.

If you have a **USB Ethernet adapter**, use its port instead: it appears in the
picker like any other, and sharing it costs the Pi nothing.

### Turning it on

1. Open the **Wired (Ethernet) sharing** box in Settings.
2. Set a **controller password** first if you have not — sharing is refused
   without one, because anyone who plugs in a cable lands on the same network as
   this API. The **host network control** switch in the hotspot box above must
   also be on; the same switch covers both features.
3. Choose the **Ethernet port**. A port carrying the Pi's own connection says so
   in the list, and choosing it raises the red acknowledgement box — tick it.
4. Leave **Address for cabled machines** blank unless you need a specific range.
   The default is `10.10.10.1/24`, deliberately not the hotspot's `10.42.0.1/24`.
5. Press **Save wired settings**, then switch **Enable wired sharing** on.
6. Press **Confirm** before the countdown runs out.

### Connecting a machine

1. Plug an Ethernet cable between the Pi's shared port and the machine. No
   configuration is needed on the machine — it asks for an address and gets one.
2. Read the **Sentry IP** off the panel (`10.10.10.1` by default) and enter it,
   with each device's port, in Sentinel's SDR settings. The control channel is
   still `port + 2`, exactly as on a LAN.

The panel lists **recent DHCP leases** so you can see which machines were given
an address, and warns when sharing is running with **nothing plugged in** — by
far the commonest reason a share that came up correctly appears to do nothing.

### Turning it off

Switch **Enable wired sharing** off. The port goes back to its normal profile,
which on a one-port Pi means the Pi rejoins your LAN at its usual address. To
forget the configuration entirely:

```bash
curl -X DELETE http://<PI_IP>:8000/api/wired \
     -H "Cookie: <your console session cookie>"
```

If you lock yourself out, from a keyboard and monitor on the Pi:

```bash
sudo nmcli connection down sentry-wired            # stop it now
sudo nmcli connection modify sentry-wired \
     connection.autoconnect no                     # and stop it starting on boot
```

### Things worth knowing

- **The cable is the credential.** There is no passphrase anywhere in this
  feature — reaching the network requires physical access to the port. That is a
  deliberate property, not a missing one.
- **Cabled machines can reach your uplink LAN**, where the Pi still has one:
  NetworkManager's shared mode provides DHCP, DNS and NAT.
- **Both can run at once.** The hotspot and the wired share are independent, on
  separate ranges, with separate lease lists. On a one-radio, one-port Pi,
  running the hotspot is how you keep a way in while sharing the cable.
- **If `SENTRY_ADVERTISED_HOST` is set**, it is published to cabled machines too,
  which cannot reach a LAN address. Sentry warns rather than overriding your
  setting; use the address shown on the panel.
- Sentry owns exactly one wired NetworkManager profile (`sentry-wired`) and never
  reads, edits or deletes any other.

---

## Configuration files

Standing up a second Pi otherwise means retyping every device's name, port,
antenna, notes and visibility by hand and getting all of them right. Instead,
export from a working Sentry and import into the new one.

Open the **configuration control in the top-right of the header**:

- **Download configuration** saves `sentry-config.json`.
- **Choose a configuration file…** stages a file and shows what it contains.
  Nothing is applied until you press **Apply this configuration** — an import
  rewrites every device's settings, which is too much to happen as a side effect
  of a file picker closing.

The same thing over the API. If a password is set, sign in once and keep the
session cookie in a jar — there is no bearer token to send:

```bash
curl -c sentry-cookies.txt -X POST http://<PI_IP>:8000/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"password": "your-password"}'
```

Then use it on every call (omit `-b` entirely while the controller has no
password):

```bash
curl -b sentry-cookies.txt \
  http://<PI_IP>:8000/api/config > sentry-config.json

curl -X POST http://<PI_IP>:8000/api/config \
  -b sentry-cookies.txt \
  -H 'Content-Type: application/json' \
  -d "{\"config\": $(cat sentry-config.json), \"apply_devices\": true}"
```

`config.example.json` in the repo root shows the shape. Prefer exporting a real
file over hand-writing one — the format is validated on import, and an exported
file is always correct.

### What a config file does and does not carry

Devices are matched by their **identity** (`serial:AIS-01`, `usb:1-1.3`), not by
row id, so the same file describes the same physical dongles on any Pi.

An import is reported entry by entry, because a partial import is the *expected*
outcome rather than an error:

- **applied** — the settings were written.
- **skipped** — that dongle is not plugged into this Sentry yet. Plug it in and
  import again.
- **failed** — the settings were rejected, usually because the port is already
  taken here. The reason is shown per entry.

Entries are replayed through the same validation `PATCH /api/devices/{id}` uses,
so an import can never write a configuration the normal endpoint would refuse.

**The hotspot password goes in, but never comes out.**

A config file is the most copied, emailed and committed artefact a project has,
so an *export* never contains WiFi credentials — it records only whether a
password was set (`passphrase_set`). `GET /api/config` is reachable by anyone
who can reach the API, and a password falling out of a routine export is not a
risk worth the convenience.

An *import* may carry one. Add a `passphrase` to the file's `hotspot` section
and it is applied, which is what lets a fresh Pi be provisioned to a working
hotspot in a single import:

```jsonc
"hotspot": {
  "ssid": "Sentry Field",
  "hidden": true,
  "security": "wpa2",
  "passphrase": "your-wifi-password"   // import-only; never appears in an export
}
```

The asymmetry is the point: a file you hand-wrote is one you chose to make
sensitive and control, whereas one Sentry produced could be anywhere. The field
is structurally excluded from serialisation, so a file Sentry wrote cannot
contain a password however it was produced. **Treat any file you add one to as
a secret** — do not commit it.

Setting a password this way needs a controller password configured, the same
gate every other hotspot change passes. Importing hotspot settings writes the
network's name, band and address but **never starts it**, with or without a
password — you turn it on yourself, from a panel that shows what you are about
to broadcast. Without a password in the file, a Pi with none stored refuses the
hotspot section rather than writing an SSID it could never use.

**One thing is absent entirely.**

*The deploy-time settings* `SENTRY_HOTSPOT_CONTROL_ENABLED` and
`SENTRY_HOTSPOT_CONTROL_ENABLED`. That is `.env`-only because it is precisely the
controls that require shell access to the Pi. A file that could switch on host
WiFi control, or set the API's own credential, would hand that away to anyone
who can reach the API — which is unauthenticated by default. The hotspot panel
shows the exact lines to paste, with a copy button, rather than editing them.

> **Not a boot-time seed.** Unlike Sentinel's `default_config.json`, dropping a
> file next to Sentry does nothing on startup. A device's configuration can only
> be applied once that dongle has actually been detected, and on a cold boot
> nothing has been enumerated yet — a startup seed would silently skip every
> entry. Import through the UI or the API once the dongles are up.

---

## API

| Endpoint                        | Purpose                                                                            |
| ------------------------------- | ---------------------------------------------------------------------------------- |
| `GET /api/health`               | Liveness. 200 while dongles are degraded; 503 only if the database is unreachable. |
| `GET /api/status`               | Full JSON snapshot of every device                                                 |
| `GET /api/events`               | SSE stream — `snapshot`, `device_changed`, `device_removed`, `health`, `notice`    |
| `GET /api/devices`              | Device configuration, including unconfigured ones                                  |
| `PATCH /api/devices/{id}`       | Set name, output port, enabled, visibility, notes, antenna, tuning defaults        |
| `DELETE /api/devices/{id}`      | Forget an absent device's configuration                                            |
| `POST /api/devices/{id}/serial` | Write a unique serial via `rtl_eeprom`                                             |
| `GET /api/v1/sdrs`              | The public dongles, for Sentinel                                                   |
| `GET /api/hotspot`              | Hotspot configuration and state. Always 200 — degrades rather than failing         |
| `GET /api/hotspot/interfaces`   | Wireless interfaces the hotspot could use, and which carries the Pi's own link     |
| `GET /api/hotspot/clients`      | DHCP leases the hotspot has issued. `null` means "cannot tell", never "none"       |
| `PUT /api/hotspot`              | Replace the hotspot configuration. Omit `passphrase` to keep the stored one        |
| `POST /api/hotspot/enable`      | Start the hotspot, provisionally — it rolls back unless confirmed                  |
| `POST /api/hotspot/disable`     | Stop the hotspot                                                                   |
| `POST /api/hotspot/confirm`     | Keep a hotspot that is on trial, and let it start on boot                          |
| `DELETE /api/hotspot`           | Forget the hotspot, password included                                              |
| `GET /api/wired`                | Wired-sharing configuration and state. Always 200 — degrades rather than failing   |
| `GET /api/wired/interfaces`     | Ethernet ports that could be shared, and which carries the Pi's own link           |
| `GET /api/wired/clients`        | DHCP leases the wired share has issued. `null` means "cannot tell", never "none"   |
| `PUT /api/wired`                | Replace the wired-sharing configuration                                            |
| `POST /api/wired/enable`        | Start wired sharing, provisionally — it rolls back unless confirmed                |
| `POST /api/wired/disable`       | Stop wired sharing                                                                 |
| `POST /api/wired/confirm`       | Keep a wired share that is on trial, and let it start on boot                      |
| `DELETE /api/wired`             | Forget the wired-sharing configuration                                             |
| `GET /api/config`               | Export this instance's configuration — devices and hotspot, never a password       |
| `GET /api/config/download`      | The same payload with a `Content-Disposition` filename attached                    |
| `POST /api/config`              | Import a configuration, reporting each entry's outcome. May carry a hotspot password |

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
| `SENTRY_MAX_DEVICES`          | `8`                                   | Device cap                                             |
| `SENTRY_INTERNAL_PORT_BASE`   | `14000`                               | Base of the loopback-only `rtl_tcp` range              |
| `SENTRY_RESERVED_PORTS`       | *(empty)*                             | Extra ports Sentry must never assign                   |
| `SENTRY_RECONCILE_INTERVAL_S` | `2.0`                                 | Sysfs sweep period (hotplug safety net)                |
| `SENTRY_LOG_LEVEL`            | `INFO`                                | Logging level                                          |
| `SENTRY_CORS_ORIGINS`         | *(empty — CORS closed)*               | Allow-list for a separately-hosted dev frontend        |

WiFi hotspot (all inert while control is off):

| Variable                            | Default                  | Purpose                                                       |
| ----------------------------------- | ------------------------ | ------------------------------------------------------------- |
| `SENTRY_HOTSPOT_CONTROL_ENABLED`    | `false`                  | Master switch for host WiFi control                           |
| `SENTRY_HOTSPOT_REQUIRE_AUTH_TOKEN` | `true`                   | Refuse hotspot changes while no controller password is set     |
| `SENTRY_HOTSPOT_CONNECTION_NAME`    | `sentry-hotspot`         | The single NetworkManager profile Sentry owns                 |
| `SENTRY_HOTSPOT_INTERFACE`          | *(chosen automatically)* | Wireless interface to use                                     |
| `SENTRY_HOTSPOT_GATEWAY_CIDR`       | `10.42.0.1/24`           | The Pi's address on the hotspot — what clients dial           |
| `SENTRY_HOTSPOT_CONFIRM_TIMEOUT_S`  | `120.0`                  | Seconds to confirm a hotspot before it rolls back             |
| `SENTRY_NMCLI_PATH`                 | `nmcli`                  | nmcli binary path                                             |
| `SENTRY_NMCLI_TIMEOUT_S`            | `20.0`                   | Per-command timeout for nmcli                                 |
| `SENTRY_NM_STATE_ROOT`              | `/var/lib/NetworkManager`| Where NetworkManager keeps its dnsmasq lease files            |

Wired (Ethernet) sharing. Gated by the *same* `SENTRY_HOTSPOT_CONTROL_ENABLED`
switch and the same console-password requirement — it is one host-network
capability, not two (ADR-0014):

| Variable                          | Default                  | Purpose                                                       |
| --------------------------------- | ------------------------ | ------------------------------------------------------------- |
| `SENTRY_WIRED_CONNECTION_NAME`    | `sentry-wired`           | The single NetworkManager wired profile Sentry owns           |
| `SENTRY_WIRED_INTERFACE`          | *(chosen automatically)* | Ethernet port to share                                        |
| `SENTRY_WIRED_GATEWAY_CIDR`       | `10.10.10.1/24`          | The Pi's address on the cable — what a plugged-in machine dials |
| `SENTRY_WIRED_CONFIRM_TIMEOUT_S`  | `120.0`                  | Seconds to confirm a wired share before it rolls back         |

`SENTRY_WIRED_GATEWAY_CIDR` must not overlap `SENTRY_HOTSPOT_GATEWAY_CIDR`;
Sentry refuses to start if it does. Both features run their own DHCP server and
can be up at the same time.

### Security

**A fresh install has no password**, which suits a trusted home LAN: plug in,
open the controller, name your dongles. Nothing is asked of you.

The consequence is worth understanding rather than skipping. Until you set a
password, **anyone who can reach the Pi has full control of it** — renaming
devices, reassigning ports, disabling radios, exporting your whole configuration
or importing one that replaces it. Sentry can spawn processes, bind ports and
write dongle firmware. On a home network with nothing else on it that is often
fine; it stops being fine with guests on the WiFi, or the moment you want the
hotspot.

Set one from the controller — it asks on first visit, and keeps asking while
none is set:

> **Settings → Sentry controller password**

It is hashed with argon2id and stored in Sentry's own database. Signing in gives
this browser an `HttpOnly; SameSite=Strict` session cookie, so nothing is kept in
the page and there is no token to paste. Changing the password signs out every
other browser immediately, which is what you want if you think it is known.

`GET /api/health` stays open — the Docker healthcheck must reach it whatever the
password, and it reports counts rather than identities. `GET /api/v1/sdrs` is
also open: it is the read-only export Sentinel consumes, filtered to the devices
you marked public (see below).

**Forgotten it?** From the Pi:

```bash
./tools/reset-password.sh
```

That clears the password and returns the controller to open, ready for a new
one. It grants nothing that shell access did not already — anyone who can run it
could read the database directly.

**What a password does not cover.** Your dongles' ports (1234, 2345…) stay open.
`rtl_tcp` has no authentication; that is the protocol every SDR client speaks,
not a choice Sentry made. Anyone on your LAN can still connect to a radio and
tune it. The password guards management, not the RF path.

**"Private" now means private.** `GET /api/v1/sdrs` needs no credential, so the
per-device visibility flag is the whole access control on it: a device marked
public has its name, host, port, notes and antenna readable by anyone who can
reach the Pi. Mark anything you would not publish as private.

The container runs `privileged: true` with the whole USB bus passed through,
which is required for dongles that re-enumerate. It does **not** mount the Docker
socket — earlier versions did, which was root-equivalent host control; the
supervisor is now the parent of its own child processes and restarts them
directly (see `docs/adr/0002`).

**The WiFi hotspot makes a password effectively mandatory.** Raising an access
point invites unknown machines onto the same network as this API, so Sentry
refuses every hotspot change while no controller password is set. Host
WiFi control is also off by default (`SENTRY_HOTSPOT_CONTROL_ENABLED`), so it has
to be turned on deliberately by someone with shell access to the Pi. The hotspot
password is write-only end to end: it is never returned by any endpoint, never
logged, and never stored by Sentry — NetworkManager holds it in its own root-only
keyfile. See `docs/adr/0007` for why driving the host's NetworkManager from this
container was preferred to a separate privileged helper.

Note that the hotspot's shared mode provides NAT as well as DHCP and DNS, so a
client that joins it can route out to whatever network the Pi's uplink is on.
That is inherent to the mode and is not restricted.

---

## Architecture

Design documents live in `docs/`:

- `docs/architecture/sentry-sdr-controller.md` — the full design
- `docs/adr/0001` — one container with subprocess supervision, not a container per dongle
- `docs/adr/0002` — dropping the Docker socket
- `docs/adr/0003` — device identity strategy
- `docs/adr/0004` — SSE over WebSocket
- `docs/adr/0005` — SQLite with WAL
- `docs/adr/0006` — adopting Sentinel's visual language
- `docs/adr/0007` — driving the host's NetworkManager for the WiFi hotspot

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
