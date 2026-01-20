# Claude Agents Directory

This directory contains custom agent definitions for Claude CLI.

## Adding Custom Agents

Place your custom agent markdown files (`.md`) in this directory. Each file should follow the Claude agent format with instructions and capabilities defined.

## Example Structure

```
agents/
├── README.md                    # This file
├── your-custom-agent.md         # Your custom agent
└── another-agent.md             # Another custom agent
```

## Syncing

After adding or modifying agents:

1. They will automatically be available in `~/.claude/agents/` (via symlink)
2. Run `../../sync-from-system.sh` from the repo root to capture changes
3. Commit and push to version control
