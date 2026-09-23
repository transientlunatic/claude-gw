---
name: asimov-plugin-review
description: Strict review of an asimov pipeline plugin (an asimov-* package registered under the asimov.pipelines entry point) against asimov's ecosystem norms. Checks that the plugin uses core features (scheduler abstraction, PriorInterface, rundir, needs/assets, monitor states) rather than reimplementing them, and that its Python, bundled config template and blueprints use the standard ledger vocabulary rather than inventing duplicate keys. Use when asked to review, audit or check an asimov plugin or a PR to one, or before opening a plugin PR. Produces a JSON + Markdown report and, if given a PR, inline review comments.
---

# Reviewing an asimov plugin

This review is deliberately strict. A plugin that works is not enough: it
must work *the asimov way*, because every duplicated feature or invented
ledger key is a place where plugins drift apart and users have to write the
same number twice.

The rules are in `references/rules.md` and the output format is in
`references/output.md`. Read both before starting. `scripts/lint_plugin.py`
finds the mechanical candidates.

## Inputs

- **Plugin**: a local path, or a PR (owner/repo#N or URL). For a PR, check
  out its head branch locally.
- **asimov ref**: the branch or tag the plugin targets. Default to the newest
  of `v0.8-preview` / `main` that satisfies the plugin's `asimov` dependency
  pin. Say which one you used.
- **Wrapped code** (optional): the source of the analysis code the plugin
  drives. Several rules (completion markers, checkpointing, config schema)
  can only be checked against it. If it isn't available, list those rules
  under "not checked".

## Procedure

1. **Get asimov at the target ref.** Use an existing checkout if there is
   one, otherwise
   `git clone --depth 1 -b <ref> https://github.com/etive-io/asimov <scratch>/asimov`.
   Record the commit SHA. If `asimov/vocabulary.yaml` is missing at that ref
   (it arrives with etive-io/asimov#175), fetch that PR's head into the same
   checkout, use its vocabulary, and say so in the report.

2. **Run the linter.**
   ```bash
   python <skill>/scripts/lint_plugin.py <plugin> --asimov-src <asimov> --json > <scratch>/lint.json
   ```
   Exit status 1 just means there are BLOCKER/MUST-FIX candidates.

3. **Read the plugin completely**: `pyproject.toml`, every module in the
   package, the bundled template(s), every YAML blueprint (examples, tests,
   docs), the README and the tests. Don't review from the lint output alone.

4. **Read the core counterparts** at the target ref, at minimum:
   `asimov/pipeline.py` (the `Pipeline` base class and every hook the plugin
   overrides), `asimov/analysis.py` (`make_config`, `rundir`, `_collect_psds`,
   `_previous_assets`, `dependencies`), `asimov/scheduler.py` and
   `asimov/scheduler_utils.py` (`JobDescription`, `create_job_from_dict`),
   `asimov/priors.py`, `asimov/monitor_states.py`, and `asimov/vocabulary.yaml`.

5. **Confirm or dismiss every lint candidate.** Open the line and decide.
   Common false positives: reads from a local *copy* the linter didn't
   recognise; hook-provided dicts that aren't the ledger; `print` for dry-run
   output. Each dismissal gets a one-line reason.

6. **Hunt for reinvented wheels** (this is where the linter can't help). For
   every method and helper the plugin defines, ask *"does core already do
   this?"* and grep core for it: resource mapping, rundir handling, asset
   passing, prior conversion, config rendering, executable lookup, retry
   logic, status handling, logging, error types. If core does it, it's a
   finding under the matching CORE/SCHED rule. If three or more plugins
   carry the same workaround, it's an AP-CORE-011 SMELL with a proposed
   core feature.

7. **Apply the vocabulary test to every pipeline-namespaced key** in code,
   template and blueprints: *would another pipeline need this number to run
   the same analysis?* If yes, it's AP-LEDGER-001, even if the linter didn't
   match it (synonym lists are not exhaustive). Also check that per-detector
   values are handled as per-detector (AP-LEDGER-008), and that scientific
   quantities aren't silently defaulted (AP-LEDGER-009).

8. **Check the non-lint rules** in `references/rules.md` one by one (SCHED-004/005/006,
   LEDGER-008/009/010, CORE-002/009/010/012/013, TMPL-001/004, BP-002,
   PKG-006, NORM-001/002). Record which ones you checked.

9. **Write the outputs** described in `references/output.md`. Rank findings
   BLOCKER, then MUST-FIX, then SMELL, then NIT. Every BLOCKER cites the
   plugin line *and* the core symbol or vocabulary term it duplicates.

## Tone

- Be direct. State what is wrong, what core already provides, and the fix.
  Don't pad with praise, and don't hedge a finding you've verified.
- Be specific. Give `file:line`, the offending code, the core symbol, and the
  concrete replacement.
- Don't accept "the builder skill said so" or "the sibling plugin does it"
  as justification. The authority order is in `references/rules.md`.
- Keep the plugin's fault separate from core's: a SMELL points at the core
  change that would remove the workaround.
- Review only. Don't edit the plugin's code; the session that owns the
  plugin applies the fixes.
