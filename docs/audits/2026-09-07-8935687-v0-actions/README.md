# V0: isolated GitHub Actions audit

Product BASE_SHA: `89356876a04bc836ea9b2c223ff8aba2b424ffde`.
AUDIT_SHA is the exact push commit recorded by each run. This folder changes no product behavior.
Only `.github/workflows/audit-v0.yml` and the seven allowlisted files in `run_ci.py` are published.
Original Phase I, Phase II and blocked local V0 artifacts remain local and unchanged.

Three independent Ubuntu 24.04 jobs run Python 3.12 and PostgreSQL 16. Pulled image digests,
installed dependency versions, original Git blob hashes, commands, run IDs and audit hashes
are included in artifacts. Dependencies are resolved from the unchanged unpinned pyproject;
the installation report documents the resulting resolution, not a reproducible lockfile.

The original complete pytest suite uses its original metadata fixtures in DB_SUITE. All setup,
call and teardown reports are retained alongside JUnit. No historical count is forced.
DB_MIGRADA is upgraded using original Alembic migrations; separate DB_METADATA is reflected
and compared after normalizing names, ordering and serial sequence defaults. Expression
equivalence still requires interpretation. No migration downgrade is introduced or modified.

The reproduction job executes 36 adapted Phase II probes plus multi-message H29, H04/H05,
and H17 flows. Every scenario uses a fresh migrated database. Only providers are simulated.
H05 remains linked to PR-06b / U21. Owner UPDATE observations do not establish deployed-role
permissions. Failure to reach a harness precondition is reported as HARNESS_ERROR, never as
confirmed product failure. Raw failed webhook statuses and persisted effects are retained.

The network is Docker internal, with an additional Python socket guard. Test containers
receive only synthetic runtime values and commit identities, no GitHub credentials, host
mounts or published ports. Artifacts contain only synthetic executions and expire after 3 days.
Any required assertion failure, harness error, preparation failure or missing artifact fails
the job, while independent jobs continue. This workflow has no deploy, PR, main push or tags.

Execution: push an authorized audit commit to `audit/v0-ci-*`; inspect the workflow run for
that exact AUDIT_SHA. `run_ci.py` intentionally refuses local execution outside GitHub Actions.
