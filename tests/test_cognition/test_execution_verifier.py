"""Test ExecutionVerifier — 6 stage deterministic verification."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from agent.cognition.execution_verifier import ExecutionVerifier, Plan, WorkspaceSnapshot, FileChange


class TestExecutionVerifier:
    def setup_method(self):
        self.ev = ExecutionVerifier()

    def test_no_changes_fail(self):
        plan = Plan(id="1", description="test", steps=[])
        report = self.ev.verify(plan, WorkspaceSnapshot(root_path="."), WorkspaceSnapshot(root_path="."))
        assert not report.success

    def test_file_change_matching(self):
        plan = Plan(id="2", description="edit a.py", steps=[{"action": "edit", "file": "a.py", "description": "x"}], target_files=["a.py"])
        before = WorkspaceSnapshot(root_path=".", files=["a.py"])
        after = WorkspaceSnapshot(root_path=".", files=["a.py", "b.py"])
        report = self.ev.verify(plan, before, after, execution_log=["executed"])
        assert report.matched_steps >= 1

    def test_deviation_scoring(self):
        plan = Plan(id="3", description="narrow", steps=[{"action": "read", "file": "a.py", "description": "x"}], target_files=["a.py"])
        before = WorkspaceSnapshot(root_path=".", files=["a.py"])
        after = WorkspaceSnapshot(root_path=".", files=["a.py", "b.py", "c.py"])
        report = self.ev.verify(plan, before, after, execution_log=[])
        assert report.deviation_score >= 0.5
