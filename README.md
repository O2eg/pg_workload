# pg-workload

`pg-workload` emulates PostgreSQL backend activity that produces diverse query plans, logs, and
runtime statistics for diagnostic observation. It installs, validates, runs, and schedules
declarative activity profiles in the PostgreSQL test flow:

```text
pg-stand -> pg-workload -> pg-diag report
                 |              ^
                 +-- rerun -----+
```

`pg-stand` creates a reproducible database stand, `pg-workload` changes its behavior, and
`pg-diag` captures the result. A user can edit a workload profile, repeat the workload, and build
another report without recreating the whole experiment.

The distribution name and command are `pg-workload`; the import package is `pg_workload`. The
wheel contains immutable profile templates and a public `pg_workload/v1` JSON Schema. Runtime
state, logs, credentials, and generated table contents are never packaged.

## Related projects

pg_workload is conceptually different from a benchmark tool such as
[pg_perf_bench](https://github.com/O2eg/pg_perf_bench): a benchmark measures a system
(maximum TPS across a controlled load sweep, with a recreated database and captured
environment evidence for every point), while pg_workload does not measure anything — it
emulates diverse background activity so that an otherwise empty database starts to "live":
queries, plans, locks, WAL, autovacuum, errors, and logs. That living database is then
observed from the other side: diagnostic reports, log parsing, dashboards, and monitoring
pipelines are tested against it.

| Project | How it is used together with pg_workload |
|---|---|
| [pg_stand](https://github.com/O2eg/pg_stand) | Deploys the disposable Docker stands (PostgreSQL 10–18, replication topologies, diagnostic extensions preloaded) that pg_workload loads — the canonical `pg-stand -> pg-workload -> pg-diag` target. |
| [pg_diag](https://github.com/O2eg/pg_diag) | Captures JSON/HTML diagnostic reports of the activity pg_workload generates. Bundled profile READMEs document which pg_diag sections each profile exercises, and `prepare-db` installs the matching default extensions (`pg_stat_statements`, `pg_buffercache`). |
| [pg_play](https://github.com/O2eg/pg_play) | Orchestrates pg_workload through the versioned machine contract `pg_play/component/v1` (plan hashes, desired-state scheduler control) — see [docs/pg_play-integration.md](docs/pg_play-integration.md). |
| [pg_configurator](https://github.com/O2eg/pg_configurator) | Generates versioned PostgreSQL configuration candidates; apply a candidate to the stand and rerun the same pg_workload profiles to observe how behavior changes with the settings. |

## Installation

### Install from PyPI

```bash
mkdir pg-workload-project
cd pg-workload-project

python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install pg-workload

pg-workload --version
pg-workload init
pg-workload profiles
pg-workload validate
```

`pg-workload init` copies editable profiles and the schema into the current project, creates an
empty desired-state file, and creates per-profile log directories. It is idempotent when bundled
assets are unchanged. It refuses to overwrite local profile edits; use `init --force` only when
the packaged version should replace those edits.

Initialize another directory with:

```bash
pg-workload init --directory /srv/pg-workload/lab
```

The CLI can also be invoked as `python -m pg_workload`.

### Install from source

```bash
git clone https://github.com/O2eg/pg_workload.git
cd pg_workload
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'

.venv/bin/pg-workload init --directory local-workload
.venv/bin/pg-workload validate --root local-workload
```

Python 3.10 and newer are supported. `psql` and `pgbench` from the selected PostgreSQL major
version must be installed on the runner host.

## Quick start

Set credentials outside the command line. `pg-workload` has no default password:

```bash
export WORKLOAD_ADMIN_PASSWORD='admin-secret'
export WORKLOAD_PASSWORD='new-workload-role-secret'
```

Create the workload database and role, install a profile, and run it once:

```bash
pg-workload prepare-db \
  --target external \
  --host 127.0.0.1 \
  --database workload_db

pg-workload install \
  --target external \
  --host 127.0.0.1 \
  --database workload_db \
  --profile simple_stock \
  --scale 1

pg-workload run \
  --target external \
  --host 127.0.0.1 \
  --database workload_db \
  --profile simple_stock
```

For an existing role, prefer a libpq passfile:

```bash
chmod 600 ./workload.pgpass
pg-workload run \
  --target external \
  --host db.example.net \
  --database workload_db \
  --passfile ./workload.pgpass \
  --profile simple_stock
```

The passfile has standard libpq fields:

```text
hostname:port:database:username:password
```

`WORKLOAD_ADMIN_PASSWORD` authenticates administrative operations. `WORKLOAD_PASSWORD` is needed
when `prepare-db` creates a role and may also authenticate workload jobs. `PGPASSFILE` can be used
instead of `--passfile`; `PGPASSWORD` is accepted only as an admin-password compatibility input.

## Credential and role safety

- There is no built-in or generated public password.
- Passwords are not accepted as CLI flags, so they do not appear in process listings or shell
  history.
- Passwords are never placed in `PGOPTIONS`, psql variables, log messages, or scheduler child
  arguments.
- `prepare-db` does not change the password of an existing role.
- Password rotation requires both `--rotate-workload-password` and `WORKLOAD_PASSWORD`.
- Promotion of an existing workload role to superuser requires `--workload-superuser`.
- Existing roles can use passfile, peer, certificate, or another libpq-supported authentication
  method.

`prepare-db --recreate` drops only the selected workload database after terminating its sessions;
it does not drop the workload role.
Unless `--extensions` is supplied, it creates both `pg_stat_statements` and
`pg_buffercache`, matching the default pg_diag metric set used by pg_play.

## Targets

Three connection modes use the same workload contract:

- `local`: defaults to `/var/run/postgresql` and is suitable for a command running on the DB host.
- `external`: defaults to `127.0.0.1`; pass `--host` for a remote server or proxy.
- `patroni`: resolves a member through one or more `--patroni-url` REST endpoints and
  `--patroni-role`.

Examples:

```bash
pg-workload run --target local --profile simple_stock

pg-workload run \
  --target patroni \
  --patroni-url http://patroni-1:8008 \
  --patroni-url http://patroni-2:8008 \
  --patroni-role master \
  --profile simple_stock
```

Use `--bin-dir /path/to/postgresql/bin` when client binaries are outside
`/usr/lib/postgresql/<major>/bin`. The default major version is 18.

## Bundled profiles

| Profile | Purpose | Data preparation |
|---|---|---|
| `simple_stock` | Write-heavy CRUD over related stock tables | synthetic Python generator |
| `simple_stock_spec_symbols` | Identifier, Unicode, and parser edge cases | synthetic Python generator |
| `imdb` | Movie-domain analytical joins and skew | synthetic Python generator |
| `pagila` | Mixed Pagila OLTP | synthetic Python generator |
| `many_objects` | Metadata-heavy schemas and partitions | scale-aware SQL object creation |
| `emulate_errors` | Intentional SQL errors | SQL seed rows only |
| `pss_overflow` | `pg_stat_statements` churn | scaled Python generator; extension/preload required |
| `queue_skip_locked` | Producer/consumer task queue with `FOR UPDATE SKIP LOCKED` | synthetic Python generator |
| `jsonb_docs` | JSONB document store with GIN containment and `jsonb_set` updates | synthetic Python generator |
| `partition_aging` | Daily-partitioned time-series with partition pruning and aging DDL | synthetic Python generator |
| `bloat_vacuum` | Dead-tuple churn from non-HOT updates with scheduled `VACUUM` | synthetic Python generator |

No profile requires a dump, CSV file, or network download. The Pagila schema is redistributed
under its upstream license; see `THIRD_PARTY_NOTICES.md`. Its rows are generated locally. The
bundled `imdb` profile is an original, compact movie-domain model and does not contain Join Order
Benchmark SQL or IMDB source data.

Every profile directory contains a `README.md` with the scenario description, its jobs, the
pg_diag sections it is meant to exercise, and scale/observation guidance.

## Profile contract

See [docs/profile-authoring-cookbook.md](docs/profile-authoring-cookbook.md) for a complete
guide to writing custom profiles, including generator conventions and worked recipes for
queue, JSONB, partitioning, and bloat scenarios.

Profiles live at `data/<profile>/profile.yml`. Version 1 is identified by the stable string
`pg_workload/v1`:

```yaml
api_version: pg_workload/v1
name: my_workload
schema: my_workload
description: Small example workload.
requires_write: false
min_pg_version: 12            # optional major-version floor for the target server

prepare:
  steps:
    - type: sql
      path: sql/schema.sql
    - type: generator
      path: generator.py
    - type: sql
      path: sql/indexes.sql

jobs:
  - name: reads
    type: pgbench
    interval: 60
    transactions: 10
    clients: 2
    threads: 2
    scripts:
      - path: sql/01_read.sql
        weight: 5
    log: reads.log

  - name: analyze
    type: psql
    interval: 1800
    command: "ANALYZE my_workload.items;"
    log: analyze.log
```

The public schema is copied to `schema/pg_workload-v1.schema.json`. Runtime validation also checks
conditions that JSON Schema alone cannot safely enforce:

- unknown fields are errors at every object level;
- `api_version`, `name`, and a non-empty `jobs` list are required;
- job names are unique and types are `pgbench` or `psql`;
- a pgbench job defines exactly one of `duration` or `transactions`;
- threads do not exceed clients;
- `min_pg_version`, when present, is an integer major version of at least 10;
- SQL files, generators, script globs, and logs stay inside their profile boundary even when
  symlinks are present;
- generator steps reference an existing Python file;
- referenced local SQL and pgbench scripts exist before any database operation begins.

`validate` checks the complete contract and all local paths without connecting to PostgreSQL.
`install` executes `prepare.steps` in declared order. A normal data profile therefore creates its
schema, runs its generator, and only then creates indexes and statistics. When a profile declares
`min_pg_version`, `install` also queries the target `server_version_num` and refuses to install
on an older server — this fails fast instead of breaking later on a missing feature
(for example, `jsonb_docs` requires PostgreSQL 12 for SQL/JSON path queries).

```bash
pg-workload validate
pg-workload validate --profile simple_stock
```

`--workload` remains a temporary compatibility alias for `--profile`; `--dbname` is an alias for
`--database`.

## Prepare, install, and run

```bash
pg-workload prepare-db --target external --host 127.0.0.1

pg-workload install \
  --target external --host 127.0.0.1 \
  --profile simple_stock \
  --profile pss_overflow \
  --scale 1

pg-workload run \
  --target external --host 127.0.0.1 \
  --profile simple_stock \
  --job main
```

`install --prepare-db` combines database preparation and profile installation. Use
`--recreate-db` with it only for a disposable stand.

CLI pgbench overrides are mutually exclusive:

```bash
pg-workload run --profile simple_stock --pgbench-duration 30
pg-workload run --profile simple_stock --pgbench-transactions 100
```

### Synthetic data scale

`--scale` is a positive coefficient passed to every Python generator during `install`. At
`--scale 1`, the profiles approximate these domain sizes:

| Profile | Base table sizes at scale 1 |
|---|---|
| `simple_stock` | 150,000 product groups; 1,000,000 SKUs; 1,000,000 stock rows |
| `simple_stock_spec_symbols` | the same cardinalities with hostile and Unicode identifiers/values |
| `imdb` | 10,000 companies; 100,000 people; 100,000 titles; 1,300,000 fact rows |
| `pagila` | 600 customers; 1,000 films; 4,500 inventory; 16,000 rentals; 16,500 payments |
| `queue_skip_locked` | 20,000 pending + 5,000 done queue tasks |
| `jsonb_docs` | 50,000 JSONB documents |
| `partition_aging` | 33 daily partitions; 200,000 events skewed toward recent days |
| `bloat_vacuum` | 100,000 accounts, pre-bloated by one non-HOT update round |

For example, `--scale 2` approximately doubles scalable tables. Very small values retain a
profile-specific minimum so foreign-key structure and query selectivity remain meaningful in CI.
Generators use deterministic seeds, preserve foreign-key relationships, and introduce skewed
random distributions for hot entities, popularity, money, ratings, inventory, and customers.
`many_objects` scales its committed schema batches with `scale_repeat`; this
also bounds DDL locks on small PostgreSQL stands. `pss_overflow` scales its
generated table count (with a 50-table minimum). `emulate_errors` alone ignores
`--scale` because it keeps a fixed, tiny seed.

Installing a generated profile recreates its schema before filling it, so changing `--scale` and
installing again produces a clean dataset rather than appending rows. Scheduler recovery reuses
the same scale that was passed to the scheduler.

A profile generator is a regular Python program invoked as `python generator.py --scale VALUE`.
It receives the selected connection through standard `PGHOST`, `PGPORT`, `PGDATABASE`, `PGUSER`,
`PGAPPNAME`, and libpq credential environment variables; `PG_WORKLOAD_PSQL` points to the selected
`psql` binary. Bundled generators use only the Python standard library and stream server-side SQL
to `psql`, so generated rows never pass through repository files. Because a locally edited
generator can execute arbitrary code with the runner account, only run profiles from a trusted
project directory.

## Desired-state scheduler

The scheduler runs in the foreground and owns only its child workload processes. It does not
install cron jobs or systemd units.

```bash
pg-workload enable simple_stock --job main --interval 60
pg-workload enable pss_overflow --job statement_churn --interval 120
pg-workload state

pg-workload scheduler \
  --target external \
  --host 127.0.0.1 \
  --run-immediately
```

`scheduler`, `start`, and their reviewed `plan --operation=scheduler` accept
`--job-interval-seconds N` to apply one bounded interval to every selected
profile. This is intended for short orchestrated observation windows; normal
long-running installations should keep profile-specific intervals.

Changes made by `enable`, `disable`, and `set-interval` are picked up without restarting the
scheduler:

```bash
pg-workload disable simple_stock --job main
pg-workload set-interval pss_overflow statement_churn 300
```

Only one scheduler may hold `state/scheduler.lock`. Scheduler subprocesses use
`python -m pg_workload`, so installed operation does not depend on a repository checkout.

## Resource guard and logs

Before installation and execution, and while scheduled jobs run, the resource guard checks:

- used space on writable mounted filesystems;
- available memory in percent and MiB;
- average CPU utilization.

Thresholds are configurable with `--resource-*` options. `--no-resource-monitor` is intended for
controlled testing only.

Job output is written under `data/<profile>/log/`. Logs rotate at job start and by size. Configure
retention with `--log-max-mb`, `--log-backups`, and `--no-log-rotate-on-start`. Known secrets are
redacted from command and output logs.

## Project boundary

After `init`, the working directory is:

```text
project/
  data/<profile>/
    profile.yml
    README.md             # scenario, jobs, pg_diag watch list, scale guidance
    generator.py          # only when the profile needs table data
    sql/
    log/                 # runtime, ignored
  schema/
    pg_workload-v1.schema.json
  state/
    workloads.yml        # runtime desired state
    scheduler.lock       # runtime lock
```

The repository `.gitignore` excludes initialized root-level `data/`, `schema/`, `state/`, logs,
locks, dumps, archives, and CSV datasets. Canonical immutable profile sources live only in
`src/pg_workload/bundled/` and are included in the wheel; generated table rows live only in the
target PostgreSQL database.

## Orchestrator integration

The normal profile and scheduler CLI remains human-oriented. Authors of
`pg_play`-compatible orchestrators can use the separate
[versioned machine contract](docs/pg_play-integration.md).

## Development and release checks

```bash
python -m pip install -e '.[dev]'
ruff check .
ruff format --check .
pytest

python -m build
twine check dist/*
```

Docker PostgreSQL 18 integration is opt-in locally:

```bash
WORKLOAD_DOCKER_INTEGRATION=1 pytest tests/test_docker_postgres18.py
```

Release automation verifies Python 3.10 and 3.12, Ruff, unit tests, the PostgreSQL 18 Docker
integration test, tag/version equality, sdist/wheel metadata, and a clean wheel smoke test covering
`--version`, `init`, `profiles`, and `validate`. Publishing uses PyPI Trusted Publishing; no PyPI
API token is stored in the repository.
