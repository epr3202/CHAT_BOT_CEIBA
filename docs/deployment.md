# R11 — protected deployment and certification contract

Status: candidate under CI validation. No deployment has been performed.
`PREPROD_TARGET=NOT_PROVISIONED`: repository evidence describes a Compose VPS and
historical `/opt/ceiba` paths, but identifies no confirmed staging host, database,
domain, TLS terminator, backup custodian or secret provisioning. Do not infer them
from the old SSH workflow. Infrastructure provisioning belongs to the next authorized pass.

## Environment and profiles

Canonical values: development, testing, staging, production. Protected image entrypoints
force `DEPLOYED_RUNTIME=true` and require explicit staging/production. Backend, worker
and one-shots share Settings validation. Frontend receives the same ENVIRONMENT from
the standalone `compose.protected.yml`; omission/invalid/local values abort before listening.
The local `docker-compose.yml` explicitly disables the deployed marker/entrypoint and
must never be used as a protected deployment profile. Local Python remains usable.

For staging set ENVIRONMENT=staging; production uses ENVIRONMENT=production. Both use
PAYMENT_EVIDENCE_AUTOMATION_ENABLED=false, CALENDAR_WRITES_ENABLED=false,
CALENDAR_ADAPTER=google, CATALOG_STORAGE_DIR=/data/catalogs and
PAYMENT_EVIDENCE_DIR=/data/payment-evidence. Do not construct Calendar adapters when
the gated visit actions are disabled. Google write credentials are not required.
The entrypoint validates settings and storage before any command, including Alembic.
API/worker additionally check the exact DB revision before serving or polling.

| Classification | Names |
| --- | --- |
| Known configuration | ENVIRONMENT, DEPLOYED_RUNTIME, PAYMENT_EVIDENCE_AUTOMATION_ENABLED, CALENDAR_WRITES_ENABLED, CALENDAR_ADAPTER, CATALOG_STORAGE_DIR, PAYMENT_EVIDENCE_DIR |
| Required; actual presence unverified | DATABASE_URL, META_APP_SECRET, META_VERIFY_TOKEN, META_ACCESS_TOKEN, META_PHONE_NUMBER_ID, OPENROUTER_API_KEY, POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DB, META_GRAPH_API_VERSION, CATALOG_HOST_DIR, EVIDENCE_HOST_DIR |
| Artifact identity supplied after build | API_IMAGE, FRONTEND_IMAGE (immutable local Docker sha256 IDs) |
| Not required in this release | GOOGLE_SERVICE_ACCOUNT_FILE, GOOGLE_CALENDAR_ID, GOOGLE_FREEBUSY_CALENDAR_IDS; historical DEPLOY_SSH_KEY/DEPLOY_HOST/DEPLOY_USER/DEPLOY_PATH are not read by CI |
| Must remain absent from images and frontend | .env files, private keys, secret stores, provider credentials; frontend does not receive backend secrets |

Real secret values stay outside Git and outside build contexts. Startup accepts no blank
critical secret/phone ID. No provider authentication is attempted by readiness. Graph
version remains configurable; account acceptance of v20.0 or the operator-selected
version must be demonstrated externally during the next pass, never assumed from age.
DATABASE_URL must identify the same Compose `db`/5432/database/user/password that the
deployment backs up. External database topology is unsupported until reviewed.

## Build and preservation

Use Linux amd64, Python 3.12 tooling and Docker/Compose v2 supporting `up --wait`.
From a clean exact detached checkout, run:

```sh
python3 -m scripts.build_release <full-sha> --output /protected/releases/<full-sha>
```

The build reads only `git archive <sha>`, rejects ancestry before R10.1, labels both
images with SHA/tree/schema, and writes image IDs and images.tar checksum to manifest.json.
No registry is presumed. Copy the complete archive/manifest via approved transport to
protected release storage; verify the manifest against CI evidence and the archive checksum
before `docker load --input images.tar`. Treat a modified manifest as an invalid artifact.
Retain the last safe artifact and its configuration alongside the candidate. CI artifacts
expire; the release custodian must preserve them beyond the 30-day Actions retention.

