# Asimov plugin review rules

Every finding in a review cites one of these rule IDs. Rules marked
**[lint]** are detected (as candidates) by `scripts/lint_plugin.py`; the
rest need reading the code. A lint hit is a *candidate*: confirm it against
the code before reporting it, and dismiss it (saying why) if it is a false
positive.

## Severity

| Severity | Meaning | Merge? |
|---|---|---|
| **BLOCKER** | Reinvents a core asimov feature, or duplicates a quantity that already has a standard ledger name. The plugin will diverge from the ecosystem. | No |
| **MUST-FIX** | Breaks an ecosystem norm, or will fail at runtime in a case the plugin doesn't handle. | No |
| **SMELL** | The plugin works around a *gap in asimov core*. Not the plugin's fault, but it must be tracked upstream. Report the upstream fix, not just the workaround. | Yes, with an upstream issue linked in the code |
| **NIT** | Style, naming, docs. | Yes |

A BLOCKER needs **two citations**: the plugin line, and the core symbol or
vocabulary term it duplicates (`asimov/scheduler.py:JobDescription`,
`psds`). If you can't find the core counterpart, it isn't a BLOCKER: ask a
question instead.

Order of authority when sources disagree: **asimov core code on the target
branch > `asimov vocabulary` > asimov docs > the `asimov-plugin` builder skill
> other plugins**. Other plugins are evidence of common practice, not of
correct practice: asimov-jim, asimov-pycbc and the plugin template share
several of the anti-patterns below.

---

## SCHED: Job submission and monitoring

Core provides `Pipeline.scheduler` (lazily configured HTCondor, Slurm or local
from `asimov.conf`), `asimov.scheduler.JobDescription`,
`asimov.scheduler_utils.create_job_from_dict()`, `Scheduler.submit/submit_dag/
query/delete`, and the monitor state machine (`asimov.monitor_states`).

- **AP-SCHED-001 BLOCKER [lint]**: imports `htcondor`, `htcondor2`, `classad` or
  `pyslurm`, or shells out to `condor_submit[_dag]`, `condor_q`, `condor_rm`,
  `sbatch`, `squeue`, `scancel` or `sacct`.
  Fix: build a `JobDescription` (or use `create_job_from_dict`) and call
  `self.scheduler.submit(job)` (or `self.scheduler.submit_dag(dag_file, batch_name=...)`
  for a real multi-stage DAG).
- **AP-SCHED-002 BLOCKER [lint]**: instantiates `HTCondor()`, `Slurm()`,
  `LocalProcessScheduler()` or calls `get_scheduler()`. Importing a scheduler
  class only for an `isinstance(self.scheduler, Slurm)` branch is a SMELL
  (see AP-SCHED-006), not a BLOCKER.
- **AP-SCHED-003 BLOCKER [lint]**: overrides the `Pipeline.scheduler` property.
- **AP-SCHED-004 MUST-FIX**: `submit_dag` does not convert scheduler failures
  (`FileNotFoundError`, `RuntimeError`, ...) into `PipelineException`, or it
  swallows them.
- **AP-SCHED-005 BLOCKER**: polls job status itself (loops, sleeps, parses
  scheduler output) instead of relying on the monitor loop calling
  `detect_completion()` and the state handlers.
