#!/bin/bash
#
# git_all.sh - add, commit en push in één commando
#
# Gebruik:
#   ./git_all.sh "commit message"
#   ./git_all.sh                    (vraagt om message)
#

set -e

cd "$(dirname "$0")"

# Kleuren
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check of we in een git repo zitten
if [ ! -d .git ]; then
  echo -e "${RED}Fout: geen git repository gevonden${NC}"
  exit 1
fi

# Commit message
if [ -z "$1" ]; then
  echo -n "Commit message: "
  read MSG
  if [ -z "$MSG" ]; then
    echo -e "${RED}Geen message opgegeven, afgebroken.${NC}"
    exit 1
  fi
else
  MSG="$1"
fi

echo -e "${YELLOW}=== Git status ===${NC}"
git status --short

# Check of er iets te committen is
if [ -z "$(git status --porcelain)" ]; then
  echo -e "${GREEN}Niets te committen, working tree is clean.${NC}"
  exit 0
fi

echo
echo -e "${YELLOW}=== Git add ===${NC}"
git add -A
echo "Alle wijzigingen gestaged."

echo
echo -e "${YELLOW}=== Git commit ===${NC}"
git commit -m "$MSG"

echo
echo -e "${YELLOW}=== Git push ===${NC}"
git push

echo
echo -e "${GREEN}✓ Klaar!${NC}"
