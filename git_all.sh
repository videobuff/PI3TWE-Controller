#!/bin/bash
#
# gitall - add, commit en push in één commando
#
# Gebruik:
#   gitall "commit message"
#

set -e

if [ -z "$1" ]; then
  echo "Gebruik: gitall \"commit message\""
  exit 1
fi

MSG="$1"

echo "=== Git status ==="
git status --short

echo
echo "=== Git add ==="
git add -A

echo
echo "=== Git commit ==="
git commit -m "$MSG"

echo
echo "=== Git push ==="
git push

echo
echo "Klaar."
