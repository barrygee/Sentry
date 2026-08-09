# Architecture Decision Records

Each ADR records one decision that was non-obvious or reversible-but-costly: the context that
forced it, the decision, and the consequences (good and bad) we accepted.

ADRs are immutable once accepted. To change a decision, add a new ADR that supersedes the old one
and update the old one's status to `Superseded by ADR-NNNN`.

| ADR | Title | Status |
|---|---|---|
| [0001](0001-one-container-subprocess-supervision.md) | One container with subprocess supervision, not a container per dongle | Accepted |
| [0002](0002-drop-docker-socket-wedge-recovery.md) | Drop the Docker socket; recover a wedged dongle by process exit | Accepted |
| [0003](0003-device-identity-strategy.md) | Three-tier device identity; librtlsdr index resolved at spawn, never cached | Accepted |
| [0004](0004-sse-over-websocket.md) | Server-Sent Events, not WebSocket, for realtime status | Accepted |
| [0005](0005-sqlite-wal-persistence.md) | SQLite with WAL for configuration persistence | Accepted |
| [0006](0006-adopt-sentinel-visual-language.md) | Adopt Sentinel's visual language, palette included | Accepted |
| [0007](0007-nmcli-over-host-dbus-for-the-hotspot.md) | Drive the host's NetworkManager over the system D-Bus socket, not a privileged sidecar | Accepted |
| [0008](0008-static-ui-over-vue-spa.md) | Replace the Vue SPA with a static, framework-free TypeScript UI | Accepted |
| [0009](0009-dual-control-sentry-owns-device-state.md) | Dual control: Sentry owns device state, Sentinel is a remote client | **Superseded by 0010** |
| [0010](0010-sentinel-reads-sentry-manages.md) | Sentinel reads, Sentry manages; a console password replaces the API token | Accepted |

The design these decisions serve is
[`docs/architecture/sentry-sdr-controller.md`](../architecture/sentry-sdr-controller.md).