- **AP-SCHED-006 SMELL [lint]**: branches on scheduler type to express a resource
  (such as GPUs) that `JobDescription` can't express generically. Acceptable
  only with a comment linking the upstream issue (currently
  etive-io/asimov#161) and with no scheduler-specific key leaking into the
  other scheduler's submit description.
- **AP-SCHED-007 MUST-FIX**: resource requests are hard-coded, or read from
  non-standard ledger keys (e.g. `scheduler: cpus` rather than
  `scheduler: request cpus`). Overlaps with AP-LEDGER-003.

## LEDGER: Ledger vocabulary

The canonical vocabulary is `asimov vocabulary` (`asimov/vocabulary.yaml`,
etive-io/asimov#175). **A quantity with the same meaning to more than one
pipeline must use its standard name.** A pipeline namespace (`mypipeline:`)
may only hold quantities that mean nothing to any other pipeline. Apply the
test: *would bilby, RIFT or another pipeline need this number if it ran the
same analysis?*

- **AP-LEDGER-001 BLOCKER [lint]**: code, a template or a blueprint uses a
  pipeline-namespaced key (or an invented top-level key) for a quantity that
  already has a standard name. For example: `mypipeline: data: psd_files`
  duplicates `psds`, `mypipeline: prior` duplicates `priors`, and
  `mypipeline: f_min` duplicates `likelihood: minimum frequency`.
- **AP-LEDGER-002 BLOCKER [lint]**: the plugin's registered vocabulary
  (`asimov.vocabulary` entry point) defines a term that duplicates a core term,
  or tries to redefine one (`asimov vocabulary lint`).
- **AP-LEDGER-003 MUST-FIX [lint]**: reads a key that isn't in the vocabulary
  and isn't under the pipeline's own namespace, e.g. a typo or an invented key
  inside a standard section such as `scheduler: cpus`.
- **AP-LEDGER-004 MUST-FIX [lint]**: uses an alias or deprecated location
  (e.g. `quality: minimum frequency`, `likelihood: reference frequency`, top-level
  `approximant`).
- **AP-LEDGER-005 SMELL [lint]**: reads a term owned by a different pipeline
  (e.g. `likelihood: iterations`, which belongs to BayesWave). Either the term
  is really generic (propose promoting it in core) or the plugin shouldn't
  read it.
- **AP-LEDGER-006 MUST-FIX [lint]**: reads a pipeline-namespaced block but does
  not register its terms via the `asimov.vocabulary` entry point, so
  `asimov vocabulary check` can't validate users' blueprints.
- **AP-LEDGER-007 MUST-FIX [lint]**: writes plugin state or derived output into
  `production.meta`, such as a rendered config, a converted prior, counters or
  flags. The ledger holds analysis *inputs* and asimov-managed state. For
  rendered config, the template receives `pipeline`, so call
  `{{ pipeline.render_config() }}` (or similar) from the template instead of
  stashing text in the ledger. Retry counters such as `resurrections` are a
  SMELL (core has no retry-count field yet), so propose one upstream.
- **AP-LEDGER-008 MUST-FIX**: treats a per-detector value (`per ifo: true` in
  the vocabulary, e.g. `likelihood: minimum frequency`) as a scalar, or
  collapses it without saying how (min/max) in the code and README.
- **AP-LEDGER-009 MUST-FIX**: applies defaults silently for scientifically
  significant quantities (sample rate, frequencies, approximant, priors) that
  the ledger should supply. A missing value should either raise
  `PipelineException` or be logged clearly. Defaults are fine for purely
  technical knobs.
- **AP-LEDGER-010 BLOCKER**: silently remaps parameter names or physical
  conventions between the asimov prior blueprint and the wrapped code (e.g.
  spin frames, mass parameterisations) without an exact, tested mapping.

## CORE: Reusing core features

- **AP-CORE-001 MUST-FIX [lint]**: resolves the run directory itself (e.g.
  `config.get("general", "rundir_default")` joined with event/production
  names). `Analysis.rundir` already derives it from the subject's
  `working directory`. Read `self.production.rundir` and raise
  `PipelineException` if it's `None`.
- **AP-CORE-002 BLOCKER**: converts priors anywhere other than a
  `PriorInterface` subclass returned from `get_prior_interface()`, or reads
  `production.meta["priors"]` raw in the pipeline. An "escape hatch" namespace
  (`mypipeline: prior:`) is AP-LEDGER-001. Unsupported prior types should
  raise from `convert()`.
- **AP-CORE-003 BLOCKER / MUST-FIX [lint]**: chains downstream work
  (PESummary, another pipeline) from inside the plugin, whether by importing
  it, calling `entry_points`/`known_pipelines`, or submitting it. It must be a
  separate analysis with `needs:`. (BLOCKER if it submits; MUST-FIX if it only
  looks the pipeline up.)
- **AP-CORE-004 BLOCKER / SMELL [lint]**: `collect_assets()` returns a
  non-standard name for a standard asset (`posterior` for `samples`,
  `psd_files` for `psds`), which breaks `needs:` consumers such as
  `Analysis._collect_psds`. This is a BLOCKER. A genuinely new asset is a
  SMELL until it is registered in the plugin vocabulary.
- **AP-CORE-005 MUST-FIX [lint]**: calls `make_config()` from `build_dag`/
  `submit_dag`, or otherwise merges the separate `asimov manage build` and
  `asimov manage submit` steps.
- **AP-CORE-006 MUST-FIX [lint]**: reads `meta["psds"]`, `meta["xml psds"]` or
  `meta["rundir"]` directly instead of `production.psds`, `production.xml_psds`
  or `production.rundir`, skipping core's resolution logic (e.g. PSDs from
  `needs`).
- **AP-CORE-007 MUST-FIX [lint]**: writes the ledger (`ledger.update_event`,
  `event.update_data`, `ledger.save`) from inside pipeline hooks. The CLI and
  monitor handle persistence.
- **AP-CORE-008 MUST-FIX [lint]**: overrides `while_running`, invents
  production statuses, or manages state transitions by hand. Custom states go
  through `asimov.monitor_states.register_state` / `asimov.custom_states`.
- **AP-CORE-009 MUST-FIX**: `build_dag`/`submit_dag` don't honour `dryrun`
  (any filesystem, scheduler or ledger side effect in dryrun mode).
- **AP-CORE-010 MUST-FIX**: `detect_completion()` keys on a file the wrapped
  code writes *before* it has finished (e.g. samples written before final
  diagnostics). Check the wrapped code's write order.
- **AP-CORE-011 SMELL**: code copied from sibling plugins to work around the
  same core gap (e.g. `_executable()` resolution with `shutil.which`, retry
  counters). Three copies is a core feature request: name it.
- **AP-CORE-012 MUST-FIX**: `after_completion()` doesn't call
  `super().after_completion()`, or does more than mark the analysis finished.
- **AP-CORE-013 MUST-FIX**: `resurrect()` has no retry cap, or resubmits without
  handling the wrapped code's checkpoint/resume semantics.

## TMPL: Bundled config template

Templates are rendered by `Analysis.make_config` with `production`,
`analysis`, `pipeline` and `config` in scope.

- **AP-TMPL-001 MUST-FIX**: the template isn't bundled as package data, isn't
  exposed through `config_template`, or is located with a path relative to
  the current working directory.
- **AP-TMPL-002 MUST-FIX [lint]**: chained `[...]` indexing into the ledger with
  no guard. This raises when an intermediate key is missing. Use `.get()`
  chains or `{% if %}` guards. (Required keys that should fail loudly are an
  exception, but say so in a comment.)
- **AP-TMPL-003 MUST-FIX [lint]**: hard-codes values the ledger supplies, such
  as accounting group, channels, frame types, absolute paths, sample rate or
  frequencies.
- **AP-TMPL-004 MUST-FIX**: builds a type-sensitive format (TOML, JSON, YAML)
  as templated text, which renders Python `True`/`None` into invalid syntax.
  Build a dict and serialise it instead, without violating AP-LEDGER-007.
- **AP-TMPL-005**: every ledger key the template reads is subject to the
  LEDGER rules (the linter checks them).

## BP: Blueprints shipped with the plugin (examples, tests, docs)

- **AP-BP-001 MUST-FIX [lint]**: a blueprint has unknown or type findings from
  `asimov vocabulary check --pipeline <name>`. (Duplicates are
  AP-LEDGER-001, and deprecated or alias spellings are AP-LEDGER-004.)
- **AP-BP-002 MUST-FIX**: example blueprints set pipeline-namespaced values
  for standard quantities, or omit `needs:` where the plugin expects upstream
  assets (data, PSDs).
- **AP-BP-003 NIT**: examples don't cover the plugin's namespaced settings, so
  users have no reference for them.

## PKG: Packaging and repository norms

- **AP-PKG-000 BLOCKER [lint]**: a Python file doesn't parse.
- **AP-PKG-001 BLOCKER [lint]**: no `asimov.pipelines` entry point.
- **AP-PKG-002 MUST-FIX [lint]**: the entry point name isn't the lower-case
  pipeline name, or `Pipeline.name` and the `__init__` pipeline-mismatch check
  disagree with it.
- **AP-PKG-003 MUST-FIX [lint]**: doesn't depend on `asimov`, pins an old
  asimov, or depends on the wrapped analysis code (which should already be in
  the runtime environment).
- **AP-PKG-004 MUST-FIX [lint]**: no unit tests; or tests that talk to a real
  scheduler or real `asimov.conf` instead of mocks.
- **AP-PKG-005 NIT [lint]**: no CI workflow. (No end-to-end HTCondor job once
  the plugin wraps a real executable is MUST-FIX.)
- **AP-PKG-006 MUST-FIX**: README doesn't document the `pipeline:` name, the
  namespaced settings schema, the `needs:` pattern for inputs and
  post-processing, and checkpoint/resume behaviour.

## NORM: Code norms

- **AP-NORM-001 MUST-FIX**: raises bare exceptions or `sys.exit` instead of
  `PipelineException(message, production=...)`.
- **AP-NORM-002 MUST-FIX**: public hooks lack numpy-style docstrings.
- **AP-NORM-003 NIT**: unused leftovers from the template (`hooks.py`,
  `myplugin` names).
- **AP-NORM-004 NIT [lint]**: `print()` instead of `self.logger` (printing the
  dry-run plan is fine).

## TOOL: Reviewer tooling

- **AP-TOOL-001 INFO [lint]**: the vocabulary wasn't available, so the
  LEDGER/BP lint checks were skipped. Rerun with `--asimov-src` pointing at an
  asimov checkout that includes `asimov/vocabulary.yaml`, and say in the
  report that those checks were done by hand.
