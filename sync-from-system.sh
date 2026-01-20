#!/usr/bin/env bash
set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_DIR="$HOME/.claude"
DEST_DIR="$REPO_DIR/claude/.claude"

echo "Syncing Claude configuration from system to repository..."

if [ ! -d "$SOURCE_DIR" ]; then
    echo -e "${RED}Error: $SOURCE_DIR does not exist${NC}"
    exit 1
fi

# Create destination directory if it doesn't exist
mkdir -p "$DEST_DIR"

# List of files/directories to sync (excluding sensitive and cache data)
SYNC_ITEMS=(
    "agents"
    "plugins/known_marketplaces.json"
)

# Sync each item
for item in "${SYNC_ITEMS[@]}"; do
    if [ -e "$SOURCE_DIR/$item" ]; then
        echo -e "${GREEN}Syncing: $item${NC}"

        # Create parent directory if needed
        mkdir -p "$(dirname "$DEST_DIR/$item")"

        # Copy the item
        if [ -d "$SOURCE_DIR/$item" ]; then
            rsync -av --delete "$SOURCE_DIR/$item/" "$DEST_DIR/$item/"
        else
            cp -f "$SOURCE_DIR/$item" "$DEST_DIR/$item"
        fi
    else
        echo -e "${YELLOW}Skipping (not found): $item${NC}"
    fi
done

echo ""
echo -e "${GREEN}✓ Sync complete!${NC}"
echo ""
echo "Files synced to: $DEST_DIR"
echo ""
echo "To commit changes:"
echo "  cd $REPO_DIR"
echo "  git add ."
echo "  git commit -m 'Update Claude configuration'"
echo "  git push"
