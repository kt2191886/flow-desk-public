# Humans

Who is on the other end of this system, and what they get back.

## Who

One person: the operator of a small private trading desk. They read the morning brief before the market opens, decide what to do, and place every order themselves, by hand, in their own brokerage account. Nobody else receives the outputs. Nothing downstream of this system acts on them automatically.

## What they give the system

- A positions export, dropped as a file. The system will not accept positions any other way.
- The day's feed files.
- Optionally, a declared absence ("I am away until this date"), so expected gaps are reported as expected.
- Optionally, a webhook address for notifications, supplied per run.

## What they get back

| Output | When they read it | What it tells them |
|---|---|---|
| `notify.json` (or the message it becomes) | First, on a phone | The verdict in one line. Whether to open the brief, or to go fix an input first |
| `debrief.md` | At the desk | Blockers, then every integrity check, then the reads |
| `brief.html` | At the desk | The same content as one page, with the chart |
| `chart.svg` | Inside the brief | Which alerts open interest actually followed |

Every output is ordered the same way, for a reason. A person skimming early in the morning reads the top and stops. So the top says whether the rest can be trusted.

## What the system promises them

- **It will say when it does not know.** PENDING, "unknown", and "no evidence yet" are printed as such. They are never rounded to yes or no.
- **It will not show analysis it cannot vouch for.** On a RED verdict there are no reads, only the list of what to fix.
- **Every caveat travels with the numbers.** An AMBER run prints its caveats above the reads, not in a log.
- **Every artifact says what it was built from.** The stamp at the end of each file lists the inputs and their timestamps.
- **It will not nag.** A known problem pages once, then at most every few hours, then once more when it clears.

## What it asks of them

Two things only.

1. **Clear blockers.** A RED names the check and the reason. The fix is always on the input side: drop the missing file, re-export the positions, wait for the feed.
2. **Settle the needs-a-person queue.** These are alerts the data cannot classify: a deep in-the-money print with no contract-level account-type read, or a symbol with only a blended read. The system lists them with the exact thing to look up. It does not guess.

## What stays with the person, always

Whether to trade. What to trade. How much. When to stop. The system ranks what to look at and shows its evidence. It has no opinion on what to do about it, and no way to act if it had one.

## If a language model is in the loop

On the private desk a language model reads these same artifacts and writes a narrative summary. It is held to the rules a new analyst would be: read the file, cite the file, do not recompute a number the pipeline already produced, and do not state a position from memory. The pipeline in this repo is what makes that possible. The model is handed checked facts and asked only for judgment.
