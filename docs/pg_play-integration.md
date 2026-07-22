# pg_play integration contract

This document is for orchestrator authors. Normal users retain the concise
profile, install, run, scheduler, and lifecycle CLI described in the README.

`pg_workload` supports the hidden `pg_play/component/v1` machine transport:

```bash
pg-workload --machine --request-id workload-001 --component-capabilities
pg-workload --machine --request-id workload-002 validate --root workload
pg-workload --machine --request-id workload-003 plan \
  --root workload --operation=install --profile pagila
```

The capability document uses `pg_play/capabilities/v1`. Every command declares
the common boolean fields `mutates_target`, `machine_output`, and
`accepts_plan_hash`.
Its `machine_interface` object records the canonical machine, request-id, and
capability option names.

`plan` hashes every selected profile file, selected jobs, scale, connection
metadata without secrets, requested database changes, and scheduler state.
Mutating `prepare-db`, `install`, `run`, and `start` operations can
be guarded with the returned component plan hash.

`start`, `status`, and `stop` provide a bounded background lifecycle useful to
both people and orchestrators. `stop` verifies that the recorded PID belongs
to the exact project scheduler before sending a signal.

For an orchestrated run, the hidden `--enable-selected` option is supplied to
both `plan --operation=scheduler` and `start`. The plan hashes the prospective
desired state; `start` verifies that hash, writes all selected enables under
one state lock, and only then launches the scheduler.
`--job-interval-seconds` is included in that same desired state, so a reviewed
short diagnostic cadence cannot drift between plan and execution. Database
preparation creates the default pg_diag extensions (`pg_stat_statements` and
`pg_buffercache`) unless the caller explicitly supplies another extension set.

Passwords are accepted only through the documented environment/passfile
mechanisms. They are never accepted in the machine envelope or emitted to
stdout.
