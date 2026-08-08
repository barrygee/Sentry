# Changelog

All notable changes to this project are documented in this file. It is generated
from the repository's [Conventional Commits](https://www.conventionalcommits.org)
and regenerated automatically on every merge to `main`, so **edit the commit
messages rather than this file** — the next run overwrites it. Follows
[Keep a Changelog](https://keepachangelog.com).


## [Unreleased]

### Features

- Add rtl_tcp fan-out relay to share the single-client dongle
- Add tuning-ownership control channel for shared dongle (#2)
- Add exit-on-wedge recovery for supervised operation
- Add hardware interfaces and adapters
- Add SQLite persistence with WAL and Alembic migrations
- Add device registry, supervisor and control follower
- Add REST and SSE surface with optional bearer auth
- Add Vue 3 fleet console with live topology and serial flashing
- Add mock Sentry server for hardware-free development
- Package Sentry as a single supervised container
- Restyle the console in Sentinel's settings visual language
- Match Sentinel's dark chrome, not its light settings panel
- Remove the USB topology section and the header streaming counter
- Match Sentinel's wordmark and type scale; centre the device stack
- Hide the Devices label and stack each card's fields
- Centre the header lockup
- Narrow the name and port inputs; remove every border
- Use Sentinel's palette unmodified
- Label the identity fields, add a relay-ports readout, reword the toggle
- Match inputs to Sentinel's search field; size the port input to its caption
- Remove the IQ/CTRL pair, name the centre frequency, unfill the status label
- Drop the port explanation line; pad above the header lockup
- Drop the name hint, open up row spacing, move the toggle caption left
- Explain why a plugged-in SDR cannot be forgotten
- Dismiss with an arm-then-confirm ✕/✓, as Sentinel's row actions do
- Three-row card layout, and remove the forget control and card title
- De-box the inputs and align them with the readouts beside them
- Lift the card off the page, rule the fields, level the value type
- Make every card title white and bold
- Align the card's columns across both rows
- Adopt Sentinel's shell — black header, left icon rail, light body
- One white box per device, on a canvas that reads darker
- Match Sentinel's settings type scale; stop the tones washing out
- Notices become solid vibrant fills instead of tints
- Publish only public devices, with notes and antenna
- Add private, notes and antenna controls to the device card
- Fix the app shell and align chrome with Sentinel
- Run a hidden WiFi network for Sentinel clients
- Export and import a whole instance's configuration
- Add the client address field and in-app .env setup help
- Version the management API as a cross-app contract
- Let a provisioning file carry the hotspot password

### Bug Fixes

- Track whole USB bus via devices + cgroup rule to survive re-enumeration
- Repair the integration defects that made the fleet manager non-functional
- Resolve address families instead of assuming IPv4 and IPv6
- Show only present hardware in the topology tree, and let absent devices be forgotten
- Stop losing reconcile events, and diagnose an unresponsive dongle
- Kill a hung child before respawning, and name a busy device
- Stop a cached index.html pinning the SPA to a stale bundle
- Put field labels above their inputs, as Sentinel does
- Drop the fills behind the IQ, CTRL, CENTER, RATE and GAIN readouts
- Make the forget action quiet and move it out of the header
- Remove the enable switch's track border
- Stop the notice tones reading as washed out
- Drop the sidebar toggle's fill while the sidebar is hidden
- Attribute notices to their device, and coalesce repeats
- Stop a rejected value coming back in the 422 body

### Chores

- Restructure for the Sentry backend and frontend
- Drop the root-level relay and test after the move
- Remove the retained legacy single-dongle compose
- Restore the test harness on the static console

### Other

- Initial commit
- Update Dockerfile and docker-compose.yml

### Refactoring

- Drop the Docker-socket wedge recovery path
- Replace the Vue SPA with a static TypeScript console

### Documentation

- Document the fan-out relay and 1234/1235 port split
- Add Sentry fleet-manager design and ADRs
- Point setup at this repository and drop predecessor references
- Describe the frontend that exists

### Continuous Integration

- Run every gate on pull requests and main
- Re-trigger checks
