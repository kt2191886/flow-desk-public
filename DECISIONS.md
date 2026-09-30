# Decisions

Eight design decisions, each with what it cost. All of them come from the private desk's own changelogs and lessons, with the specifics removed. None was obvious in advance. Most were found the hard way.

## 1. A missing observation is never recorded as zero

**What happened.** A data source stopped answering. The audit code treated an empty response as "open interest is zero", stored it, and cached it. For about seven weeks every alert was graded against fabricated zeros. Nothing failed. The confirmation rate just quietly fell.

**Decision.** No evidence, no row. An empty answer is never cached. An alert with nothing to check stays PENDING.

**Trade-off.** More alerts sit unresolved for longer, and the summary has a category that means "we do not know". That is less satisfying than a verdict and it is the truth.

**In this repo.** `score/confirm.py` (`pick_eod_oi` returns `None`, `build_snapshots` skips it). The eval counts violations of this rule and requires zero.

## 2. Wait for the data to exist before asking for it

**What happened.** The confirmation job ran in the evening. Settled open interest for that day is not published until the next morning, so the job fetched numbers that were not there yet and saved what it got.

**Decision.** Move the job to the next morning and add a guard: a session's figure is readable only after the publish hour on the next business day.

**Trade-off.** Every verdict arrives most of a day later. A slower right answer was chosen over a fast wrong one.

**In this repo.** `oi_available_for` in `score/confirm.py`.

## 3. Freshness compares with "on or after", not "equal to"

**What happened.** The freshness check required an artifact's date to equal the session date. Work finished just after midnight carried the next day's date and was flagged as stale. The reports existed and the monitor said they did not. A monitor that is wrong in a known way gets ignored.

**Decision.** Fresh means written on or after the session it belongs to.

**Trade-off.** The check is slightly more permissive. A file rewritten the next day with old contents would pass the file clock. That gap is why the data clock exists as a separate gate.

**In this repo.** `check_staleness` (file clock) and `check_data_clock` (dates inside the data) in `integrity/gates.py`.

## 4. A RED page is sent when something changes, not every time it is true

**What happened.** The integrity check ran every thirty minutes and sent a page on every RED. One known condition produced about 48 pages a day.

**Decision.** Page when the set of failing checks changes. Re-page at most every six hours while it persists. Send one recovery note when it clears.

**Trade-off.** A RED that persists is quieter than it used to be. Someone who missed the first page waits up to six hours for the second.

**In this repo.** `should_push` in `notify/sender.py`, a pure function with its own tests.

## 5. The aggressor side is not the account type

**What happened.** A large print that lifted the offer was read as a directional bet by a sophisticated buyer. The account-type report later showed the opposite: it was one leg of a financing structure, written by the side assumed to be buying. The same misread happened on several deep in-the-money contracts.

**Decision.** Who traded is answered only by the account-type report, only at the grain of the specific contract, and only while that read is recent. A blended read for the whole symbol never settles one strike. Deep in-the-money prints with no contract-level read go to a person and are never labeled.

**Trade-off.** The needs-a-person queue is longer, and some alerts that were real get no label at all. An unlabeled alert costs a few minutes. A confidently mislabeled one costs a decision.

**In this repo.** `open_close_support` and the hard guard in `score_alert` (`score/scorer.py`). `OpenClose.scope` in `contracts.py`.

## 6. A snapshot already contains the day's trades

**What happened.** The positions import loaded the brokerage snapshot and then replayed the day's fills on top. The snapshot already included those fills. Every position traded that day was counted twice.

**Decision.** The latest export is the single source of truth for what is held. Nothing is replayed onto it. After every import, the store is reconciled against the export and the import is rejected on any mismatch.

**Trade-off.** Intraday state cannot be reconstructed from fills between exports. The book is only as current as the last file.

**In this repo.** The rule survives as the never-from-memory gate: one file, read now, with a digest (`ingest/positions.py`, `check_positions_from_disk`). The reconciliation itself needs the database layer and was not ported.

## 7. A parser that does not recognize a file must fail, not return nothing

**What happened.** The brokerage changed its export layout: a few preamble lines and a differently named first column. A parser keyed to the old header found no matching rows and returned an empty list. It read as "no data".

**Decision.** Parsers search for their header within the first lines and raise an error when they cannot find it. Separately, zero rows from a required feed is RED.

**Trade-off.** A cosmetic change in a vendor file now stops the run until someone looks. That is the intended behavior and it is still an interruption.

**In this repo.** `read_table` and `FeedFormatError` in `ingest/_csvio.py`. `check_rows` in `integrity/gates.py`.

## 8. Match on strike and expiry, never strike alone

**What happened.** The check that flags new flow pressing on a held short strike matched by strike only. It raised a top-priority warning for a build that expired months away from the position it supposedly threatened. On review, three quarters of its flags were the same kind of mismatch.

**Decision.** Flow only counts against a held position when it shares that position's expiry cycle. A strike match in another cycle is kept as context and never raises priority.

**Trade-off.** A genuinely related build in a neighboring cycle will not be flagged as overlap. It still appears in the list, without the emphasis.

**In this repo.** `held_overlap` in `score/scorer.py`, which also reports how many cross-cycle matches it set aside.
