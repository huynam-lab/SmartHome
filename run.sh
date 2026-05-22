#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

LINK_FILE="$SCRIPT_DIR/link.txt"

APP_PID=""
CLOUDFLARED_PID=""
TUNNEL_PIPE=""
TUNNEL_READER_PID=""

if [ -f ".env" ]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
fi

APP_HOST="${WEB_SERVER_HOST:-127.0.0.1}"
APP_PORT="${WEB_SERVER_PORT:-5000}"
CLOUDFLARED_QUICK_TUNNEL_RETRIES="${CLOUDFLARED_QUICK_TUNNEL_RETRIES:-3}"

if command -v python3.10 >/dev/null 2>&1; then
  PYTHON_BIN="python3.10"
else
  PYTHON_BIN="python3"
fi

find_cloudflared_bin() {
  if command -v cloudflared >/dev/null 2>&1; then
    command -v cloudflared
    return 0
  fi

  return 1
}

cleanup() {
  if [ -n "$TUNNEL_READER_PID" ] && kill -0 "$TUNNEL_READER_PID" >/dev/null 2>&1; then
    kill "$TUNNEL_READER_PID" >/dev/null 2>&1 || true
    wait "$TUNNEL_READER_PID" 2>/dev/null || true
  fi

  if [ -n "$CLOUDFLARED_PID" ] && kill -0 "$CLOUDFLARED_PID" >/dev/null 2>&1; then
    kill "$CLOUDFLARED_PID" >/dev/null 2>&1 || true
    wait "$CLOUDFLARED_PID" 2>/dev/null || true
  fi

  if [ -n "$APP_PID" ] && kill -0 "$APP_PID" >/dev/null 2>&1; then
    kill "$APP_PID" >/dev/null 2>&1 || true
    wait "$APP_PID" 2>/dev/null || true
  fi

  if [ -n "$TUNNEL_PIPE" ] && [ -p "$TUNNEL_PIPE" ]; then
    rm -f "$TUNNEL_PIPE"
  fi
}

wait_for_app() {
  local i
  for i in $(seq 1 60); do
    if ! kill -0 "$APP_PID" >/dev/null 2>&1; then
      printf 'Web app process exited before opening port %s.\n' "$APP_PORT" >&2
      return 1
    fi

    if bash -lc "exec 3<>/dev/tcp/$APP_HOST/$APP_PORT" >/dev/null 2>&1; then
      return 0
    fi

    if curl --silent --max-time 2 --output /dev/null "http://$APP_HOST:$APP_PORT/" >/dev/null 2>&1; then
      return 0
    fi

    sleep 1
  done
  return 1
}

start_tunnel() {
  local cloudflared_bin="$1"
  local tunnel_error_file=""
  local attempt=""
  local error_text=""
  local max_attempts="$CLOUDFLARED_QUICK_TUNNEL_RETRIES"
  rm -f "$LINK_FILE"

  for attempt in $(seq 1 "$max_attempts"); do
    TUNNEL_PIPE="$(mktemp -u /tmp/cloudflared.pipe.XXXXXX)"
    mkfifo "$TUNNEL_PIPE"
    tunnel_error_file="$(mktemp /tmp/cloudflared.err.XXXXXX)"

    (
      while IFS= read -r line; do
        if [ ! -s "$LINK_FILE" ]; then
          local_tunnel_url="$(printf '%s\n' "$line" | grep -oE 'https://[-[:alnum:]]+\.trycloudflare\.com' | head -n 1 || true)"
          if [ -n "$local_tunnel_url" ]; then
            printf '%s\n' "$local_tunnel_url" >"$LINK_FILE"
            printf 'Cloudflare Tunnel URL: %s\n' "$local_tunnel_url"
            printf 'Saved to %s\n' "$LINK_FILE"
          fi
        fi

        if printf '%s\n' "$line" | grep -qiE 'error|failed|invalid uuid|internal server error'; then
          printf '%s\n' "$line" >"$tunnel_error_file"
        fi
      done <"$TUNNEL_PIPE"
    ) &
    TUNNEL_READER_PID="$!"

    "$cloudflared_bin" tunnel --url "http://$APP_HOST:$APP_PORT" --no-autoupdate --loglevel info >"$TUNNEL_PIPE" 2>&1 &
    CLOUDFLARED_PID="$!"

    local i
    for i in $(seq 1 45); do
      if [ -s "$LINK_FILE" ]; then
        rm -f "$tunnel_error_file"
        return 0
      fi

      if ! kill -0 "$CLOUDFLARED_PID" >/dev/null 2>&1; then
        error_text=""
        if [ -s "$tunnel_error_file" ]; then
          error_text="$(tr '\n' ' ' <"$tunnel_error_file")"
        fi
        break
      fi
      sleep 1
    done

    if [ -n "$TUNNEL_READER_PID" ] && kill -0 "$TUNNEL_READER_PID" >/dev/null 2>&1; then
      kill "$TUNNEL_READER_PID" >/dev/null 2>&1 || true
      wait "$TUNNEL_READER_PID" 2>/dev/null || true
    fi
    if [ -n "$CLOUDFLARED_PID" ] && kill -0 "$CLOUDFLARED_PID" >/dev/null 2>&1; then
      kill "$CLOUDFLARED_PID" >/dev/null 2>&1 || true
      wait "$CLOUDFLARED_PID" 2>/dev/null || true
    fi
    if [ -n "$TUNNEL_PIPE" ] && [ -p "$TUNNEL_PIPE" ]; then
      rm -f "$TUNNEL_PIPE"
    fi

    if [ "$attempt" -lt "$max_attempts" ]; then
      if [ -n "$error_text" ]; then
        printf 'cloudflared attempt %s/%s failed: %s\n' "$attempt" "$max_attempts" "$error_text" >&2
      else
        printf 'cloudflared attempt %s/%s failed. Retrying...\n' "$attempt" "$max_attempts" >&2
      fi
      rm -f "$tunnel_error_file"
      sleep 2
      continue
    fi

    if [ -n "$error_text" ]; then
      if printf '%s' "$error_text" | grep -qiE '500 internal server error|invalid uuid length: 0|failed to unmarshal quick tunnel'; then
        printf 'cloudflared quick tunnel is currently unavailable from trycloudflare.com. Last error: %s\n' "$error_text" >&2
      else
        printf 'cloudflared error: %s\n' "$error_text" >&2
      fi
    else
      printf 'Timed out waiting for Cloudflare Tunnel URL.\n' >&2
    fi
    rm -f "$tunnel_error_file"
    return 1
  done

  return 1
}

trap cleanup EXIT INT TERM

"$PYTHON_BIN" main.py &
APP_PID="$!"

if ! wait_for_app; then
  printf 'Web app did not become ready on http://%s:%s\n' "$APP_HOST" "$APP_PORT" >&2
  exit 1
fi

if CLOUDFLARED_BIN="$(find_cloudflared_bin)"; then
  start_tunnel "$CLOUDFLARED_BIN"
else
  printf 'cloudflared not found in PATH. Install cloudflared on the system and run again.\n' >&2
  exit 1
fi

wait "$APP_PID"
