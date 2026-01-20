#!/usr/bin/env bash
set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET_DIR="$HOME"

echo -e "${YELLOW}Removing Claude configuration symlinks...${NC}"

cd "$REPO_DIR"

# Unstow the claude directory
stow -v -D -t "$TARGET_DIR" claude

echo -e "${GREEN}✓ Symlinks removed!${NC}"
echo ""
echo "Your ~/.claude directory is no longer managed by this repository."
echo "The files in $REPO_DIR are unchanged."
