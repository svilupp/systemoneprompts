#!/bin/sh
# Run one check while retaining the complete log. Success stays compact;
# failures print the captured diagnostics and preserve the child exit status.
set -u

usage() {
  printf 'Usage: %s <label> [--] <command> [args...]\n' "$(basename "$0")" >&2
}

if [ "$#" -lt 2 ]; then
  usage
  exit 2
fi

label=$1
shift
if [ "${1:-}" = "--" ]; then
  shift
fi
if [ "$#" -eq 0 ]; then
  usage
  exit 2
fi

log_root=${SYSTEMONEPROMPTS_CHECK_LOG_DIR:-${TMPDIR:-/tmp}}
log_root=${log_root%/}
mkdir -p "$log_root" 2>/dev/null || {
  printf '%s: unable to create log directory %s\n' "$label" "$log_root" >&2
  exit 1
}

safe_label=$(printf '%s' "$label" | tr -c '[:alnum:]_.-' '_')
log_path=$(mktemp "$log_root/systemoneprompts-${safe_label}.XXXXXX") || {
  printf '%s: unable to create temporary log in %s\n' "$label" "$log_root" >&2
  exit 1
}

printf '%s\n' '---' "$label started (full log: $log_path)"

"$@" >"$log_path" 2>&1
status=$?

if [ "$status" -eq 0 ]; then
  printf '%s\n' "$label: OK" '---'
else
  printf '%s\n' "$label: FAIL"
  cat "$log_path"
  printf '%s\n' '---'
fi

exit "$status"
