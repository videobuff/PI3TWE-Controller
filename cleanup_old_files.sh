#!/bin/bash
set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${YELLOW}=== PI3TWE CLEANUP SCRIPT ===${NC}"
echo ""
echo "Scanning voor obsolete bestanden..."
echo ""

FILES_TO_DELETE=()

# Check app.py backups
for f in app.py.backup* app.py.bak* app.py.before* app.py.sqlite* app.py.working*; do
    [ -f "$f" ] && FILES_TO_DELETE+=("$f")
done

# Check README backup
[ -f "README.md.backup_v2.0" ] && FILES_TO_DELETE+=("README.md.backup_v2.0")

# Check webroot backup
[ -f "webroot/index.html.backup" ] && FILES_TO_DELETE+=("webroot/index.html.backup")

# Check obsolete scripts
[ -f "create_new_empty_influx_db.sh" ] && FILES_TO_DELETE+=("create_new_empty_influx_db.sh")
[ -f "tools/dht_to_influx_test.py" ] && FILES_TO_DELETE+=("tools/dht_to_influx_test.py")
[ -f "tools/dynu_update.sh" ] && FILES_TO_DELETE+=("tools/dynu_update.sh")
[ -f "tools/ddns_update.sh" ] && FILES_TO_DELETE+=("tools/ddns_update.sh")

if [ ${#FILES_TO_DELETE[@]} -eq 0 ]; then
    echo -e "${GREEN}Geen obsolete bestanden gevonden! Directory is al schoon.${NC}"
    exit 0
fi

echo -e "${RED}Te verwijderen bestanden:${NC}"
for f in "${FILES_TO_DELETE[@]}"; do
    SIZE=$(du -h "$f" | cut -f1)
    echo "  • $f ($SIZE)"
done

echo ""
read -p "Verwijderen? Type 'ja': " response

if [ "$response" != "ja" ]; then
    echo -e "${GREEN}Afgebroken.${NC}"
    exit 0
fi

echo ""
for f in "${FILES_TO_DELETE[@]}"; do
    rm -v "$f"
done

echo ""
echo -e "${GREEN}✓ Cleanup voltooid!${NC}"
