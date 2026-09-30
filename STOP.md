# Stop

When this system must pause, and who decides what happens next.

## It stops itself when

| Condition | What it does | Who decides next |
|---|---|---|
| Any integrity check is RED | Withholds every read. Writes the blocker list. Removes the chart. Exits with code 2 | The operator fixes the input and runs again |
| A required feed is missing, stale, empty, or in an unknown format | RED, as above | The operator |
| The newest data inside a feed is older than the last session | RED, as above | The operator |
| Positions did not come from a file read during this run | RED, as above | The operator re-exports and drops the file |
| The positions file changed after it was read | RED, as above | The operator runs again |
| Scoring is called without a passing integrity report | Raises `IntegrityBlocked`. No score is produced | The caller must run the gates first |
| An alert cannot be classified from the data | Puts it in the needs-a-person queue with the exact lookup required. No label is assigned | The operator |
| No evidence exists for an alert | Leaves it PENDING. Never records a zero | Nobody. It waits for data |
| No webhook address is set | Sends nothing. Says so | The operator, if they want a message |
| The webhook address is not https, or the post fails | Sends nothing, or reports the failure. Never claims a delivery | The operator |

## It never does these, under any verdict

- Place, preview, stage or size a trade. There is no code here that talks to a broker.
- Recommend an action. Outputs rank what to look at. They do not say what to do.
- Fill a gap with an estimate, a default, or the last known value.
- Relax a gate. There is no force flag and no override.
- Send anything to an address it was not given for that run.
- Repair its own inputs. Catching drift is its job. Fixing it is a person's call.

## What only a person may do

- Decide that a RED is acceptable. The answer in code is always no, so this means fixing the input.
- Change a threshold in `config.py`. Each one guards a specific failure. Loosening one is a decision with a reason, not a way to get a green run.
- Resolve an item in the needs-a-person queue.
- Declare an absence, which softens staleness on hand-dropped layers to AMBER. It does not soften anything a machine feeds.
- Publish this repository. `tools/public_gate.py` must pass first, and then every file gets read once by eye. The gate catches strings. It does not catch meaning.

## If you extend this

Keep the order: ingest, gate, then everything else. If you add a step that produces a number a person will act on, make it call `require_pass` first. If you add an input, give it a staleness limit, decide whether it is required, and add a fault for it in `synth.py` so the eval proves the gate catches it.