Runtime and CI dependencies are pinned with wheel hashes in requirements.lock and
requirements-ci.lock, derived from R10.1 CI 34871963604, CPython 3.12/Linux amd64.
Install with pip `--require-hashes --only-binary=:all:`. No manager migration. Python
and Postgres bases use verified R10.1 image digests. Node 22 base is a mutable build
input; record its built image ID and promote that image unchanged. Never rebuild during
promotion. Dependency/base refresh requires a new candidate and CI.
`.dockerignore` filters secrets, keys, worktrees and evidence; CI tests Docker's actual
context filtering using synthetic secret sentinels. Runtime Dockerfile copies explicit paths.

## Target inventory and authorization

Before executing, the operations owner supplies an external target.json with these names:

```json
{
  "environment": "staging",
  "hostname": "<verified host hostname>",
  "checkout_path": "<absolute detached checkout>",
  "project": "<existing isolated compose project>",
  "database_system_identifier": "<verified PostgreSQL system identifier>",
  "backup_dir": "<absolute protected backup directory>",
  "backup_gpg_recipient": "<approved backup key fingerprint>",
  "close_hook": "<absolute reviewed ingress-close executable>",
  "smoke_hook": "<absolute reviewed PRE smoke executable>",
  "reopen_hook": "<absolute reviewed ingress-reopen executable>"
}
```

These placeholders are not a provisioned target. Hooks must be operator-owned and
non-writable by application processes, return nonzero on failure, and verify their
postconditions: ingress closure/reopening and PRE smoke results. The close hook must
prove that all ingress is closed and that the named Compose services are the only
consumers of the target database. The operator verifies Docker context/daemon identity,
project/host ownership and absence of consumers outside this project. CI never calls
target hooks or reads operational secrets. For an empty DB, provision the target and
initial schema in a separately authorized bootstrap; unknown/unversioned DBs abort.

## Stop, checkpoint, migration and start

Run `./deploy.sh <sha> --manifest <manifest> --target <target>` for read-only identity
preflight/plan. It validates exact HEAD/tree, ancestry, labels/image IDs, host/path,
explicit environment, required Compose variables and DB system identifier. It does
not checkout, pull, build or migrate. Only the separately authorized deployment pass
adds `--execute`.

Execution is strictly: close ingress; stop frontend/API/worker with 180-second grace;
verify no old services running; inspect uncertain Outbox operations; encrypted backup
and restore-list verification; read-only migration ancestry preflight; upgrade explicitly
to 20260910_0027; verify exact revision; start API, then worker, then frontend with
Compose health waiting; DB/worker checks; smoke hook; reopen ingress.

Durable Inbox claims recover through their existing leases. Outbox SENDING or
ADMITTED/UNKNOWN admission requires human reconciliation; deploy aborts instead of
replaying an uncertain external send. SIGTERM/timeout may interrupt a poll; durable
claims are not deleted or reset by deployment. No PaymentEvidence/reminder loop is added.
Old revisions are eligible only when part of the single known chain; unversioned,
unknown or multiple revisions fail. No schema change is part of R11 (27 revisions).
After any failure ingress stays closed; investigate the named failed gate. Do not
rerun hooks or migration blindly, reopen traffic, or reset claims to obtain a green gate.

## Backup and restore

Responsible roles: operations/release owner runs and records checkpoint; database
custodian owns restore validation; security owner controls the GPG key and retention.
Provision GPG public/private restore keys via approved secret management, never an image.
The deployment streams `pg_dump -Fc -U "$POSTGRES_USER" "$POSTGRES_DB"` from Compose db
directly to `gpg --batch --encrypt --recipient <fingerprint> --output <timestamp>.dump.gpg`.
It checks both process exit codes, nonempty output, decrypts into `pg_restore --list`,
checks both exit codes again, then records the encrypted-file SHA256. Any failure aborts.
No plaintext dump is written. Backup directory must be owner-only (0700), encrypted at
rest and copied to separately protected storage with approved retention. The host needs
the restore key for verification; its absence blocks deployment rather than skipping.

