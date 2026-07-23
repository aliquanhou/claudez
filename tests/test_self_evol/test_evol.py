"""Test self_evol modules."""
import sys, os, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from agent.self_evol.nudge import NudgeEngine
from agent.self_evol.review import BackgroundReviewer
from agent.self_evol.compressor import FourStageCompressor


class TestNudgeEngine:
    def setup_method(self):
        self.e = NudgeEngine()

    def test_tool_error_detection(self):
        nudges = self.e.analyze({"total_tokens": 5000, "max_context_tokens": 32000},
                                 ["bash", "bash", "bash"], [], 0, 10)
        assert any(n.key == "tool_error_bash" for n in nudges)

    def test_token_high_detection(self):
        nudges = self.e.analyze({"total_tokens": 25000, "max_context_tokens": 32000},
                                 [], [], 0, 10)
        assert any(n.key == "token_high" for n in nudges)

    def test_long_run_detection(self):
        nudges = self.e.analyze({"total_tokens": 1000, "max_context_tokens": 32000},
                                 [], [], 0, 400)
        assert any(n.key == "long_run" for n in nudges)

    def test_prompt_block(self):
        nudges = self.e.analyze({"total_tokens": 25000, "max_context_tokens": 32000},
                                 ["bash", "bash", "bash"], [], 0, 10)
        block = self.e.get_nudge_prompt_block(nudges)
        assert block.startswith("## 优化建议")


class TestBackgroundReviewer:
    def test_review_interval(self):
        br = BackgroundReviewer(3)
        assert br.check(1) is None
        assert br.check(2) is None
        assert br.check(3) is not None

    def test_critical_review(self):
        br = BackgroundReviewer(1)
        note = br.check(1, "goal", tool_error_count=6)
        assert note.severity == "critical"


class TestFourStageCompressor:
    def test_compresses_long_tool_results(self):
        fc = FourStageCompressor()
        msgs = [{"role": "user", "content": "goal", "timestamp": 0.0}]
        for i in range(12):
            msgs.append({"role": "tool", "content": "x" * 600, "timestamp": float(i + 1)})
        msgs.append({"role": "user", "content": "latest", "timestamp": 13.0})
        result = fc.compress(msgs)
        shortened = [m for m in result if m.get("content") == "[结果较长，已压缩]"]
        assert len(shortened) > 0

    def test_llm_summarize(self):
        fc = FourStageCompressor(llm_summarize_fn=lambda t: "Summary.")
        msgs = [{"role": "user" if i == 0 else "assistant", "content": f"m{i}", "timestamp": float(i)}
                for i in range(20)]
        result = fc.compress(msgs)
        assert len(result) > 0
