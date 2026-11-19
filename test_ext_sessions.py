import unittest

from ext_sessions import Sessions, clean_state, validate_command

A, B = "key-member-a-0001", "key-member-b-0002"


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.sessions = Sessions([A, B], clock=self.clock)

    def test_each_licence_has_its_own_state_and_commands(self):
        self.sessions.sync(A, {"botEnabled": True, "bettingMode": "O25", "totalProfit": 1500})
        self.sessions.sync(B, {"botEnabled": False, "bettingMode": "GG"})
        self.sessions.queue(A, "STOP")
        self.assertEqual(self.sessions.sync(B, {}), [])               # B never receives A's Stop
        self.assertEqual(self.sessions.sync(A, {}), [{"type": "STOP"}])
        self.assertEqual(self.sessions.sync(A, {}), [])               # delivered once
        self.assertEqual(self.sessions.status(A)["state"]["bettingMode"], "O25")
        self.assertEqual(self.sessions.status(B)["state"]["bettingMode"], "GG")
        self.assertEqual(self.sessions.status(A)["delivered"][0]["type"], "STOP")

    def test_online_and_pending_reflect_the_last_sync(self):
        self.assertFalse(self.sessions.status(A)["online"])
        self.sessions.sync(A, {})
        self.assertTrue(self.sessions.status(A)["online"])
        self.clock.now += 16
        self.assertFalse(self.sessions.status(A)["online"])
        self.sessions.queue(A, "STAKE", "250")
        pending = self.sessions.status(A)["pending"]
        self.assertEqual((pending[0]["type"], pending[0]["value"]), ("STAKE", 250.0))

    def test_newer_commands_replace_undelivered_ones(self):
        self.sessions.queue(A, "START")
        self.sessions.queue(A, "STOP")                 # Stop cancels the queued Start
        self.sessions.queue(A, "MODE", "ou")
        self.sessions.queue(A, "MODE", "O25")
        self.sessions.queue(A, "RESET")
        self.assertEqual(self.sessions.sync(A, {}), [{"type": "STOP"}, {"type": "MODE", "value": "O25"}, {"type": "RESET"}])

    def test_commands_are_validated(self):
        for kind, value in [("STAKE", "0"), ("STAKE", "abc"), ("TP", -5), ("SL", 1e9), ("MODE", "TC2"), ("DELETE", None)]:
            with self.assertRaises(ValueError):
                validate_command(kind, value)
        self.assertEqual(validate_command("tp", "1200.555"), {"type": "TP", "value": 1200.56})

    def test_reported_state_is_cleaned(self):
        state = clean_state({"botEnabled": "yes", "bettingMode": "TC2", "baseStake": "150", "minOdds": float("nan"),
                             "pendingBet": {"stake": 300, "week": "Week 12", "mode": "O25", "roundId": "x"},
                             "evil": "<script>", "extensionVersion": "3.4"})
        self.assertNotIn("botEnabled", state)
        self.assertNotIn("bettingMode", state)
        self.assertNotIn("minOdds", state)
        self.assertNotIn("evil", state)
        self.assertEqual(state["baseStake"], 150.0)
        self.assertEqual(state["pendingBet"], {"stake": 300.0, "week": "Week 12", "mode": "O25", "roundId": "x",
                                               "odds": None, "picks": [], "placedAt": None})
        self.assertIsNone(clean_state({"pendingBet": None})["pendingBet"])

    def test_telegram_chats_reach_only_their_own_extension(self):
        self.sessions.sync(A, {}, chat_id="111")
        self.sessions.sync(B, {}, chat_id="222")
        self.assertEqual(self.sessions.keys_for_chat("111"), [A])
        self.assertEqual(self.sessions.keys_for_chat("999"), [])
        self.assertEqual(self.sessions.keys_for_chat("999", admin=True), [A, B])

    def test_unknown_keys_are_not_valid(self):
        self.assertTrue(self.sessions.valid(A))
        self.assertFalse(self.sessions.valid("other"))
        self.assertFalse(self.sessions.valid(None))

    def test_queue_has_a_limit(self):
        for _ in range(3):
            self.sessions.queue(A, "RESET")
        self.assertEqual(len(self.sessions.status(A)["pending"]), 1)


if __name__ == "__main__":
    unittest.main()
