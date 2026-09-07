"""Reuse V0 isolation; keep original and diagnostic executions separately attributable."""
from __future__ import annotations

import ast
import asyncio
from collections import Counter
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys
import traceback

import ci_driver as base


def write(name, data):
    (base.OUT / name).write_text(json.dumps(data, indent=2, default=str))


class Results:
    def __init__(self):
        self.rows = []
        self.collection = []

    def pytest_collectreport(self, report):
        self.collection.append(dict(nodeid=report.nodeid, outcome=report.outcome, detail=str(report.longrepr) if report.failed else None))

    def pytest_runtest_logreport(self, report):
        self.rows.append(dict(nodeid=report.nodeid, phase=report.when, outcome=report.outcome, duration=report.duration,
                             wasxfail=getattr(report, 'wasxfail', None), detail=str(report.longrepr) if not report.passed else None))

    def pytest_sessionfinish(self, session, exitstatus):
        write(os.environ['DIAG_LABEL'] + '_results.json', dict(label=os.environ['DIAG_LABEL'], variant=os.environ['DIAG_VARIANT'],
              collected=session.testscollected, exit_code=int(exitstatus), phases=dict(Counter(r['phase'] for r in self.rows)),
              call_outcomes=dict(Counter(r['outcome'] for r in self.rows if r['phase']=='call')), results=self.rows, collection=self.collection))


def copied_catalog():
    source = Path('/source/tests/test_slice2a_catalogs_adversarial.py')
    original = source.read_text()
    old = 'monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://ceiba:ceiba@localhost:5432/ceiba_test")'
    new = 'monkeypatch.setenv("DATABASE_URL", __import__("os").environ["TEST_DATABASE_URL"])'
    if original.count(old) != 1:
        raise RuntimeError('Catalog fixture patch precondition changed')
    diagnostic = original.replace(old, new)
    def test_functions(text):
        return {n.name: ast.dump(n, include_attributes=False) for n in ast.parse(text).body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name.startswith('test_') and n.name != 'test_environment'}
    if test_functions(original) != test_functions(diagnostic):
        raise RuntimeError('Diagnostic copy changed functional test AST')
    target = Path('/audit/diagnostic_copies/test_catalogs_diagnostic.py')
    target.parent.mkdir(exist_ok=True)
    target.write_text(diagnostic)
    write('diagnostic_copy_manifest.json', dict(original_path=str(source), copy_path=str(target),
          original_sha256=hashlib.sha256(original.encode()).hexdigest(), diagnostic_sha256=hashlib.sha256(diagnostic.encode()).hexdigest(),
          test_function_ast_unchanged=True, test_functions=len(test_functions(original)), exact_old_line=old, exact_new_line=new,
          reason='Explicitly align app DATABASE_URL and fixture TEST_DATABASE_URL in diagnostic copy only'))
    return str(target)


def run_pytest(label, nodes, variant):
    db = 'audit_diag_' + label.replace('-', '_') + '_test_' + base.NONCE[:10]
    asyncio.run(base.create_database(db))
    env = dict(os.environ, DIAG_LABEL=label, DIAG_VARIANT=variant)
    command = [sys.executable, __file__, '--pytest', db, *nodes]
    result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=1800)
    (base.OUT / (label + '.log')).write_text(result.stdout + result.stderr)
    path = base.OUT / (label + '_results.json')
    summary = json.loads(path.read_text()) if path.exists() else {'collected':0,'missing_results':True}
    return dict(label=label, variant=variant, command=command, exit_code=result.returncode, database=db,
                collected=summary['collected'], outcomes=summary.get('call_outcomes'), phases=summary.get('phases'), missing_results=not path.exists())


def main():
    if len(sys.argv)>1 and sys.argv[1]=='--pytest':
        base.environment(sys.argv[2])
        import pytest
        raise SystemExit(pytest.main([*sys.argv[3:], '-c', '/source/pyproject.toml', '-q', '-p', 'pytest_asyncio.plugin', '-p', 'respx.plugin', '-p', 'diagnostic_plugin',
                                     '-p', 'no:cacheprovider', '--tb=short', '--junitxml=/audit-output/' + os.environ['DIAG_LABEL'] + '.xml'], plugins=[Results()]))
    stage = os.environ['AUDIT_STAGE']
    base.environment('audit_unused_test_' + base.NONCE[:10])
    write('environment.json', dict(python=sys.version, packages={p:importlib.metadata.version(p) for p in ['pytest','pytest-asyncio','SQLAlchemy','asyncpg','alembic','httpx','respx','pydantic','fastapi','ruff']},
          base_sha=os.environ['BASE_SHA'],audit_sha=os.environ['AUDIT_SHA'],stage=stage,network='Docker internal plus unchanged V0 socket guard',providers='SIMULATED'))
    (base.OUT / 'dependency-install.json').write_bytes(Path('/dependency-install.json').read_bytes())
    cases=json.loads(Path('/audit/case_manifest.json').read_text())
    nodes=[c['nodeid'] for c in cases]
    root_nodes=[c['nodeid'] for c in cases if c['historical_classification']=='ASSERTION_FAILED_ROOT_CAUSE_NOT_ISOLATED']
    summary=dict(stage=stage,base_sha=os.environ['BASE_SHA'],audit_sha=os.environ['AUDIT_SHA'],executions=[])
    exit_code=1
    try:
        if stage=='original-suite':
            summary['executions'].append(run_pytest('original_full', ['tests'], 'original'))
            lint=subprocess.run([sys.executable,'-m','ruff','check','.'],capture_output=True,text=True)
            (base.OUT/'ruff.log').write_text(lint.stdout+lint.stderr)
            summary['ruff_exit_code']=lint.returncode
        elif stage=='original-isolated':
            for i,node in enumerate(root_nodes):
                summary['executions'].append(run_pytest('original_root_'+str(i),[node],'original'))
            summary['executions'].append(run_pytest('original_twelve',[n for n in nodes if n not in root_nodes],'original'))
        elif stage=='diagnostic':
            catalog=copied_catalog()
            diagnostic_nodes=[n.replace('tests/test_slice2a_catalogs_adversarial.py',catalog) for n in nodes]
            summary['executions'].append(run_pytest('diagnostic_fourteen',diagnostic_nodes,'diagnostic'))
            import claim_probe
            claims=asyncio.run(claim_probe.run(base.new_probe_session))
            write('claim_results.json',claims)
            summary['claim_outcomes']=dict(Counter(r['status'] for r in claims))
        else:
            raise RuntimeError('Unknown audit stage')
        exit_code=int(any(r['exit_code'] or r['missing_results'] or not r['collected'] for r in summary['executions']) or bool(summary.get('ruff_exit_code',0)) or any(s!='PASS' for s in summary.get('claim_outcomes',{})))
    except Exception as error:
        summary['harness_error']=dict(type=type(error).__name__,message=str(error),traceback=traceback.format_exc())
    summary['exit_code']=exit_code
    write('stage_summary.json',summary)
    print(json.dumps(summary))
    raise SystemExit(exit_code)


if __name__=='__main__':
    main()
