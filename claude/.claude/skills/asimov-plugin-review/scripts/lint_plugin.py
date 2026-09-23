#!/usr/bin/env python3
"""
Deterministic pre-checks for an asimov pipeline plugin.

This finds the mechanical problems (raw scheduler calls, invented ledger
keys, reimplemented core features, packaging gaps) so that the reviewing
agent can spend its effort on judgement.  Every finding carries a rule ID
from ``references/rules.md``, a file and line, and the evidence that
triggered it.  Findings are *candidates*: the reviewer confirms or
dismisses each one.

Ledger keys are checked against asimov's own vocabulary
(``asimov.vocabulary``, etive-io/asimov#175).  It is found, in order, from
``--asimov-src``, from an importable ``asimov`` package, or not at all (in
which case the vocabulary checks are skipped and a finding says so).

Usage::

    python lint_plugin.py PATH/TO/PLUGIN [--asimov-src PATH/TO/ASIMOV] [--json]
"""

import argparse
import ast
import glob
import importlib.util
import json
import os
import re
import sys

try:
    import tomllib
except ImportError:  # pragma: no cover - python < 3.11
    tomllib = None

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None


RAW_SCHEDULER_MODULES = {"htcondor", "htcondor2", "classad", "classad2", "pyslurm"}
RAW_SCHEDULER_COMMANDS = {
    "condor_submit",
    "condor_submit_dag",
    "condor_q",
    "condor_rm",
    "condor_history",
    "condor_release",
    "condor_hold",
    "sbatch",
    "squeue",
    "scancel",
    "sacct",
}
SCHEDULER_CLASSES = {"HTCondor", "Slurm", "LocalProcessScheduler", "get_scheduler"}
SUBPROCESS_CALLS = {"run", "call", "check_call", "check_output", "Popen", "system"}
TEMPLATE_SUFFIXES = (".ini", ".toml", ".yaml", ".yml", ".json", ".liquid", ".j2", ".cfg")
# Attributes of Analysis which core fills in; reading the raw meta key
# instead skips the resolution logic behind them.
CORE_ATTRIBUTES = {
    ("psds",): "production.psds (Analysis._collect_psds also pulls PSDs from `needs`)",
    ("xml psds",): "production.xml_psds",
    ("rundir",): "production.rundir (Analysis.rundir)",
}


class Finding(dict):
    def __init__(self, rule, severity, file, line, message, evidence="", suggestion=None):
        super().__init__(
            rule=rule,
            severity=severity,
            file=file,
            line=line,
            message=message,
            evidence=evidence.strip()[:200],
        )
        if suggestion:
            self["suggestion"] = suggestion


# ----------------------------------------------------------------------
# Vocabulary
# ----------------------------------------------------------------------


