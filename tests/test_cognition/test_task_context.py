"""Test TaskContext / TaskManager."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from agent.cognition import TaskManager, TaskPhase


class TestTaskManager:
    def setup_method(self):
        self.tm = TaskManager()

    def test_create_task(self):
        task = self.tm.create_task("test goal")
        assert task is not None
        assert task.user_goal == "test goal"
        assert task.current_phase == TaskPhase.INTENT_CLARIFY

    def test_phase_transition(self):
        task = self.tm.create_task("test")
        self.tm.transition_phase(task.task_id, TaskPhase.ANALYSIS)
        t = self.tm.get_current_task()
        assert t.current_phase == TaskPhase.ANALYSIS
        assert t.phases[-1].phase == TaskPhase.ANALYSIS

    def test_add_decision(self):
        task = self.tm.create_task("test")
        self.tm.add_decision(task.task_id, "made a decision", "because...")
        assert len(task.decisions) == 1

    def test_get_summary(self):
        task = self.tm.create_task("test goal")
        summary = self.tm.get_summary()
        assert "test goal" in summary
