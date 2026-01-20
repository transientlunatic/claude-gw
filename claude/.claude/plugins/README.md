# Claude Plugins Directory

This directory contains plugin configurations for Claude CLI.

## Structure

- `known_marketplaces.json` - Configuration for plugin marketplace sources

## Note

The `marketplaces/` subdirectory is excluded from version control as it contains downloaded marketplace data that can be re-fetched.

## Syncing

The `known_marketplaces.json` file is automatically synced when you run `../../sync-from-system.sh` from the repo root.