def load_vocabulary(asimov_src=None):
    """Return an asimov Vocabulary, or None if one cannot be found."""
    if asimov_src:
        module_path = os.path.join(asimov_src, "asimov", "vocabulary.py")
        data_path = os.path.join(asimov_src, "asimov", "vocabulary.yaml")
        if os.path.exists(module_path) and os.path.exists(data_path):
            spec = importlib.util.spec_from_file_location("_asimov_vocabulary", module_path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module.Vocabulary.from_file(data_path)
        return None
    try:
        from asimov.vocabulary import Vocabulary
    except Exception:
        return None
    return Vocabulary.core()


# ----------------------------------------------------------------------
# Python checks
# ----------------------------------------------------------------------


def _string(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _call_name(node):
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _dotted(node):
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


class MetaPathVisitor(ast.NodeVisitor):
    """
    Collect ledger paths read from ``*.meta`` with ``[...]`` or ``.get(...)``,
    following simple local aliases such as ``data = meta.get("data") or {}``.
    """

    def __init__(self):
        self.paths = []  # (path tuple, line)
        self.writes = []  # (path tuple, line)
        self.aliases = {}
        # Local names bound to a *copy* of a ledger value; writing to them
        # does not touch the ledger.
        self.copies = set()

    def visit_FunctionDef(self, node):
        saved = dict(self.aliases), set(self.copies)
        self.aliases, self.copies = {}, set()
        self.generic_visit(node)
        self.aliases, self.copies = saved

    visit_AsyncFunctionDef = visit_FunctionDef

    def resolve(self, node):
        """Return the meta path an expression refers to, or None."""
        if isinstance(node, ast.BoolOp):
            return self.resolve(node.values[0])
        if isinstance(node, ast.Call) and _call_name(node) in {"dict", "list"} and node.args:
            return self.resolve(node.args[0])
        if isinstance(node, ast.Attribute) and node.attr == "meta":
            return ()
        if isinstance(node, ast.Name) and node.id in self.aliases:
            return self.aliases[node.id]
        if isinstance(node, ast.Name) and node.id == "meta":
            return ()
        if isinstance(node, ast.Subscript):
            base = self.resolve(node.value)
            key = _string(node.slice)
            if base is not None and key is not None:
                return base + (key,)
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in {"get", "setdefault", "pop"}
            and node.args
        ):
            base = self.resolve(node.func.value)
            key = _string(node.args[0])
            if base is not None and key is not None:
                return base + (key,)
        return None

    @staticmethod
    def _is_copy(node):
        if isinstance(node, ast.BoolOp):
            node = node.values[0]
        return isinstance(node, ast.Call) and _call_name(node) in {
            "dict", "list", "copy", "deepcopy",
        }

    def visit_Assign(self, node):
        path = self.resolve(node.value)
        for target in node.targets:
            if isinstance(target, ast.Name):
                if path is not None:
                    self.aliases[target.id] = path
                if self._is_copy(node.value):
                    self.copies.add(target.id)
                else:
                    self.copies.discard(target.id)
        self.generic_visit(node)

    def _base_name(self, node):
        while isinstance(node, (ast.Subscript, ast.Attribute, ast.Call)):
            node = node.value if not isinstance(node, ast.Call) else node.func
        return node.id if isinstance(node, ast.Name) else None

    def _record(self, node):
        path = self.resolve(node)
        if path:
            self.paths.append((path, node.lineno))

    def visit_Subscript(self, node):
        if isinstance(node.ctx, ast.Store):
            path = self.resolve(node)
            if path and self._base_name(node) not in self.copies:
                self.writes.append((path, node.lineno))
        else:
            self._record(node)
        self.generic_visit(node)

    def visit_Call(self, node):
        if isinstance(node.func, ast.Attribute) and node.func.attr in {"get", "setdefault", "pop"}:
            self._record(node)
        # Mutating dict methods change the ledger just as item assignment
        # does: setdefault/pop at the keyed path, update/clear at the
        # container's path.
        if isinstance(node.func, ast.Attribute) and self._base_name(node.func) not in self.copies:
            if node.func.attr in {"setdefault", "pop"}:
                path = self.resolve(node)
            elif node.func.attr in {"update", "clear", "popitem"}:
                path = self.resolve(node.func.value)
            else:
                path = None
            if path:
                self.writes.append((path, node.lineno))
        self.generic_visit(node)


def _deepest(paths):
    """Drop paths which are prefixes of another path read on the same line."""
    unique = sorted(set(paths))
    result = []
    for path, line in unique:
        if any(
            other_line == line and len(other) > len(path) and other[: len(path)] == path
            for other, other_line in unique
        ):
            continue
        result.append((path, line))
    return result


def check_python(path, relative, source, findings, pipeline_names):
    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError as error:
        findings.append(
            Finding("AP-PKG-000", "BLOCKER", relative, error.lineno or 0, "File does not parse.")
        )
        return [], {}, []
    lines = source.splitlines()

    def line_of(node):
        return lines[node.lineno - 1] if 0 < node.lineno <= len(lines) else ""

    asset_names = {}
    for node in ast.walk(tree):
        # Raw scheduler libraries.
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            modules = (
                [alias.name for alias in node.names]
                if isinstance(node, ast.Import)
                else [node.module or ""]
            )
            for module in modules:
                if module.split(".")[0] in RAW_SCHEDULER_MODULES:
                    findings.append(
                        Finding(
                            "AP-SCHED-001",
                            "BLOCKER",
                            relative,
                            node.lineno,
                            f"Imports the scheduler library '{module}' directly.",
                            line_of(node),
                            "Build a JobDescription (asimov.scheduler_utils.create_job_from_dict) "
                            "and submit with self.scheduler.submit().",
                        )
                    )
            if isinstance(node, ast.ImportFrom) and node.module == "asimov.scheduler":
                for alias in node.names:
                    if alias.name in SCHEDULER_CLASSES:
                        findings.append(
                            Finding(
                                "AP-SCHED-006",
                                "SMELL",
                                relative,
                                node.lineno,
                                f"Imports asimov.scheduler.{alias.name}; check it is only used "
                                "for isinstance() branching, never instantiated.",
                                line_of(node),
                            )
                        )

        if isinstance(node, ast.Call):
            name = _call_name(node)
            dotted = _dotted(node.func)
            # subprocess / os.system calls to scheduler command-line tools.
            if name in SUBPROCESS_CALLS and (
                dotted.startswith("subprocess") or dotted.startswith("os.") or name == "Popen"
            ):
                text = ast.get_source_segment(source, node) or ""
                for command in RAW_SCHEDULER_COMMANDS:
                    if re.search(rf"['\"]{command}['\"\s]", text):
                        findings.append(
                            Finding(
                                "AP-SCHED-001",
                                "BLOCKER",
                                relative,
                                node.lineno,
                                f"Shells out to '{command}' instead of using the scheduler "
                                "abstraction.",
                                line_of(node),
                                "Use self.scheduler.submit()/query()/delete().",
                            )
                        )
                        break
            # Instantiating a scheduler instead of using Pipeline.scheduler.
            if name in SCHEDULER_CLASSES and isinstance(node.func, (ast.Name, ast.Attribute)):
                findings.append(
                    Finding(
                        "AP-SCHED-002",
                        "BLOCKER",
                        relative,
                        node.lineno,
                        f"Instantiates a scheduler ({name}) instead of using self.scheduler.",
                        line_of(node),
                        "Use the lazily-configured Pipeline.scheduler property.",
                    )
                )
            # Chaining another pipeline (post-processing) directly.
            if name == "entry_points" or dotted.endswith("known_pipelines.get"):
                findings.append(
                    Finding(
                        "AP-CORE-003",
                        "MUST-FIX",
                        relative,
                        node.lineno,
                        "Looks up another pipeline from inside the plugin; downstream work "
                        "should be a separate analysis with `needs:`.",
                        line_of(node),
                    )
                )
            if name == "print":
                findings.append(
                    Finding(
                        "AP-NORM-004",
                        "NIT",
                        relative,
                        node.lineno,
                        "Uses print(); use self.logger (dryrun output excepted).",
                        line_of(node),
                    )
                )
            if name == "make_config":
                findings.append(
                    Finding(
                        "AP-CORE-005",
                        "MUST-FIX",
                        relative,
                        node.lineno,
                        "Calls make_config() from the plugin; config rendering is the "
                        "separate `asimov manage build` step.",
                        line_of(node),
                    )
                )

        # Reimplementing rundir resolution.
        if isinstance(node, ast.Constant) and node.value == "rundir_default":
            findings.append(
                Finding(
                    "AP-CORE-001",
                    "MUST-FIX",
                    relative,
                    node.lineno,
                    "Resolves the run directory from config rundir_default itself.",
                    line_of(node),
                    "Read self.production.rundir; Analysis.rundir derives it from the "
                    "subject's working directory.",
                )
            )

        # Pipeline overriding the scheduler property or state machinery.
        if isinstance(node, ast.FunctionDef) and node.name in {"scheduler", "while_running"}:
            findings.append(
                Finding(
                    "AP-SCHED-003" if node.name == "scheduler" else "AP-CORE-008",
                    "BLOCKER" if node.name == "scheduler" else "MUST-FIX",
                    relative,
                    node.lineno,
                    f"Overrides Pipeline.{node.name}.",
                    line_of(node),
                )
            )

        # Asset names returned from collect_assets().
        if isinstance(node, ast.FunctionDef) and node.name == "collect_assets":
            for inner in ast.walk(node):
                if isinstance(inner, ast.Dict):
                    for key in inner.keys:
                        if _string(key):
                            asset_names[_string(key)] = inner.lineno
                if isinstance(inner, ast.Subscript) and isinstance(inner.ctx, ast.Store):
                    if _string(inner.slice):
                        asset_names[_string(inner.slice)] = inner.lineno

        # Writing to the ledger directly.
        ledger_writers = {"update_data", "save", "update_event"}
        if isinstance(node, ast.Call) and _call_name(node) in ledger_writers:
            dotted = _dotted(node.func)
            if "ledger" in dotted or dotted.endswith("event.update_data"):
                findings.append(
                    Finding(
                        "AP-CORE-007",
                        "MUST-FIX",
                        relative,
                        node.lineno,
                        "Writes the ledger from inside the plugin.",
                        line_of(node),
                    )
                )

    visitor = MetaPathVisitor()
    visitor.visit(tree)

    def with_source(pairs):
        return [(path, line, lines[line - 1] if line <= len(lines) else "") for path, line in pairs]

    return with_source(_deepest(visitor.paths)), asset_names, with_source(visitor.writes)


# ----------------------------------------------------------------------
# Template checks
# ----------------------------------------------------------------------

LIQUID_BLOCK = re.compile(r"({{.*?}}|{%.*?%})", re.S)
ASSIGN = re.compile(r"assign\s+(\w+)\s*=\s*(.+?)\s*-?%}", re.S)
SET = re.compile(r"set\s+(\w+)\s*=\s*(.+?)\s*-?%}", re.S)
ACCESS = re.compile(
    r"(production\.meta|analysis\.meta|meta|\b\w+\b)"
    r"((?:\[\s*['\"][^'\"]+['\"]\s*\]|\.get\(\s*['\"][^'\"]+['\"][^)]*\))+)"
)
KEY = re.compile(r"['\"]([^'\"]+)['\"]")


def check_template(path, relative, text, findings):
    """Return the ledger paths a Liquid/Jinja template reads."""
    aliases = {"meta": ()}
    paths = []

    def resolve(expression):
        match = ACCESS.search(expression)
        if not match:
            return None
        base, chain = match.group(1), match.group(2)
        if base in ("production.meta", "analysis.meta"):
            prefix = ()
        elif base in aliases:
            prefix = aliases[base]
        else:
            return None
        keys = tuple(KEY.findall(re.sub(r",[^)]*\)", ")", chain)))
        return prefix + keys, chain

    for block in LIQUID_BLOCK.finditer(text):
        content = block.group(0)
        line = text.count("\n", 0, block.start()) + 1
        assignment = ASSIGN.search(content) or SET.search(content)
        if assignment:
            resolved = resolve(assignment.group(2))
            if resolved is not None:
                aliases[assignment.group(1)] = resolved[0]
        for match in ACCESS.finditer(content):
            resolved = resolve(match.group(0))
            if resolved is None or not resolved[0]:
                continue
            path_keys, chain = resolved
            paths.append((path_keys, line, content))
            depth = chain.count("[")
            guarded = ".get(" in chain or "contains" in content or " if " in content
            if depth >= 2 and not guarded:
                findings.append(
                    Finding(
                        "AP-TMPL-002",
                        "MUST-FIX",
                        relative,
                        line,
                        "Chained [] indexing into the ledger raises if an intermediate key "
                        "is missing; guard it or use .get() chains.",
                        content,
                    )
                )
    # Hard-coded values which belong in the ledger.
    for number, raw in enumerate(text.splitlines(), start=1):
        if LIQUID_BLOCK.search(raw):
            continue
        if re.search(r"(accounting[-_ ]group|channel|frame[-_ ]?type)\s*=\s*\S", raw, re.I):
            findings.append(
                Finding(
                    "AP-TMPL-003",
                    "MUST-FIX",
                    relative,
                    number,
                    "Hard-codes a value the ledger supplies.",
                    raw,
                )
            )
        if re.search(r"=\s*/(home|opt|cvmfs|scratch|data)/", raw):
            findings.append(
                Finding(
                    "AP-TMPL-003",
                    "MUST-FIX",
                    relative,
                    number,
                    "Hard-codes an absolute path.",
                    raw,
                )
            )
    return paths


# ----------------------------------------------------------------------
# Vocabulary cross-checks
# ----------------------------------------------------------------------

LEDGER_RULES = {
    "duplicate": ("BLOCKER", "AP-LEDGER-001"),
    "unknown": ("MUST-FIX", "AP-LEDGER-003"),
    "alias": ("MUST-FIX", "AP-LEDGER-004"),
    "deprecated": ("MUST-FIX", "AP-LEDGER-004"),
    "foreign": ("SMELL", "AP-LEDGER-005"),
    "type": ("MUST-FIX", "AP-LEDGER-003"),
}


def check_writes(vocabulary, writes, relative, pipeline_names, findings):
    """Report ledger keys the plugin writes, other than standard ones."""
    reported = set()
    for path, line, evidence in writes:
        if path in reported:
            continue
        reported.add(path)
        term = vocabulary.lookup(path) if vocabulary is not None else None
        if term is not None and not term.deprecated:
            continue
        findings.append(
            Finding(
                "AP-LEDGER-007",
                "MUST-FIX",
                relative,
                line,
                f"Writes plugin state or derived output into the ledger at "
                f"meta{list(path)}.",
                evidence,
                "The ledger holds analysis inputs; keep derived values out of it "
                "(e.g. render config via `{{ pipeline.<method>() }}` in the template), "
                "or register the key in the plugin vocabulary if it must persist.",
            )
        )


def check_paths(
    vocabulary, paths, relative, pipeline_names, findings, rule_prefix, written=frozenset()
):
    """
    Check ledger paths read by code or templates against the vocabulary.

    Paths the plugin itself writes are skipped here: they are reported once,
    at the write, by :func:`check_writes`.
    """
    for path, line, evidence in paths:
        if any(path[: len(w)] == w for w in written):
            continue
        if path in CORE_ATTRIBUTES:
            findings.append(
                Finding(
                    "AP-CORE-006",
                    "MUST-FIX",
                    relative,
                    line,
                    f"Reads meta{list(path)} directly.",
                    evidence,
                    f"Use {CORE_ATTRIBUTES[path]}.",
                )
            )
            continue
        if vocabulary is None:
            continue
        document = {}
        cursor = document
        for key in path[:-1]:
            cursor = cursor.setdefault(key, {})
        cursor[path[-1]] = None
        pipeline = (
            path[0] if path[0].lower() in pipeline_names else next(iter(pipeline_names), None)
        )
        for result in vocabulary.check(document, pipeline=pipeline):
            if result.kind == "duplicate" and result.path != path:
                # An intermediate section which mirrors a core section
                # (e.g. `mypipeline: data:`); the leaf is what matters.
                continue
            if result.kind == "duplicate":
                target = vocabulary.lookup(result.suggestion or "")
                if target is not None and target.children:
                    continue
            severity, rule = LEDGER_RULES[result.kind]
            findings.append(
                Finding(
                    rule,
                    severity,
                    relative,
                    line,
                    f"[{rule_prefix}] {result.message}",
                    evidence,
                    result.suggestion,
                )
            )


def check_blueprints(vocabulary, files, root, pipeline_names, findings):
    for path in files:
        relative = os.path.relpath(path, root)
        try:
            with open(path) as handle:
                documents = list(yaml.safe_load_all(handle))
        except Exception:
            continue
        for document in documents:
            if not isinstance(document, dict) or "kind" not in document:
                continue
            pipeline = document.get("pipeline") or next(iter(pipeline_names), None)
            for result in vocabulary.check(document, pipeline=pipeline):
                severity, rule = LEDGER_RULES[result.kind]
                if result.kind in {"unknown", "type"}:
                    rule = "AP-BP-001"
                findings.append(
                    Finding(
                        rule,
                        severity,
                        relative,
                        0,
                        f"[blueprint] {result.message}",
                        result.dotted,
                        result.suggestion,
                    )
                )


def check_assets(vocabulary, asset_names, relative, findings):
    if vocabulary is None:
        return
    for name, line in asset_names.items():
        if name in vocabulary.assets:
            continue
        standard = vocabulary.suggest_asset(name)
        if standard is not None:
            findings.append(
                Finding(
                    "AP-CORE-004",
                    "BLOCKER",
                    relative,
                    line,
                    f"collect_assets() returns '{name}', which downstream analyses look "
                    f"for as '{standard.name}'.",
                    name,
                    standard.name,
                )
            )
        else:
            findings.append(
                Finding(
                    "AP-CORE-004",
                    "SMELL",
                    relative,
                    line,
                    f"collect_assets() returns a non-standard asset '{name}'; register it "
                    "in the plugin vocabulary if downstream analyses should use it.",
                    name,
                )
            )


# ----------------------------------------------------------------------
# Packaging
# ----------------------------------------------------------------------


def check_packaging(root, findings):
    """Return (pipeline names, package directories)."""
    pyproject = os.path.join(root, "pyproject.toml")
    if not os.path.exists(pyproject):
        findings.append(
            Finding("AP-PKG-001", "MUST-FIX", "pyproject.toml", 0, "No pyproject.toml.")
        )
        return set(), []
    if tomllib is None:
        return set(), []
    with open(pyproject, "rb") as handle:
        data = tomllib.load(handle)
    project = data.get("project", {})
    entry_points = project.get("entry-points", {})
    pipelines = entry_points.get("asimov.pipelines", {})
    if not pipelines:
        findings.append(
            Finding(
                "AP-PKG-001",
                "BLOCKER",
                "pyproject.toml",
                0,
                "No [project.entry-points.\"asimov.pipelines\"] entry; asimov cannot "
                "discover the pipeline.",
            )
        )
    for name in pipelines:
        if name != name.lower():
            findings.append(
                Finding(
                    "AP-PKG-002",
                    "MUST-FIX",
                    "pyproject.toml",
                    0,
                    f"Pipeline entry point '{name}' is not lower case; ledgers match "
                    "`pipeline:` against it.",
                )
            )
    dependencies = " ".join(project.get("dependencies", []))
    if "asimov" not in dependencies:
        findings.append(
            Finding("AP-PKG-003", "MUST-FIX", "pyproject.toml", 0, "Does not depend on asimov.")
        )
    has_vocabulary = "asimov.vocabulary" in entry_points
    packages = sorted(
        {
            os.path.dirname(path)
            for path in glob.glob(os.path.join(root, "*", "__init__.py"))
            if not os.path.basename(os.path.dirname(path)).startswith(("test", "."))
        }
    )
    if not glob.glob(os.path.join(root, "tests", "test_*.py")):
        findings.append(
            Finding("AP-PKG-004", "MUST-FIX", "tests/", 0, "No tests/test_*.py.")
        )
    if not glob.glob(os.path.join(root, ".github", "workflows", "*.y*ml")):
        findings.append(
            Finding("AP-PKG-005", "NIT", ".github/workflows/", 0, "No CI workflow.")
        )
    return {name.lower() for name in pipelines}, packages, has_vocabulary


# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------


SEVERITY_ORDER = {"BLOCKER": 0, "MUST-FIX": 1, "SMELL": 2, "NIT": 3, "INFO": 4}


def lint(root, asimov_src=None):
    root = os.path.abspath(root)
    findings = []
    result = check_packaging(root, findings)
    if len(result) == 2:
        pipeline_names, packages, has_vocabulary = result[0], result[1], False
    else:
        pipeline_names, packages, has_vocabulary = result

    vocabulary = load_vocabulary(asimov_src)
    if vocabulary is None:
        findings.append(
            Finding(
                "AP-TOOL-001",
                "INFO",
                "",
                0,
                "asimov.vocabulary is unavailable (install asimov with etive-io/asimov#175 "
                "or pass --asimov-src); ledger-vocabulary checks were skipped.",
            )
        )
    else:
        # Merge the plugin's own vocabulary so its registered terms are known.
        for package in packages:
            own = os.path.join(package, "vocabulary.yaml")
            if os.path.exists(own) and yaml is not None:
                with open(own) as handle:
                    owner = next(iter(pipeline_names), os.path.basename(package))
                    vocabulary.merge(yaml.safe_load(handle), owner=owner)
                    vocabulary.plugins.append(owner)
        for duplicate in vocabulary.duplicates():
            findings.append(
                Finding(
                    "AP-LEDGER-002",
                    "BLOCKER",
                    "vocabulary.yaml",
                    0,
                    duplicate.message,
                    duplicate.dotted,
                    duplicate.suggestion,
                )
            )

    namespaced_python = False
    written = set()
    python_files = [
        path
        for package in packages
        for path in sorted(glob.glob(os.path.join(package, "**", "*.py"), recursive=True))
    ]
    # Collect writes first so that templates reading plugin-written keys are
    # attributed to the write.
    for path in python_files:
        with open(path) as handle:
            try:
                visitor = MetaPathVisitor()
                visitor.visit(ast.parse(handle.read()))
                written.update(p for p, _ in visitor.writes)
            except SyntaxError:
                pass
    for package in packages:
        for path in sorted(glob.glob(os.path.join(package, "**", "*.py"), recursive=True)):
            relative = os.path.relpath(path, root)
            with open(path) as handle:
                source = handle.read()
            meta_paths, asset_names, writes = check_python(
                path, relative, source, findings, pipeline_names
            )
            written.update(p for p, _, _ in writes)
            check_writes(vocabulary, writes, relative, pipeline_names, findings)
            if any(p[0][0].lower() in pipeline_names for p in meta_paths if p[0]):
                namespaced_python = True
            check_paths(
                vocabulary, meta_paths, relative, pipeline_names, findings, "python", written
            )
            check_assets(vocabulary, asset_names, relative, findings)
        for path in sorted(glob.glob(os.path.join(package, "**", "*"), recursive=True)):
            if not path.endswith(TEMPLATE_SUFFIXES) or os.path.basename(path) == "vocabulary.yaml":
                continue
            relative = os.path.relpath(path, root)
            with open(path) as handle:
                text = handle.read()
            if "{{" not in text and "{%" not in text:
                continue
            paths = check_template(path, relative, text, findings)
            if any(p[0][0].lower() in pipeline_names for p in paths if p[0]):
                namespaced_python = True
            check_paths(
                vocabulary, paths, relative, pipeline_names, findings, "template", written
            )

    if namespaced_python and not has_vocabulary:
        findings.append(
            Finding(
                "AP-LEDGER-006",
                "MUST-FIX",
                "pyproject.toml",
                0,
                "The plugin reads a pipeline-namespaced ledger block but does not register "
                "its terms through the `asimov.vocabulary` entry point.",
            )
        )

    if vocabulary is not None and yaml is not None:
        candidates = [
            path
            for pattern in ("**/*.yaml", "**/*.yml")
            for path in glob.glob(os.path.join(root, pattern), recursive=True)
            if "/.git/" not in path
            and "/.github/" not in path
            and os.path.basename(path) != "vocabulary.yaml"
        ]
        check_blueprints(vocabulary, sorted(candidates), root, pipeline_names, findings)

    # De-duplicate and sort.
    seen = set()
    unique = []
    for finding in findings:
        key = (finding["rule"], finding["file"], finding["line"], finding.get("suggestion"))
        if key in seen:
            continue
        seen.add(key)
        unique.append(finding)
    unique.sort(key=lambda f: (SEVERITY_ORDER.get(f["severity"], 9), f["file"], f["line"]))
    return {
        "plugin": root,
        "pipelines": sorted(pipeline_names),
        "vocabulary": vocabulary is not None,
        "findings": unique,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("plugin", help="Path to the plugin repository.")
    parser.add_argument("--asimov-src", help="Path to an asimov checkout.")
    parser.add_argument("--json", action="store_true", help="Emit JSON.")
    args = parser.parse_args(argv)
    report = lint(args.plugin, args.asimov_src)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        for finding in report["findings"]:
            location = finding["file"]
            if finding["line"]:
                location += f":{finding['line']}"
            print(f"{finding['severity']:8} {finding['rule']:13} {location}  {finding['message']}")
            if finding.get("suggestion"):
                print(f"{'':23}-> {finding['suggestion']}")
    blocking = any(f["severity"] in {"BLOCKER", "MUST-FIX"} for f in report["findings"])
    return 1 if blocking else 0


if __name__ == "__main__":
    sys.exit(main())
