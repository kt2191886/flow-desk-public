"""Render smoke tests: four outputs from the same records, and the stamp."""
import json
import os
import unittest
from datetime import timedelta

from flow_desk import pipeline, synth
from flow_desk.integrity import provenance

from .helpers import CLOCK, FeedCase


class RenderSmoke(FeedCase):
    def setUp(self):
        super(RenderSmoke, self).setUp()
        self.got = pipeline.run(self.feeds, self.out, now=CLOCK, send=False)

    def _read(self, name):
        with open(self.got["paths"][name], encoding="utf-8") as fh:
            return fh.read()

    def test_four_outputs_exist_and_are_not_empty(self):
        self.assertEqual(sorted(self.got["paths"]),
                         ["brief.html", "chart.svg", "debrief.md", "notify.json"])
        for name in self.got["paths"]:
            self.assertGreater(len(self._read(name)), 200, name)

    def test_debrief_puts_blockers_before_reads(self):
        text = self._read("debrief.md")
        self.assertLess(text.index("## 1. Blockers"), text.index("## 2. Integrity checks"))
        self.assertLess(text.index("## 2. Integrity checks"), text.index("## 3. Reads"))

    def test_html_is_self_contained(self):
        page = self._read("brief.html")
        self.assertTrue(page.startswith("<!doctype html>"))
        self.assertIn("<svg", page)
        for needle in ("<script", "<link", "@import", "src="):
            self.assertNotIn(needle, page)

    def test_chart_draws_no_bar_for_missing_evidence(self):
        svg = self._read("chart.svg")
        pending = sum(1 for s in self.got["result"]["scored"] if s["confirmation"] == "PENDING")
        self.assertGreater(pending, 0)
        self.assertEqual(svg.count("no evidence yet"), pending)
        self.assertEqual(svg.count("<title>"), len(self.got["result"]["scored"]) - pending)

    def test_outputs_agree_with_each_other(self):
        payload = json.loads(self._read("notify.json"))
        self.assertEqual(payload["integrity"], self.got["report"]["overall"])
        for verdict, n in payload["verdict_counts"].items():
            self.assertIn("%s %d" % (verdict, n), self._read("debrief.md"))
            self.assertIn("%s %d" % (verdict, n), self._read("brief.html"))

    def test_no_absolute_paths_leak_into_outputs(self):
        for name in self.got["paths"]:
            self.assertNotIn(self.tmp, self._read(name), name)


class Provenance(FeedCase):
    def setUp(self):
        super(Provenance, self).setUp()
        self.got = pipeline.run(self.feeds, self.out, now=CLOCK, send=False)

    def test_every_artifact_is_stamped_and_clean(self):
        for name in ("debrief.md", "brief.html", "notify.json"):
            self.assertEqual(provenance.check(self.got["paths"][name], self.feeds), [], name)

    def test_newer_input_flags_the_artifact_stale(self):
        synth.set_mtimes(self.feeds, CLOCK + timedelta(minutes=5), only="oi_change")
        stale = provenance.check(self.got["paths"]["debrief.md"], self.feeds)
        self.assertEqual([(s["source"], s["reason"]) for s in stale],
                         [("oi_change.csv", "newer")])

    def test_input_that_disappears_is_flagged(self):
        os.remove(self.path("open_close"))
        stale = provenance.check(self.got["paths"]["notify.json"], self.feeds)
        self.assertEqual([(s["source"], s["reason"]) for s in stale],
                         [("open_close.csv", "missing_now")])

    def test_unstamped_artifact_is_unknown_not_clean(self):
        path = os.path.join(self.tmp, "plain.md")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("# no stamp here\n")
        self.assertIsNone(provenance.check(path, self.feeds))


if __name__ == "__main__":
    unittest.main()
