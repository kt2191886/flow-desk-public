"""The eval is deterministic, the gates catch every planted fault, the CLI runs."""
import io
import os
import unittest
from contextlib import redirect_stdout

from flow_desk import __main__ as cli
from flow_desk import eval as evaluation

from .helpers import FeedCase


class Eval(unittest.TestCase):
    def test_every_gate_scenario_returns_the_expected_verdict(self):
        rows = evaluation.run_gate_scenarios()
        self.assertGreaterEqual(len(rows), 10)
        self.assertEqual([r for r in rows if not r["ok"]], [])

    def test_confirmation_eval_is_deterministic_and_honest(self):
        a = evaluation.run_confirmation_eval(seeds=5)
        b = evaluation.run_confirmation_eval(seeds=5)
        self.assertEqual(a, b)
        self.assertEqual(a["tp"] + a["fp"] + a["fn"] + a["tn"], a["alerts"])
        self.assertGreater(a["precision"], 0.6)
        self.assertGreater(a["recall"], 0.6)
        self.assertLess(a["precision"], 1.0)      # a perfect score would mean the world is too easy
        self.assertGreater(a["no_evidence_alerts"], 0)
        self.assertEqual(a["fabricated_verdicts"], 0)


class Cli(FeedCase):
    def _run(self, *argv):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = cli.main(list(argv))
        return code, buf.getvalue()

    def test_demo_writes_four_outputs(self):
        code, text = self._run("demo", "--out", self.out)
        self.assertEqual(code, 0, text)
        for name in ("debrief.md", "chart.svg", "brief.html", "notify.json"):
            self.assertTrue(os.path.isfile(os.path.join(self.out, name)), name)
        self.assertIn("nothing was sent", text)

    def test_demo_with_a_fault_exits_red(self):
        code, text = self._run("demo", "--out", self.out, "--fault", "stale")
        self.assertEqual(code, 2)
        self.assertIn("Reads withheld", text)
        self.assertFalse(os.path.exists(os.path.join(self.out, "chart.svg")))

    def test_demo_refuses_positions_from_memory(self):
        code, text = self._run("demo", "--out", self.out, "--fault", "memory")
        self.assertEqual(code, 2)
        self.assertIn("in-memory book refused", text)


if __name__ == "__main__":
    unittest.main()