Next pass MUST demonstrate restore into a disposable, separately named Postgres 16 DB:

```sh
# All variables refer to the disposable restore host/container; never the operational DB.
set -o pipefail
gpg --batch --decrypt <verified.dump.gpg> | \
  docker exec -i <disposable-postgres> pg_restore --exit-on-error \
  --no-owner --no-privileges -U <restore-role> -d <disposable-database>
```

Compare source/checkpoint and restored table counts for message, audit_event, customer,
conversation, inbox/outbox and lead; validate foreign keys/unique constraints and exact
alembic_version. Capture checksums, counts, timestamps and owner approval without PII.
Archive-list validation is necessary but does not replace this restore test. Never
drop/recreate or restore over an operational database in this task.

## Rollback

`./rollback.sh <safe-sha> --manifest <safe-manifest> --target <target> --execute` uses
the same identity and checkpoint gates, omits migration, requires exact 0027 before
start, and preserves OFF. No downgrade and no mutable branch selection. R9 ancestry
is rejected. Prior R10.1 has no R11 packaged artifact, so it is not an automatic
operational rollback image. Until a certified safe artifact exists, stop services and
keep ingress closed; preserve backup and seek an explicitly reviewed recovery release.

## Supervision, storage and health

Compose `restart: unless-stopped` handles exits; healthchecks detect unhealthy live
processes but Compose does not automatically restart an unhealthy process. Operations
must watch unhealthy status and perform reviewed restarts/recovery. `/live` checks
only process liveness; `/ready` checks storage, DB connectivity and exact schema with
a 10-second DB timeout and sanitized 503. Provider outages do not fail liveness.
Worker writes independent atomic inbox/outbox monotonic poll timestamps only after
successful polls; healthcheck requires live PID and both timestamps younger than 300s.
Polls longer than 300s may report unhealthy and require investigation, not blind restart.

Create catalog directory owned 10001:10001 mode0750; API RW, worker RO. Historical
evidence is persistent and RO in both services, owner10001/group10001 readable/searchable.
Paths are explicitly /data/catalogs and /data/payment-evidence. Missing/mispermissioned
directories abort startup. Postgres volume is project-scoped, has no published host port,
requires explicit password; full role separation is deferred hardening. API/frontend
bind host loopback. Provision a TLS reverse proxy with restricted admin access.

Frontend Node has restart/healthcheck, 20MiB request cap (supports catalog uploads),
20s upstream timeout, request/header timeouts, no server source download and basic
nosniff/frame/referrer headers. Simulator remains unavailable in protected environments.
Login distributed rate limiting is deferred: staging must restrict admin ingress via
VPN/IP policy; public production admin access is blocked pending throttling and review.
Reset CLI retains its established explicit phone/override contract, now applied equally
to staging and production; absence of either refuses the operation.

## Parity and next pass

Identical: approved SHA/tree and image IDs, process topology, PostgreSQL16, revision0027,
OFF flags, entrypoint guards, built runtime versions and storage semantics. Different:
credentials, DB instance/project, WhatsApp account/number, domain, test data and paths.
No real provider calls or operational migration occurred in R11.

Next authorized pass: provision/verify target and secret names; retain artifact/checksum;
configure TLS/admin access and target hooks; prove backup restore; deploy exact artifact;
run PRE-01..PRE-18 in the frozen certification plan in order, recording evidence for
each (worker polling and all OFF guards included); reopen only after all gates pass.
Rollback triggers: wrong identity, unsafe config, incompatible DB, missing worker polls,
scope breach, failed smoke or uncertain external effects. Stop and preserve evidence;
select only a reviewed safe artifact at 0027 or remain stopped.
