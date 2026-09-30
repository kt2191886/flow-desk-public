# Integrity

The due-diligence rules, in plain language, and why each one exists. Every rule here came from something that went wrong at least once.

The short version: **never fabricate, mark everything, and gate on integrity before anything reaches the person who decides.**

## The verdict

Each check returns GREEN, AMBER or RED with a one-line reason. The run's verdict is the worst single check.

| Verdict | Meaning | What happens |
|---|---|---|
| GREEN | Inputs passed every gate | Reads are produced |
| AMBER | Usable, with a named caveat | Reads are produced and the caveat is printed above them |
| RED | An input cannot be vouched for | Reads are withheld. The outputs carry the blocker list only |

There is no override flag. The way to clear a RED is to fix the input and run again.

## The gates

### 1. Staleness: the file clock

*Rule.* A feed file older than its limit is RED.

*Why.* A pipeline that runs on schedule will happily run on yesterday's file if today's never arrived. The output looks normal. Nothing in it says the data is a day old. The only defense is to check the age of every input on every run.

### 2. Staleness: the data clock

*Rule.* The newest session date inside the open-interest feed must be the last completed session or later. Otherwise RED, even if the file itself is new.

*Why.* A file's timestamp says when it was written, not when its contents were true. A cache that re-saves, or a source that serves an old snapshot, produces a fresh file full of old data. The file clock cannot see that. The dates in the rows can.

### 3. Completeness

*Rule.* Every required layer must be present. A missing required layer is RED. A missing optional layer is AMBER.

*Why.* The scorer combines layers. With one missing it still returns a score, just a lower, quieter one. A reader cannot tell "this alert is weak" from "we could not see half the evidence". So the absence is reported before any score is shown.

### 4. Zero rows is an error

*Rule.* A feed that parses to zero rows is RED for a required layer. A file whose header the parser does not recognize raises an error instead of returning an empty list.

*Why.* An export format changed once, and a parser keyed to the old header returned nothing. No crash, no warning. It read as "no data today". An empty answer from a parser that did not understand the question is the most dangerous kind of wrong, because it looks like a quiet day.

### 5. Never from memory

*Rule.* Positions must come from a file on disk, read during this run. The loaded book carries the file's path and digest. The gate is RED if the book was assembled in code, if the file is gone, or if the file changed after it was read.

*Why.* Positions are the one input where being slightly out of date is worse than having nothing. A book remembered from an earlier session, typed into a prompt, or left in a variable looks exactly like a current one. This rule matters most where a language model is in the loop: a model will answer a question about holdings from whatever it saw last, fluently and wrongly. The only acceptable source is the latest export, read now.

### 6. Held coverage

*Rule.* Every symbol with a held option should appear in the open-interest feed. A held symbol with no data is AMBER and is named.

*Why.* The gaps that matter are the ones in names you actually hold. An average coverage figure hides them. Naming them does not.

### 7. A broken check is not a passing check

*Rule.* If a check itself raises an error, the result is AMBER with the reason, never a silent skip.

*Why.* The failure mode of a monitoring layer is to fail quietly and leave everything looking green.

## Rules inside the confirmation step

### 8. No evidence means no row

*Rule.* When open interest for a contract cannot be found, nothing is recorded. The alert stays PENDING. A missing observation is never written as zero.

*Why.* A data source once went dark. The code treated "nothing came back" as "open interest is zero" and stored it. For weeks, every alert was scored against fabricated zeros and marked as not confirmed. Nothing crashed. "We could not see it" and "it did not happen" are different facts, and only the second may count against an alert.

### 9. Wait for the publish window

*Rule.* End-of-day open interest for a session is not read until the morning of the next business day.

*Why.* Asking before the figure is published returns an empty or stale answer. Caching that answer poisons every later read for that day.

### 10. Observed days, not calendar days

*Rule.* "Not confirmed" requires enough days of actual observations showing no growth. Calendar age alone is not enough.

*Why.* A weekend, a holiday or a feed outage is not three days of evidence.

## Rules around the outputs

### 11. Every artifact says what it was built from

*Rule.* Each output ends with an `inputs_asof` stamp listing the input files and their timestamps. A checker compares the stamp with the files as they are now.

*Why.* Several producers write on different clocks. A report can ship minutes before a newer input lands, and afterwards nobody can tell. The stamp makes "was this built on the latest data?" a question with an answer.

### 12. Expected darkness softens, never silences

*Rule.* When the operator has declared an absence, staleness on layers a person drops by hand is AMBER with the as-of time, not RED. Layers that machines feed still go RED.

*Why.* A gate that pages every day for a condition everyone expects gets ignored, and then it gets ignored on the day it is right. The as-of time still prints on every output, so no reader mistakes an old book for a current one.

### 13. Pages do not repeat themselves

*Rule.* A RED page is sent when the set of failing checks changes, re-sent at most every few hours while it persists, and followed by one recovery note when it clears.

*Why.* The same RED re-sent on every scheduled run trains the reader to mute the channel.

## What was not ported

Honest list. These exist on the private desk and are not in this repo because they depend on parts that were left out:

- Reconciling the positions store against each new export, leg by leg, and aborting the import on a mismatch. Needs the database layer.
- Spot-checking field values between the raw feed and the stored rows. Needs the database layer.
- Liveness of the scheduler and freshness of each scheduled artifact. Needs the scheduler.
- Any self-healing. The private desk's sentinel is also read-only by design: catching drift is the job, fixing it is a person's call.
