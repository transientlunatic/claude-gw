# Claude Configuration Repository

This repository keeps Claude CLI configurations under version control using GNU Stow for portable, symlink-based synchronization.

## What Gets Synced

This repository tracks:
- **Custom agents** (`~/.claude/agents/`)
- **Plugin configurations** (`~/.claude/plugins/known_marketplaces.json`)

### What's Excluded

The following are intentionally excluded (via [.gitignore](.gitignore)):
- Credentials and secrets (`.credentials.json`, `secrets.json`)
- Cache directories (`cache/`, `debug/`, `file-history/`, etc.)
- Runtime files (`history.jsonl`, `stats-cache.json`)
- Project-specific data (`projects/`, `plans/`)
- Downloaded plugin marketplaces (can be re-downloaded)

## Prerequisites

- GNU Stow (automatically installed by [install.sh](install.sh) on Linux/macOS)
- Git

## Setup

### Initial Setup

1. Clone this repository:
   ```bash
   git clone <repository-url> ~/repositories/personal/claude-gw
   cd ~/repositories/personal/claude-gw
   ```

2. Run the install script:
   ```bash
   ./install.sh
   ```

This will:
- Install GNU Stow if not present (Linux/macOS)
- Create symlinks from `~/repositories/personal/claude-gw/claude/.claude` to `~/.claude`
- Preserve existing files while creating the link structure

### On a New Machine

1. Clone the repository
2. Run `./install.sh`
3. Your Claude configuration will be immediately available

## Usage

### Syncing Changes

#### After Modifying Files in ~/.claude

If you add or modify agents or plugin configurations in `~/.claude/`, sync them back to the repository:

```bash
./sync-from-system.sh
git add .
git commit -m "Update Claude configuration"
git push
```

#### After Pulling Changes from Git

If you pull changes from the repository on another machine:

```bash
git pull
# Symlinks are automatically updated since ~/.claude points to the repo
```

### Uninstalling

To remove the symlink setup and restore `~/.claude` to a normal directory:

```bash
./uninstall.sh
```

## Directory Structure

```
claude-gw/
├── claude/              # Stow package directory
│   └── .claude/         # Mirrors ~/.claude structure
│       ├── agents/      # Custom Claude agents
│       └── plugins/     # Plugin configurations
├── install.sh           # Setup script
├── sync-from-system.sh  # Sync from ~/.claude to repo
├── uninstall.sh         # Remove symlinks
├── .gitignore           # Excludes sensitive/cache files
└── README.md            # This file
```

## How GNU Stow Works

GNU Stow creates symlinks from a "stow directory" to a target directory. When you run:

```bash
stow -t $HOME claude
```

It creates symlinks in `$HOME` that point to files in the `claude/` directory. For example:
- `~/.claude/agents/` → `~/repositories/personal/claude-gw/claude/.claude/agents/`

This allows you to:
- Edit files in `~/.claude` as normal
- Have those changes automatically reflected in the git repository
- Version control your configuration without moving it from its standard location

## Scripts

### install.sh

Installs GNU Stow (if needed) and creates symlinks from the repository to `~/.claude`.

### sync-from-system.sh

Copies configuration files from `~/.claude` back to the repository. Use this when you've added new agents or modified plugin configurations and want to commit them.

### uninstall.sh

Removes the symlinks created by stow, restoring `~/.claude` to a normal directory.

## Best Practices

1. **Before making changes**: Ensure you're on the correct branch
2. **After adding agents**: Run `sync-from-system.sh` to capture them
3. **Sensitive data**: Never commit credentials or API keys
4. **Multiple machines**: Pull before syncing to avoid conflicts

## Troubleshooting

### Symlinks Not Working

If symlinks aren't created properly:
```bash
./uninstall.sh
./install.sh
```

### Conflicts After Pull

If you have local changes and pull updates:
```bash
./sync-from-system.sh  # Save local changes
git pull --rebase      # Pull remote changes
```

### Checking Symlink Status

To verify symlinks are set up correctly:
```bash
ls -la ~/.claude
```

You should see symlinks pointing to this repository.

## Contributing

When adding new configuration types to sync:

1. Update `SYNC_ITEMS` in [sync-from-system.sh](sync-from-system.sh)
2. Update [.gitignore](.gitignore) if needed to exclude sensitive/cache files
3. Update this README to document what's being synced

## License

See [LICENSE](LICENSE)
