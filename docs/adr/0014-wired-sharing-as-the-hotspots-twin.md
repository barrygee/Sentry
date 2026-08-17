# ADR-0014 — Wired (Ethernet) sharing is the hotspot's twin, not its generalisation

- **Status:** Accepted
- **Date:** 2026-08-16
- **Deciders:** project owner
- **Builds on:** [ADR-0007](0007-nmcli-over-host-dbus-for-the-hotspot.md) (the nmcli
  seam and the commit-confirm flow), [ADR-0013](0013-hotspot-control-is-operator-flippable.md)
  (the switch this reuses)

## Context

The hotspot solves one problem: a machine with no route to the Pi's LAN needs to
reach Sentry and Sentinel. It solves it over the air. The same problem exists
over a cable and had no answer — plug a laptop directly into the Pi's Ethernet
port and nothing hands it an address, so nothing happens at all. The two hosts
sit there, both waiting for a DHCP server that is not present.

That is a real gap rather than a theoretical one. A cable is faster, needs no
passphrase, works where the 2.4 GHz band is unusable, and is the obvious first
move for anyone standing next to the Pi with a laptop.

The awkward part is the target host's layout. This Pi has **one** Ethernet port,
and that port is its uplink — `sentinel.local` is reachable at its LAN address
over exactly the socket a share would take. So wired sharing is not "additive
unless you are unlucky", the way the hotspot is on a two-radio host. On this
hardware it takes the uplink by definition: the port stops being a DHCP client
of the house router and starts being a DHCP server for whatever is plugged into
it.

## Decision

**Wired sharing is implemented as a parallel feature to the hotspot — its own
seam, service, router and panel — sharing the machinery that is genuinely the
same and nothing else.**

Concretely:

- A `WiredShareController` Protocol (`interfaces/wired_share.py`) alongside
  `WifiApController`, driven by `NmcliWiredShareController` over the same
  `nmcli`/D-Bus path ADR-0007 established.
- A `WiredShareService` with **the same commit-confirm rollback timer**. On this
  Pi that timer is not a precaution, it is the feature's only safety mechanism:
  an activation reverts itself unless someone confirms from the other side, so a
  share nobody can reach cannot survive.
- `/api/wired*`, seven routes mirroring `/api/hotspot*`, behind **the same two
  gates**: host-network control switched on, and a console password set.
- A `sentry-wired` NetworkManager profile — exactly one, never any other, the
  same ownership rule ADR-0007 set.

### What is shared, and what is not

Shared, because it is one implementation of one thing:

- `adapters/nmcli_parsing.py` — the terse-output parsers, extracted from
  `nmcli_wifi_ap.py` rather than copied. nmcli's escaping is the most bug-prone
  code in the repo and must not exist twice.
- `base/dhcpLeaseList` and `base/rollbackCountdown` in the frontend. Both
  features issue leases from the same dnsmasq and run the same countdown; the
  hotspot's components are now thin wrappers supplying wording.
- **The host-network control switch.** `hotspot_control_enabled` is named for
  the hotspot but means "the API may reconfigure this host's networking", and
  sharing an Ethernet port is that same capability. A second switch would ask an
  operator to grant one permission twice, and would let them grant half of it —
  not a distinction the risk actually has, since either can take the Pi off the
  network.

Not shared, deliberately:

- **The Protocols and value types.** An Ethernet port has no SSID, no band, no
  channel and no AP capability. A merged interface would be one with half its
  fields nullable and a comment explaining when.
- **The secret handling — because there is none.** This is the load-bearing
  difference. A wired share has no passphrase: the cable is the credential, and
  reaching the network requires physical access to the port. Folding the two
  seams together would have produced a controller whose secret handling was
  *conditional*, which is the last place a conditional belongs. Instead
  `WiredShareProfile` has no companion secret argument, `_run` takes no `secret`
  parameter, nothing redacts anything, and there is no field anywhere in the
  feature that could leak a key it does not have.

### Two consequences worth stating

**The default range is `10.10.10.1/24`, not the hotspot's `10.42.0.1/24`,** and
`Settings` refuses an overlap at startup. Both features raise a `shared`
connection with its own DHCP server and both can run at once; overlapping ranges
would give the host one address on two interfaces and route one into the other —
a failure that presents as "the hotspot randomly stopped working" long after the
config change that caused it.

**Lease reads are now scoped by interface.** NetworkManager writes one dnsmasq
lease file per interface, and the pre-existing glob merged them all. That was
correct while only one shared connection could exist; with two it would list a
laptop on the cable among the hotspot's WiFi clients. `list_clients()` on both
controllers takes an optional `interface`, and both services pass their own
profile's.

## Alternatives considered

**Generalise the hotspot into one "shared network" feature.** Rejected on the
secret-handling point above, and because the operator-facing decisions barely
overlap: one asks for a network name, a password, a band and a channel; the
other asks which socket. A single form covering both would be mostly disabled
fields.

**Link-local plus mDNS instead of DHCP.** Genuinely attractive: it never takes
the uplink down, because it needs no server at all. Rejected as the primary
mechanism because it gives an unpredictable address, and the address is the
product here — a human reads it off the screen and types it into Sentinel on the
other machine.

*Amended 2026-08-17, after testing it on the real hardware.* This route already
works and needs no code: with sharing off, a directly-cabled machine and the Pi
both self-assign, Avahi answers mDNS, and `http://sentinel.local:8000` reaches
the console. Two things were learned doing it, and both are now in the README:

- It requires `SENTRY_HTTP_HOST=::`. On a link with no DHCP server, mDNS answers
  with an **IPv6** link-local address, and the default `0.0.0.0` is IPv4-only —
  so the name resolves and the connection is then refused. The default is left
  alone because a host with IPv6 disabled cannot bind `::` and would fail to
  start.
- It reaches the *console* and not the *SDRs*. Sentry publishes each dongle's
  address for Sentinel to dial, and those are IPv4, so nothing can stream over
  the link-local path.

That second point is what keeps this decision intact rather than overturning it.
The two mechanisms answer different questions — "I have lost access to a Pi" and
"a client on this cable has to receive audio" — so they are complementary, and
documenting the cheaper one first is the honest ordering.

**Require a second (USB) Ethernet adapter, refusing to share the uplink port.**
This is the configuration where the feature costs nothing, and it works today —
a dongle's port enumerates as `ethernet` and appears in the picker. Rejected as
a *requirement* because it makes the common hardware unable to use the feature
at all, to prevent something the commit-confirm timer already prevents.

## Consequences

- Sentry can now take its own Pi off the LAN on request. This is the intended
  behaviour, gated by an explicit acknowledgement in the UI, refused by the API
  without `confirm_uplink_loss`, and undone automatically if unconfirmed.
- An operator sharing the only Ethernet port should have the hotspot running, or
  a keyboard and monitor to hand, before starting. The panel says so.
- `nmcli_wifi_ap.py` no longer defines its own parsers. Existing imports of the
  module are unaffected; the functions moved, the behaviour did not.
- `HotspotService.list_clients()` became `async` in order to read its profile's
  interface before scoping the lease file.
