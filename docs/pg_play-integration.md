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

`plan` hashes every selected profile file, selected jobs, scale, connection
metadata without secrets, requested database changes, and scheduler state.
Mutating `prepare-db`, `install`, `run`, `scheduler`, and `start` operations can
be guarded with the returned component plan hash.

`start`, `status`, and `stop` provide a bounded background lifecycle useful to
both people and orchestrators. `stop` verifies that the recorded PID belongs
to the exact project scheduler before sending a signal.

For an orchestrated run, the hidden `--enable-selected` option is supplied to
both `plan --operation=scheduler` and `start`. The plan hashes the prospective
desired state; `start` verifies that hash, writes all selected enables under
one state lock, and only then launches the scheduler.

Passwords are accepted only through the documented environment/passfile
mechanisms. They are never accepted in the machine envelope or emitted to
stdout.
