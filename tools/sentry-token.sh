#!/usr/bin/env bash
#
# Generate, show or replace this Sentry's API access token.
#
# The token lives in .env and nowhere else. It cannot be set from the web UI on
# purpose: it is the credential guarding that API, and this API is
# unauthenticated until the token exists — so an endpoint able to set it would
# hand the lock to anyone who could already walk in. Requiring shell access is
# the whole control, and this script only removes the fiddly parts of exercising
# it, not the requirement itself.
#
#   ./tools/sentry-token.sh          generate a token (or replace the current one)
#   ./tools/sentry-token.sh --show   print the token currently configured
#
set -euo pipefail

readonly TOKEN_KEY="SENTRY_AUTH_TOKEN"
readonly REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
readonly ENV_FILE="$REPO_ROOT/.env"

die() {
  printf '\n  %s\n\n' "$1" >&2
  exit 1
}

current_token() {
  [ -f "$ENV_FILE" ] || return 0
  # Last assignment wins, matching how the file is read.
  grep -E "^${TOKEN_KEY}=" "$ENV_FILE" | tail -1 | cut -d= -f2- || true
}

generate_token() {
  # 32 bytes of CSPRNG, hex-encoded. openssl is present on Raspberry Pi OS and
  # anywhere Docker runs; /dev/urandom is the fallback for a stripped image.
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -hex 32
  else
    head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n'
  fi
}

show_token() {
  local token
  token="$(current_token)"
  if [ -z "$token" ]; then
    printf '\n  No %s is set. This Sentry’s API is open to anyone who can reach it.\n' "$TOKEN_KEY"
    printf '  Run this script with no arguments to set one.\n\n'
    exit 1
  fi
  printf '\n  %s\n\n' "$token"
}

# --- argument handling ------------------------------------------------------

case "${1:-}" in
  --show)
    show_token
    exit 0
    ;;
  '')
    ;;
  *)
    die "Unknown option: $1. Use --show, or no arguments to set a token."
    ;;
esac

# --- replacing an existing token is destructive, so it is confirmed ----------

existing="$(current_token)"
if [ -n "$existing" ]; then
  cat <<'WARNING'

  A token is already set. Replacing it takes effect immediately and there is
  no grace period, so everything currently using the old one stops working:

    * every browser tab with the console open (each needs the new token pasted)
    * any script or `curl` sending the old bearer token
    * Sentinel, if this Sentry is configured in it

  There is no way to recover the old value once it is overwritten.

WARNING
  printf '  Replace it? [y/N] '
  read -r reply
  case "$reply" in
    [yY] | [yY][eE][sS]) ;;
    *) die 'Left unchanged.' ;;
  esac
fi

# --- write it ---------------------------------------------------------------

token="$(generate_token)"

if [ ! -f "$ENV_FILE" ]; then
  # A missing .env is normal on a fresh checkout — the file is git-ignored, and
  # .env.example is a reference rather than something to copy blindly.
  printf '# Sentry configuration. Never commit this file.\n' > "$ENV_FILE"
fi

if grep -qE "^${TOKEN_KEY}=" "$ENV_FILE"; then
  # Rewrite in place. Appending a second line would "work" — the last wins —
  # but leaves a stale secret sitting in the file, and makes the next --show
  # ambiguous to anyone reading it by eye.
  tmp="$(mktemp)"
  # `|| true` because grep exits 1 when it filters out every line — which is
  # exactly what happens when .env contains nothing but this token, the most
  # likely shape of a minimal install. Without it, `set -e` aborts here after
  # having already announced the replacement, leaving the old token in place
  # and the operator believing it changed.
  grep -vE "^${TOKEN_KEY}=" "$ENV_FILE" > "$tmp" || true
  printf '%s=%s\n' "$TOKEN_KEY" "$token" >> "$tmp"
  mv "$tmp" "$ENV_FILE"
else
  printf '%s=%s\n' "$TOKEN_KEY" "$token" >> "$ENV_FILE"
fi

chmod 600 "$ENV_FILE" 2>/dev/null || true

printf '\n  Token written to .env:\n\n    %s\n\n' "$token"

# --- apply it ---------------------------------------------------------------

# `docker compose restart` is the intuitive command and the wrong one: it
# restarts the existing container, which keeps the environment it was created
# with, so the new token never reaches the app. Recreation is required.
if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  printf '  Recreating the container so it picks the token up…\n\n'
  # Not fatal: the token is already saved, and a failure here is usually the
  # daemon being down rather than anything wrong with the token. Saying so
  # beats aborting on a raw Docker error and leaving the operator unsure
  # whether the write succeeded.
  if (cd "$REPO_ROOT" && docker compose up -d); then
    printf '\n  Done. Reload the console and paste the token when it asks.\n\n'
  else
    printf '\n  The token is saved, but Docker could not restart Sentry.\n'
    printf '  Start it yourself, then reload the console:\n\n    docker compose up -d\n\n'
  fi
else
  cat <<'MANUAL'
  Docker Compose was not found here, so nothing was restarted. Apply it with:

    docker compose up -d

  (`docker compose restart` will NOT pick up the new token — a restart reuses
  the container's original environment.)

MANUAL
fi
