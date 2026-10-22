# The batch runner

Runs a list of protocols through Orrery, several at a time, and keeps enough
state to inspect or interrupt any one of them. Each protocol runs as its own
child process.

## The three commands

```bash
python -m experiments.batch run    main
python -m experiments.batch status main
python -m experiments.batch stop   main
```

The argument is the batch: `main`, `claims` or `baseline`, defined in
`../batches.py`. How many run at once comes from `max_runs_concurrency` in
`../config.yaml`.

| | |
|---|---|
| `run` | starts the batch, once every protocol is clear to start fresh. A protocol still holding an unfinished run is named and the batch stops there, for you to decide: delete that run directory to start it over, or continue it with `resume`. Add a protocol id to start that one alone |
| `status` | what has finished, what is running, what failed, and each run's name |
| `stop` | interrupts the whole batch the way Ctrl-C on the scheduler does: the scheduler starts nothing more and every child closes itself out and stays re-enterable |
| `resume <batch> <protocol> --from-node <node>` | continues that protocol's interrupted run in place, under the batch's own settings (`orrery run --run-name/--from-node` cannot take them, so it would finish the run under the defaults) |

State and logs are under `<work_root>/_batch/`; the run directories themselves
are the results.

## Choosing the protocols

`../protocols.yaml` holds two things, and all three batches read it:

```yaml
selected_protocols:      # the ids this batch runs, in this order
- NSPK
- TLS13-draft20

protocols:               # what each id means
  NSPK:
    protocol_name: NSPK              # --name passed to Orrery
    path: academic/NSPK              # relative to paths.lib_root
  TLS13-draft20:
    protocol_name: TLS13
    version: draft20                 # optional
    path: rfc/TLS13/draft20
  ISO-9798-2-mechanism-1:
    protocol_name: ISO-9798-2
    subprotocol: mechanism-1         # optional; picks one mechanism under the document
    path: ISO/9798-2-symmetric-encipherment
```

The id is the fields joined by `-`: `protocol_name`, then `version` and
`subprotocol` where they are given. Every id in `selected_protocols` has a
definition below it. 
