#!/usr/bin/env bash
#
# Clear the Sentry controller's password, from the Pi.
#
# The recovery path for a forgotten password. It grants nothing that shell
# access did not already confer — anyone who can run this could read or edit the
# database directly — so requiring it is not security theatre, it is simply
# where the authority already lay.
#
# Clearing the password returns the controller to open: usable immediately by
# anyone who can reach it, exactly as a fresh install is, and the UI will start
# asking for a new password on the next visit.
#
#   ./tools/reset-password.sh
#
set -euo pipefail

readonly REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
readonly SERVICE="sentry"

die() {
  printf '\n  %s\n\n' "$1" >&2
  exit 1
}

cd "$REPO_ROOT"

command -v docker >/dev/null 2>&1 || die 'Docker was not found. Run this on the Pi, in the Sentry directory.'
docker compose ps --quiet "$SERVICE" >/dev/null 2>&1 || die "No '$SERVICE' service here. Run this from the Sentry directory."

if [ -z "$(docker compose ps --quiet --status running "$SERVICE" 2>/dev/null)" ]; then
  die "Sentry is not running. Start it first:  docker compose up -d"
fi

cat <<'WARNING'

  This clears the Sentry controller's password.

  The controller becomes open — anyone who can reach this Pi will be able to
  change your SDRs, with no password — until you set a new one. Every signed-in
  browser is signed out immediately.

  Your devices, ports and hotspot settings are untouched.

WARNING
printf '  Continue? [y/N] '
read -r reply
case "$reply" in
  [yY] | [yY][eE][sS]) ;;
  *) die 'Left unchanged.' ;;
esac

# Run inside the container: it already has the venv, the models and — crucially —
# the same SENTRY_DATABASE_URL, so this cannot clear the password in one database
# while the app reads another.
docker compose exec -T "$SERVICE" python - <<'PYTHON'
import asyncio

from app.backend.config import get_settings
from app.backend.db import create_sentry_engine, create_sentry_session_factory
from app.backend.services.console_auth import ConsoleAuthService


async def main() -> None:
    engine = create_sentry_engine(get_settings())
    service = ConsoleAuthService(create_sentry_session_factory(engine))
    # Rotates the session secret as well as dropping the hash, so a cookie
    # copied from a browser before the reset cannot outlive it.
    await service.clear_password()
    await engine.dispose()


asyncio.run(main())
PYTHON

cat <<'DONE'

  Password cleared. The controller is now open.

  Open it in a browser and set a new password when it asks — or from
  Settings > Sentry controller password.

DONE
