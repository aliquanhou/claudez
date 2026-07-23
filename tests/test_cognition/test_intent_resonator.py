"""Test IntentResonator — 0 LLM, fully deterministic."""
import sys, os, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from agent.cognition import IntentResonator, BehavioralSnapshot


class TestIntentResonator:
    def setup_method(self):
        self.r = IntentResonator(window_size=10, ttl_seconds=300, max_history=50)

    def test_feed_and_get_intent(self):
        for i in range(3):
            self.r.feed(BehavioralSnapshot(timestamp=time.time(), chars_typed=10 + i * 10))
        intent = self.r.get_intent()
        assert intent is not None

    def test_ttl_purge(self):
        self.r._history = [
            BehavioralSnapshot(timestamp=time.time() - 600, chars_typed=5),
            BehavioralSnapshot(timestamp=time.time(), chars_typed=10),
        ]
        self.r._purge_expired()
        assert len(self.r._history) == 1

    def test_max_history_lru(self):
        r = IntentResonator(window_size=20, max_history=3)
        for i in range(10):
            r.feed(BehavioralSnapshot(timestamp=time.time(), chars_typed=i))
        assert len(r._history) == 3

    def test_persist_and_load(self):
        import tempfile, json
        now = time.time()
        self.r._history = [
            BehavioralSnapshot(timestamp=now - 1, chars_typed=10),
            BehavioralSnapshot(timestamp=now, chars_typed=20),
        ]
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "intents.json")
            self.r.persist(path)
            r2 = IntentResonator(ttl_seconds=300)
            r2.load(path)
            assert len(r2._history) == 2
