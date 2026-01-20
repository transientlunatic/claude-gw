#!/usr/bin/env bash
set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Detect OS
OS="$(uname -s)"
STOW_CMD="stow"

echo "Setting up Claude configuration sync..."

# Check if stow is installed
if ! command -v stow &> /dev/null; then
    echo -e "${YELLOW}GNU Stow is not installed.${NC}"

    case "$OS" in
        Linux*)
            if command -v apt-get &> /dev/null; then
                echo "Installing stow via apt-get..."
                sudo apt-get update && sudo apt-get install -y stow
            elif command -v yum &> /dev/null; then
                echo "Installing stow via yum..."
                sudo yum install -y stow
            elif command -v pacman &> /dev/null; then
                echo "Installing stow via pacman..."
                sudo pacman -S --noconfirm stow
            else
                echo -e "${RED}Please install GNU Stow manually for your distribution.${NC}"
                exit 1
            fi
            ;;
        Darwin*)
            if command -v brew &> /dev/null; then
                echo "Installing stow via Homebrew..."
                brew install stow
            else
                echo -e "${RED}Please install Homebrew first or install GNU Stow manually.${NC}"
                exit 1
            fi
            ;;
        *)
            echo -e "${RED}Unsupported OS: $OS${NC}"
            exit 1
            ;;
    esac
fi

# Get the directory where this script is located
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET_DIR="$HOME"

cd "$REPO_DIR"

echo -e "${GREEN}Creating symlinks with stow...${NC}"

# Stow the claude directory
stow -v -t "$TARGET_DIR" claude

echo -e "${GREEN}✓ Installation complete!${NC}"
echo ""
echo "Your Claude configuration is now managed from: $REPO_DIR/claude/.claude"
echo "It is symlinked to: $HOME/.claude"
echo ""
echo "To sync changes FROM ~/.claude to this repo, run: ./sync-from-system.sh"
echo "To update symlinks after pulling changes, run: ./install.sh again"
