"""Shared test fixtures: a fixed clock and a throwaway synthetic day."""
import os
import shutil
import tempfile
import unittest
from datetime import datetime

from flow_desk import synth

CLOCK = datetime(2026, 3, 11, 7, 30)     # a Wednesday morning, after the publish hour


class FeedCase(unittest.TestCase):
    """Each test gets its own synthetic feed directory, pinned to CLOCK."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="flow_desk_test_")
        self.feeds = os.path.join(self.tmp, "feeds")
        self.out = os.path.join(self.tmp, "out")
        self.truth = synth.generate(self.feeds, seed=7, now=CLOCK)
        self._env = os.environ.pop("DISCORD_WEBHOOK_URL", None)   # tests never send

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)
        if self._env is not None:
            os.environ["DISCORD_WEBHOOK_URL"] = self._env

    def path(self, layer):
        from flow_desk import config
        return os.path.join(self.feeds, config.LAYER_FILES[layer])
