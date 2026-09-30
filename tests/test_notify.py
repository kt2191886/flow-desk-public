"""The sender: no URL means no send, and RED pages do not repeat themselves."""
import io
import json
import os
import unittest
from contextlib import redirect_stdout
from datetime import timedelta
from unittest import mock

from flow_desk import config
from flow_desk.notify import ENV_VAR, deliver, sender, should_push

from .helpers import CLOCK, FeedCase

# A reserved, non-routable test host. Assembled so no real endpoint is ever spelled out.
TEST_URL = "https://example.invalid/" + "hook"
PAYLOAD = {"title": "Morning brief", "body": "Integrity GREEN.", "reds": []}


class _Resp(object):
    status = 204

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class ShouldPush(unittest.TestCase):
    def test_new_red_set_pushes(self):
        self.assertEqual(should_push(["a"], {}, CLOCK), (True, "new"))
        self.assertEqual(should_push(["a", "b"], {"reds": ["a"]}, CLOCK), (True, "new"))

    def test_same_set_inside_window_stays_quiet(self):
        state = {"reds": ["a"], "last_push_ts": (CLOCK - timedelta(hours=1)).isoformat()}
        self.assertEqual(should_push(["a"], state, CLOCK), (False, None))

    def test_same_set_after_window_is_a_heartbeat(self):
        hours = config.RED_REPING_HOURS
        state = {"reds": ["a"], "last_push_ts": (CLOCK - timedelta(hours=hours)).isoformat()}
        self.assertEqual(should_push(["a"], state, CLOCK), (True, "heartbeat"))

    def test_clearing_sends_one_recovery_note(self):
        self.assertEqual(should_push([], {"reds": ["a"]}, CLOCK), (True, "recovered"))
        self.assertEqual(should_push([], {"reds": []}, CLOCK), (False, None))


class Deliver(FeedCase):
    def setUp(self):
        super(Deliver, self).setUp()
        os.makedirs(self.out)

    def test_without_url_nothing_is_sent_and_it_says_so(self):
        with mock.patch.object(sender.urllib.request, "urlopen") as net:
            got = deliver(PAYLOAD, self.out, CLOCK)
        net.assert_not_called()
        self.assertFalse(got["sent"])
        self.assertIn("not set", got["detail"])

    def test_with_url_posts_once_with_content(self):
        with mock.patch.dict(os.environ, {ENV_VAR: TEST_URL}), \
                mock.patch.object(sender.urllib.request, "urlopen", return_value=_Resp()) as net:
            got = deliver(PAYLOAD, self.out, CLOCK)
        self.assertTrue(got["sent"])
        self.assertEqual(net.call_count, 1)
        req = net.call_args[0][0]
        self.assertEqual(req.full_url, TEST_URL)
        self.assertIn("Morning brief", json.loads(req.data.decode("utf-8"))["content"])

    def test_url_is_never_written_to_disk(self):
        with mock.patch.dict(os.environ, {ENV_VAR: TEST_URL}), \
                mock.patch.object(sender.urllib.request, "urlopen", return_value=_Resp()):
            deliver(PAYLOAD, self.out, CLOCK)
        for name in os.listdir(self.out):
            with open(os.path.join(self.out, name), encoding="utf-8") as fh:
                self.assertNotIn("example.invalid", fh.read(), name)

    def test_plain_http_url_is_refused(self):
        with mock.patch.dict(os.environ, {ENV_VAR: TEST_URL.replace("https", "http")}), \
                mock.patch.object(sender.urllib.request, "urlopen") as net, \
                redirect_stdout(io.StringIO()) as log:
            got = deliver(PAYLOAD, self.out, CLOCK)
        net.assert_not_called()
        self.assertFalse(got["sent"])
        self.assertIn("refusing to send", log.getvalue())

    def test_dead_webhook_does_not_raise_and_is_not_a_delivery(self):
        with mock.patch.dict(os.environ, {ENV_VAR: TEST_URL}), \
                mock.patch.object(sender.urllib.request, "urlopen", side_effect=OSError("down")), \
                redirect_stdout(io.StringIO()) as log:
            got = deliver(PAYLOAD, self.out, CLOCK)
        self.assertFalse(got["sent"])
        self.assertIn("post failed", log.getvalue())

    def test_long_message_is_truncated_to_the_limit(self):
        big = dict(PAYLOAD, body="x" * (config.NOTIFY_MAX_CHARS * 2))
        with mock.patch.dict(os.environ, {ENV_VAR: TEST_URL}), \
                mock.patch.object(sender.urllib.request, "urlopen", return_value=_Resp()) as net:
            deliver(big, self.out, CLOCK)
        content = json.loads(net.call_args[0][0].data.decode("utf-8"))["content"]
        self.assertEqual(len(content), config.NOTIFY_MAX_CHARS)

    def test_repeated_red_pages_once(self):
        red = {"title": "Integrity RED", "body": "- x", "reds": ["staleness:oi_change"]}
        with mock.patch.dict(os.environ, {ENV_VAR: TEST_URL}), \
                mock.patch.object(sender.urllib.request, "urlopen", return_value=_Resp()) as net:
            first = deliver(red, self.out, CLOCK)
            second = deliver(red, self.out, CLOCK + timedelta(minutes=30))
            cleared = deliver(PAYLOAD, self.out, CLOCK + timedelta(hours=1))
        self.assertEqual((first["kind"], second["kind"], cleared["kind"]),
                         ("new", "quiet", "recovered"))
        self.assertEqual(net.call_count, 2)


if __name__ == "__main__":
    unittest.main()
