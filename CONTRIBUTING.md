# Contributing to Claude Configuration

## Workflow

### Adding New Configuration Types

When adding support for syncing new configuration files:

1. **Update sync script**: Add the file/directory to `SYNC_ITEMS` array in [sync-from-system.sh](sync-from-system.sh)

2. **Update .gitignore**: If the new config contains sensitive data or cache files, add patterns to [.gitignore](.gitignore)

3. **Update README**: Document what's being synced in the "What Gets Synced" section of [README.md](README.md)

4. **Test**: Run the full workflow:
   ```bash
   ./sync-from-system.sh
   ./uninstall.sh
   ./install.sh
   ```

### Adding Custom Agents

1. Create your agent file in `~/.claude/agents/your-agent.md`
2. Run `./sync-from-system.sh` to capture it
3. Commit and push:
   ```bash
   git add claude/.claude/agents/your-agent.md
   git commit -m "Add custom agent: your-agent"
   git push
   ```

### Modifying Scripts

When modifying shell scripts:

1. Test on multiple platforms if possible (Linux, macOS)
2. Ensure error handling with `set -euo pipefail`
3. Add descriptive echo statements for user feedback
4. Update relevant documentation

## Security Guidelines

**Never commit**:
- API keys or credentials
- Personal tokens
- Private data from projects
- Cache or temporary files

Always verify before committing:
```bash
git diff --staged
```

## Pull Request Process

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/your-feature`
3. Make your changes
4. Test thoroughly
5. Update documentation
6. Submit a pull request

## Questions?

Open an issue for discussion before making major changes.
