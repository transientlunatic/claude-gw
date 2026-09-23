"""
Tests for lint_plugin.py.

Run with ``python -m pytest`` from this directory, with an asimov that ships
``asimov.vocabulary`` importable (or set ASIMOV_SRC to an asimov checkout).
"""

import os
import textwrap

import pytest

import lint_plugin

ASIMOV_SRC = os.environ.get("ASIMOV_SRC")


def write(root, path, content):
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(textwrap.dedent(content))


@pytest.fixture
def plugin(tmp_path):
    write(
        tmp_path,
        "pyproject.toml",
        """
        [project]
        name = "asimov-bad"
        dependencies = ["asimov>=0.7"]
        [project.entry-points."asimov.pipelines"]
        bad = "asimov_bad:Bad"
        """,
    )
    write(
        tmp_path,
        "asimov_bad/__init__.py",
        """
        import subprocess
        import htcondor
        from asimov.pipeline import Pipeline
        from asimov.scheduler import HTCondor


        class Bad(Pipeline):
            def submit_dag(self, dryrun=False):
                subprocess.run(["condor_submit_dag", "x.dag"])
                scheduler = HTCondor()
                psds = self.production.meta["bad"]["psd_files"]
                cpus = self.production.meta["scheduler"]["cpus"]
                kwargs = dict(self.production.meta.get("sampler") or {})
                kwargs["checkpoint"] = "here"
                self.production.meta["bad_rendered"] = "text"

            def collect_assets(self):
                return {"posterior": "samples.h5"}
        """,
    )
    write(
        tmp_path,
        "asimov_bad/configs/bad.ini",
        """
        {%- assign meta = production.meta -%}
        srate = {{ meta['likelihood']['sample rate'] }}
        fmin = {{ meta.get('bad', {}).get('f_min') }}
        accounting_group = ligo.dev.o4.cbc.pe
        """,
    )
    write(
        tmp_path,
        "examples/analysis.yaml",
        """
        kind: analysis
        name: example
        pipeline: bad
        scheduler:
          ncpus: 4
        bad:
          f_ref: 20
        """,
    )
    write(tmp_path, "tests/test_bad.py", "")
    return tmp_path


def rules(report):
    return {(f["rule"], f["file"], f["line"]) for f in report["findings"]}


def by_rule(report, rule):
    return [f for f in report["findings"] if f["rule"] == rule]


def test_scheduler_rules(plugin):
    report = lint_plugin.lint(plugin, ASIMOV_SRC)
    found = rules(report)
    assert ("AP-SCHED-001", "asimov_bad/__init__.py", 3) in found  # import htcondor
    assert ("AP-SCHED-001", "asimov_bad/__init__.py", 10) in found  # condor_submit_dag
    assert ("AP-SCHED-002", "asimov_bad/__init__.py", 11) in found  # HTCondor()


def test_ledger_rules(plugin):
    report = lint_plugin.lint(plugin, ASIMOV_SRC)
    if not report["vocabulary"]:
        pytest.skip("asimov.vocabulary is not available")
    suggestions = {
        (f["rule"], f["file"], f.get("suggestion")) for f in report["findings"]
    }
    assert ("AP-LEDGER-001", "asimov_bad/__init__.py", "psds") in suggestions
    assert (
        "AP-LEDGER-003",
        "asimov_bad/__init__.py",
        "scheduler.request cpus",
    ) in suggestions
    assert (
        "AP-LEDGER-001",
        "asimov_bad/configs/bad.ini",
        "likelihood.minimum frequency",
    ) in suggestions
    assert (
        "AP-LEDGER-001",
        "examples/analysis.yaml",
        "waveform.reference frequency",
    ) in suggestions
    assert ("AP-BP-001", "examples/analysis.yaml", "scheduler.request cpus") in suggestions
    assert ("AP-CORE-004", "asimov_bad/__init__.py", "samples") in suggestions


def test_writes_to_ledger_but_not_to_copies(plugin):
    report = lint_plugin.lint(plugin, ASIMOV_SRC)
    writes = by_rule(report, "AP-LEDGER-007")
    assert [f["line"] for f in writes] == [16]


def test_template_rules(plugin):
    report = lint_plugin.lint(plugin, ASIMOV_SRC)
    found = rules(report)
    assert ("AP-TMPL-002", "asimov_bad/configs/bad.ini", 3) in found
    assert ("AP-TMPL-003", "asimov_bad/configs/bad.ini", 5) in found
    # The guarded .get() chain is not flagged.
    assert ("AP-TMPL-002", "asimov_bad/configs/bad.ini", 4) not in found


def test_packaging(tmp_path):
    write(tmp_path, "pyproject.toml", '[project]\nname = "x"\n')
    report = lint_plugin.lint(tmp_path, ASIMOV_SRC)
    assert by_rule(report, "AP-PKG-001")
    assert by_rule(report, "AP-PKG-003")
    assert by_rule(report, "AP-PKG-004")


def test_missing_vocabulary_is_reported(plugin, tmp_path_factory):
    empty = tmp_path_factory.mktemp("no-asimov")
    report = lint_plugin.lint(plugin, str(empty))
    assert not report["vocabulary"]
    assert by_rule(report, "AP-TOOL-001")
