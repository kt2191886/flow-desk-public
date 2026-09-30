"""The publish gate catches each class of private string, and passes a clean tree.

Every planted string below is assembled from pieces at run time. Spelled out
literally, this test file would trip the very gate it tests.
"""
import io
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
import public_gate  # noqa: E402

PLANTS = {
    "home_path": "/" + "Users" + "/someone/project",
    "long_number": "account " + "1234" * 2 + "9",
    "private_ip": "192." + "168.1.20",
    "tailnet_host": "box.example" + ".ts" + ".net",
    "email": "someone" + "@" + "mail.example",
    "webhook": "discord" + ".com/api/" + "webhooks/1/abc",
    "key_assignment": "api_key" + " = " + "'abcdEFGH1234wxyz'",
    "money_amount": "made " + "$" + "500 today",
    "option_symbol": "-ZZXY" + "260417" + "P50",
    "url": "https" + "://not-allowed.example/page",
}


class PublicGate(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="gate_test_")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def _write(self, name, text):
        path = os.path.join(self.root, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        return path

    def _main(self, *argv):
        with redirect_stdout(io.StringIO()):
            return public_gate.main(list(argv))

    def _rules(self, blocklist=None):
        hits, _ = public_gate.scan(self.root, blocklist)
        return {h.split("[")[1].split("]")[0] for h in hits}

    def test_clean_tree_passes(self):
        self._write("a.py", "x = 1  # see " + public_gate.URL_ALLOW[1] + "\n")
        self.assertEqual(self._main(self.root), 0)

    def test_each_generic_rule_fires(self):
        for rule, text in PLANTS.items():
            shutil.rmtree(self.root)
            os.makedirs(self.root)
            self._write("notes.md", "line one\n" + text + "\n")
            self.assertIn(rule, self._rules(), rule)
            self.assertEqual(self._main(self.root), 1, rule)

    def test_blocked_file_kinds_and_directories(self):
        self._write("flow.py" + ".bak" + ".1", "x")
        self._write("store" + ".db", "x")
        self._write(os.path.join("logs", "run.txt"), "x")
        self.assertEqual(self._rules(), {"blocked_file", "blocked_dir"})

    def test_generated_output_is_scanned_too(self):
        self._write(os.path.join("out", "debrief.md"), PLANTS["home_path"])
        self.assertIn("home_path", self._rules())

    def test_external_blocklist_forms(self):
        bl = self._write("bl.txt", "# private\nticker:ABCD\nre:\\bsecret-\\d+\\b\nAcme Broker\n")
        rules = public_gate.load_blocklist(bl)
        os.remove(bl)
        self._write("a.md", "ABCD rallied\n")
        self.assertEqual(self._rules(rules), {"blocklist"})
        self._write("a.md", "ABCDE and abcd are different words\n")
        self.assertEqual(self._rules(rules), set())
        self._write("a.md", "our acme broker export\n")
        self.assertEqual(self._rules(rules), {"blocklist"})
        self._write("a.md", "id secret-42\n")
        self.assertEqual(self._rules(rules), {"blocklist"})

    def test_require_blocklist_fails_closed(self):
        self._write("a.py", "x = 1\n")
        self.assertEqual(self._main(self.root, "--require-blocklist",
                                    "--blocklist", os.path.join(self.root, "nope")), 2)


if __name__ == "__main__":
    unittest.main()
