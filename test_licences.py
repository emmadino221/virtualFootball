import os
import tempfile
import unittest

from ext_sessions import Sessions
from licences import Licences, key_hash

KEY = "vf_" + "a" * 32


class Clock:
    def __init__(self): self.now = 1_800_000_000.0
    def __call__(self): return self.now


class LicenceTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.dir.name, "matches.db")
        self.clock = Clock()
        self.licences = Licences(self.db, clock=self.clock)

    def tearDown(self):
        self.dir.cleanup()

    def test_grant_expire_revoke_and_survive_a_restart(self):
        self.assertFalse(self.licences.is_valid(KEY))
        self.licences.grant(KEY, "member@example.test", self.clock.now + 30 * 86400)
        self.assertTrue(self.licences.is_valid(KEY))
        self.assertTrue(Licences(self.db, clock=self.clock).is_valid(KEY))   # stored, not only cached
        self.clock.now += 31 * 86400
        self.assertFalse(self.licences.is_valid(KEY))                         # expired
        self.licences.grant(KEY, "member@example.test", self.clock.now + 86400)
        self.assertTrue(self.licences.is_valid(KEY))                          # renewed
        self.licences.revoke(KEY)
        self.assertFalse(self.licences.is_valid(KEY))
        self.assertFalse(Licences(self.db, clock=self.clock).is_valid(KEY))

    def test_only_the_hash_is_stored(self):
        self.licences.grant(KEY, "member@example.test", self.clock.now + 60)
        with open(self.db, "rb") as f:
            raw = f.read()
        self.assertNotIn(KEY.encode(), raw)
        self.assertIn(key_hash(KEY).encode(), raw)

    def test_bad_grants_are_refused(self):
        with self.assertRaises(ValueError): self.licences.grant("short", "x", self.clock.now + 60)
        with self.assertRaises(ValueError): self.licences.grant(KEY, "x", self.clock.now - 1)
        self.assertFalse(self.licences.is_valid(None))

    def test_sessions_accept_environment_and_issued_keys(self):
        sessions = Sessions(["env-key-1234"], extra_valid=self.licences.is_valid)
        self.assertTrue(sessions.valid("env-key-1234"))
        self.assertFalse(sessions.valid(KEY))
        self.licences.grant(KEY, "member@example.test", self.clock.now + 60)
        self.assertTrue(sessions.valid(KEY))


if __name__ == "__main__":
    unittest.main()
