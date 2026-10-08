#!/bin/sh
# Encrypt or decrypt a backup with a passphrase that never appears in a command
# line (#41).
#
#   BACKUP_PASSPHRASE=... scripts/backup_crypto.sh encrypt OUT   < dump   (stdin -> OUT)
#   BACKUP_PASSPHRASE=... scripts/backup_crypto.sh decrypt FILE  > dump   (FILE -> stdout)
#
# Why a script, and why a file: a process's argv is world-readable on Linux
# (`ps auxww`, /proc/<pid>/cmdline is mode 444), so `gpg --passphrase "$PW"` shows
# every local account the key to every governance record for as long as the dump
# runs. The passphrase is taken from the ENVIRONMENT (readable only by the same
# user, in /proc/<pid>/environ at mode 400), written with the shell builtin
# `printf` (so no external process ever has it in argv) to a mode-600 temp file,
# and handed to gpg by FILE NAME. The file is removed on exit, however it exits.
#
# stdin is the dump stream in both directions, which rules out --passphrase-fd 0.
#
# Do NOT pass the passphrase as `make backup BACKUP_PASSPHRASE=...`: that puts it
# in make's own argv. Export it, or read it from a secret store.
set -eu

mode="${1:-}"
target="${2:-}"

if [ -z "${BACKUP_PASSPHRASE:-}" ]; then
  echo "BACKUP_PASSPHRASE is not set." >&2
  exit 2
fi
if [ -z "$mode" ] || [ -z "$target" ]; then
  echo "usage: backup_crypto.sh encrypt OUT | decrypt FILE" >&2
  exit 2
fi

umask 077
keyfile="$(mktemp)"
trap 'rm -f "$keyfile"' EXIT HUP INT TERM
printf '%s' "$BACKUP_PASSPHRASE" > "$keyfile"

# --pinentry-mode loopback: from GnuPG 2.1, a passphrase given on the command
# line or in a file is ignored unless pinentry is in loopback mode.
case "$mode" in
  encrypt)
    gpg --batch --quiet --symmetric --cipher-algo AES256 \
      --pinentry-mode loopback --passphrase-file "$keyfile" --output "$target"
    ;;
  decrypt)
    gpg --batch --quiet --decrypt \
      --pinentry-mode loopback --passphrase-file "$keyfile" "$target"
    ;;
  *)
    echo "unknown mode: $mode" >&2
    exit 2
    ;;
esac
