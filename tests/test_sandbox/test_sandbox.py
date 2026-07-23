"""Test sandbox modules."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from agent.sandbox.danger_score import DangerScore, score_command
from agent.sandbox.temp_dir import TempDirSandbox


class TestDangerScore:
    def test_rm_rf_critical(self):
        assert DangerScore.score("rm -rf /") >= 80

    def test_safe_command_low(self):
        assert DangerScore.score("ls -la") == 0

    def test_sudo_medium(self):
        assert DangerScore.score("sudo apt install") >= 20

    def test_fork_bomb_critical(self):
        assert DangerScore.score(":(){ :|:& };:") >= 80

    def test_risk_levels(self):
        assert DangerScore.get_risk_level(85) == "CRITICAL"
        assert DangerScore.get_risk_level(50) == "HIGH"
        assert DangerScore.get_risk_level(20) == "MEDIUM"
        assert DangerScore.get_risk_level(5) == "LOW"

    def test_risk_advice(self):
        advice = DangerScore.get_risk_advice(90, "rm -rf /")
        assert "危险" in advice or "拦截" in advice

    def test_score_command_shorthand(self):
        assert score_command("rm -rf /") >= 80


class TestTempDirSandbox:
    def test_create_and_resolve(self):
        with TempDirSandbox() as sb:
            assert sb.root is not None
            assert os.path.exists(sb.root)
            resolved = sb.resolve("test.txt")
            assert resolved.endswith("test.txt")
            assert resolved.startswith(sb.root)

    def test_path_escape_blocked(self):
        import pytest
        with TempDirSandbox() as sb:
            try:
                sb.resolve("../etc/passwd")
                assert False, "Should have raised"
            except PermissionError:
                pass

    def test_cleanup(self):
        sb = TempDirSandbox()
        root = sb.root
        assert os.path.exists(root)
        sb.cleanup()
        assert not os.path.exists(root)
