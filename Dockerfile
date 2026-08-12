# Sentry — multi-dongle RTL-SDR controller.
#
# Three build stages, one final runtime image (ADR-0001: one container, one
# process tree, subprocess supervision — no per-dongle containers, no Docker
# socket). None of the build toolchains (cmake/gcc, node, uv's dependency
# cache) ship in the final image.

# ---------------------------------------------------------------------------
# Stage 1 — build librtlsdr from source: rtl_tcp, rtl_eeprom, libusb-1.0-dev
# ---------------------------------------------------------------------------
# Pinned to the same Debian release (bookworm) as the python:3.12-slim runtime
# stage below, so the shared objects built here are glibc/ABI-compatible with
# the final image without needing a static link.
FROM debian:bookworm-slim AS rtlsdr-build

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential cmake git libusb-1.0-0-dev pkg-config ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /src

# The proven build recipe from the legacy single-dongle Dockerfile, reused
# unchanged: -DDETACH_KERNEL_DRIVER=ON lets rtl_tcp/rtl_eeprom detach the DVB
# kernel driver at runtime as a second line of defence behind the host-side
# blacklist (README).
RUN git clone --depth 1 https://github.com/steve-m/librtlsdr.git && \
    cd librtlsdr && mkdir build && cd build && \
    cmake ../ -DDETACH_KERNEL_DRIVER=ON -DCMAKE_INSTALL_PREFIX=/opt/rtlsdr && \
    make -j"$(nproc)" && make install

# ---------------------------------------------------------------------------
# Stage 2 — build the static UI
# ---------------------------------------------------------------------------
# No bundler and no framework: `tsc` emits browser-native ES modules, the
# Tailwind CLI compiles one stylesheet, and a copy step moves `index.html` and
# the vendored fonts across. Node is a build-time dependency only — it is absent
# from the runtime image below, as it was before.
FROM node:22-alpine AS frontend-build
WORKDIR /src/frontend

# Manifests + lockfile before source so the dependency layer survives source-only edits.
COPY app/frontend/package.json app/frontend/package-lock.json ./
RUN npm ci

COPY app/frontend/ ./
RUN npm run build
# -> /src/frontend/dist

# ---------------------------------------------------------------------------
# Stage 3 — Python dependencies (uv, frozen, no dev deps)
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS backend-build
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY --from=ghcr.io/astral-sh/uv:0.9.5 /uv /usr/local/bin/uv
WORKDIR /srv/sentry

# Manifests first: this layer is cached across every source-only change.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

COPY app/backend/ ./app/backend/
COPY alembic.ini ./

# ---------------------------------------------------------------------------
# Final stage — slim runtime: rtl_tcp/rtl_eeprom + librtlsdr, the backend
# venv, the backend source and the built SPA. No compiler, no node, no git.
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS runtime

# libusb-1.0-0 is the *runtime* shared object rtl_tcp/rtl_eeprom link against
# (the -dev/headers package stays in the build stage). tini is PID 1: it reaps
# the supervisor's `rtl_tcp`/relay subprocess tree on shutdown and forwards
# signals correctly, which a bare `uvicorn` as PID 1 does not do.
# procps supplies `ps`/`pkill`/`kill`, absent from python:3.12-slim by default
# — needed to inspect or signal the supervised `rtl_tcp`/relay process tree
# from inside the container (hardware-debugging finding: neither tool was
# available when diagnosing a wedged/unresponsive dongle on the Pi).
# network-manager is here for `/usr/bin/nmcli` ALONE (ADR-0007). The
# NetworkManager daemon the package also installs is never started — there is
# no init in this container, and it must not be: nmcli talks to the *host's*
# NetworkManager over the system D-Bus socket that docker-compose mounts in.
# A second NetworkManager fighting the host's one for the same radio is exactly
# the failure this design avoids. `--no-install-recommends` matters more than
# usual for it, keeping ppp, modemmanager and friends out of the image.
#
# `policy-rc.d` returning 101 tells the Debian package scripts not to start any
# service during the build. Without it, network-manager's postinst tries to
# `systemctl start` in a container that has no init and can fail the build.
RUN printf '#!/bin/sh\nexit 101\n' > /usr/sbin/policy-rc.d \
    && chmod +x /usr/sbin/policy-rc.d \
    && apt-get update && apt-get install -y --no-install-recommends \
        libusb-1.0-0 tini procps network-manager dnsmasq-utils \
    && rm -rf /var/lib/apt/lists/* \
    && rm -f /usr/sbin/policy-rc.d

# rtl_tcp and rtl_eeprom (the operator runs rtl_eeprom directly from this
# image for the duplicate-serial remedy — README), plus rtl_test and rtl_sdr —
# the standard librtlsdr diagnostics an operator or this project's own runbook
# needs to tell "electrically faulty/full-speed dongle" apart from a
# configuration error (hardware-debugging finding: `rtl_test -d <index>` was
# the one tool that would have made a bad cable/hub obvious immediately, and
# it shipped in none of the previous images) — plus the shared library the
# ctypes adapter (`adapters/ctypes_rtlsdr.py`) loads via `CDLL`.
COPY --from=rtlsdr-build \
    /opt/rtlsdr/bin/rtl_tcp /opt/rtlsdr/bin/rtl_eeprom \
    /opt/rtlsdr/bin/rtl_test /opt/rtlsdr/bin/rtl_sdr \
    /usr/local/bin/
COPY --from=rtlsdr-build /opt/rtlsdr/lib/ /usr/local/lib/
RUN ldconfig

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PATH="/srv/sentry/.venv/bin:$PATH"
WORKDIR /srv/sentry

# /srv/sentry is the repo root inside the image, so the backend package lands at
# /srv/sentry/app/backend/ — mirroring the checkout exactly, one level down
# rather than the /app/app/ that a WORKDIR of /app produced.
COPY --from=backend-build /srv/sentry /srv/sentry
COPY --from=frontend-build /src/frontend/dist /srv/sentry/app/frontend/dist

# Sentry's default DB URL (config.py) is sqlite+aiosqlite:////data/sentry.db —
# a named volume is mounted here in compose so names/ports survive
# `docker compose down` (requirement 7).
RUN mkdir -p /data

# Deliberately root, not a non-root USER (the one documented deviation from
# this project's default Docker posture): the compose service runs
# `privileged: true` with the whole USB bus passed through, which already
# grants the container host-level device access, and the RTL-SDR device
# nodes under /dev/bus/usb are root-owned with no group/other access on a
# stock Raspberry Pi OS. Running as a non-root user here would not shrink the
# container's effective host capability (privileged already grants it) but
# would break every dongle open() call unless the operator maintains
# additional udev rules, which nothing in this project documents or sets up.
# See README's Docker security note.

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3).status < 500 else 1)"

# `run_server.py` binds uvicorn from `SENTRY_HTTP_HOST`/`SENTRY_HTTP_PORT`
# (Settings) rather than a hardcoded `--host`/`--port`, which previously made
# both variables dead configuration, and wires uvicorn's access-log
# formatter to redact the SSE `?access_token=` query string.
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "-m", "app.backend.run_server"]
