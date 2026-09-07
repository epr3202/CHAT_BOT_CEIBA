# V0 failure diagnosis (audit only)

Historical BASE_SHA: 89356876a04bc836ea9b2c223ff8aba2b424ffde.
Historical AUDIT_SHA: df71d5de2de7834fffaf32fec3702a4e00dbe3be; run 34146552339.
New results must be attributed to the new push SHA and kept separate from historical runs.

The V0 launcher and guarded driver are reused in a new sibling folder. Original product,
tests, migrations, dependencies, deploy workflow and previous evidence remain unchanged.
The audit workflow has three independent jobs: full original suite, isolated originals,
and diagnostic copies/provider adapters. The original full suite is observed only at the
fourteen previously failing nodes; wrappers record rows and exceptions and delegate to
the real functions without changing outcomes. This instrumentation adds reads and timing
overhead and is not a proof that all possible races are absent.

Diagnostic change 1: generate a copy of the catalog test module and change one fixture
assignment so DATABASE_URL explicitly uses TEST_DATABASE_URL. AST equality verifies every
functional test body and its assertions remain identical. Diagnostic change 2: respx
returns a valid but unsupported event_type for the three targeted extractor paths, keeping
the real AI client/parser/normalizer and all functional assertions. No real provider access.

H02 uses three migrated probes: current success control, stale success, stale failure.
The criterion is whether an old result changes locally settled state after a newer claim;
the old provider invocation has already started and its actual external outcome is unknown.
Invocation counts do not assert external exactly-once guarantees.

Artifacts preserve per-phase JSON/JUnit, observations, exact commands, versions, image
digests, Git blob hashes, diagnostic copy changes and assertion AST equality. Required
failures remain visible in CI. No result is described as 627/627 original by combining
diagnostic passes. No deploy, main push, PR, remediation, local runtimes or operational data.
