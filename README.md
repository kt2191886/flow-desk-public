# flow-desk-public

An integrity-gated options-flow pipeline, extracted from a private one-person trading desk and rebuilt on synthetic data.

It shows how the desk thinks, not what it trades. The parsers, the integrity gates and the discipline around them are the real mechanisms. The symbols, positions, prices, thresholds and weights are not: every number in this repo is synthetic or a neutral default.

## What it does

Four raw feeds go in. Four readable outputs come out. A set of gates sits in between and decides whether the outputs may contain any analysis at all.

1. **Ingest.** One parser per feed shape: flow alerts, open-interest change, open/close by account type, the positions export. Each reads a file and returns records in one shared model.
2. **Gate.** Every input is checked for staleness, completeness and provenance. The verdict is GREEN, AMBER or RED. RED stops everything downstream.
3. **Confirm.** An alert says someone traded. The morning after (T+1), settled open interest says whether that trade opened a position. Each alert gets a verdict from the evidence, and "no evidence" is never recorded as "did not happen".
4. **Score.** Five independent axes rank what deserves a look. Anything the data cannot settle goes to a needs-a-person queue instead of getting a guess.
5. **Render.** The same records become a markdown debrief, one chart, one self-contained html page, and a notification payload.
6. **Notify.** One sender. It posts only if you give it a webhook. Otherwise it writes the payload to disk and says so.

## Sixty-second run

Python 3.9 or newer. Standard library only. No keys, no network, no install step.

```bash
python3 -m flow_desk demo
```

This generates a synthetic day, runs the pipeline, and writes four files to `out/`:

| File | Shape |
|---|---|
| `out/debrief.md` | The morning drill: blockers first, then integrity, then reads |
| `out/chart.svg` | One chart: did open interest follow the alert? |
| `out/brief.html` | The same brief as one self-contained page |
| `out/notify.json` | The notification payload |

Then break the day on purpose and watch the gate close:

```bash
python3 -m flow_desk demo --fault stale
```

Other faults: `missing`, `empty`, `olddata`, `format`, `memory`. Each one turns the run RED, removes the chart, and replaces the reads with the blocker list.

Run the eval and the tests:

```bash
python3 -m flow_desk eval
```

```bash
python3 -m unittest
```

## The eval, honestly

`synth.py` plants a hidden truth: which alerts really opened a position. The pipeline never sees it. `eval.py` scores the pipeline against it.

| Question | Result |
|---|---|
| Do the gates catch each planted fault? | 11 of 11 scenarios return the expected verdict |
| T+1 confirmation, precision | 0.818 |
| T+1 confirmation, recall | 0.747 |
| Alerts with no evidence that were marked "not confirmed" anyway | 0 of 40 |

Pooled over 25 seeds and 900 synthetic alerts, with a fixed clock, so the numbers are the same on every machine. The synthetic world includes masked opens, look-alike flow and contracts with no data, so precision and recall are not 1.0 and should not be. They measure the mechanism on made-up data. They say nothing about real markets.

## Sending to Discord

Off by default. To turn it on, set one environment variable for the run:

```bash
DISCORD_WEBHOOK_URL="<your webhook url>" python3 -m flow_desk demo
```

The URL is read from the environment at send time. It is never stored, logged, or written to any file.

## Layout

```
flow_desk/
  contracts.py        the shared record model
  config.py           every threshold, by name (neutral demo defaults)
  ingest/             one parser per input shape
  integrity/          the gates, and the inputs_asof stamps
  score/              T+1 confirmation, five-axis scorer
  render/             debrief.md, chart.svg, brief.html, notify.json
  notify/             the one sender
  pipeline.py         ingest, gate, confirm, score, render, notify
  synth.py            a synthetic day with a hidden truth
  eval.py             gate scenarios, precision and recall
tests/                python3 -m unittest
tools/public_gate.py  the check this repo passed before it was published
```

Read next: [ARCHITECTURE.md](ARCHITECTURE.md) for the data flow, [INTEGRITY.md](INTEGRITY.md) for each rule and why it exists, [DECISIONS.md](DECISIONS.md) for the trade-offs, [HUMANS.md](HUMANS.md) for who is on the other end, [STOP.md](STOP.md) for when it must pause.

## What this is not

Not a trading system, not a signal, not advice. It places no orders and connects to no broker. It contains no real symbols, positions, prices or results. The thresholds and weights are neutral defaults, not the desk's tuned values. It is a slice, not the whole desk: the database layer, the scheduler, and the language-model synthesis layer are described in the docs and are not in this repo.

## Who made this

I'm Kai. I run a small private options desk by myself, and I place every trade by hand. The system around it exists to keep me honest before I decide anything: it checks that the data is fresh and complete, tells me plainly when it is not, and refuses to hand me analysis built on inputs it cannot vouch for. This repo is the part of that system I can show in public. I build the invisible systems so the room can stay human.
