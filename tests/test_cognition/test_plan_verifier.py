"""Test PlanVerifier — 6 deterministic validation dimensions."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from agent.cognition.plan_verifier import PlanVerifier, Plan, PlanStep, Verdict


class TestPlanVerifier:
    def setup_method(self):
        self.pv = PlanVerifier()

    def test_empty_steps_fail(self):
        plan = Plan(id="1", description="empty", steps=[])
        report = self.pv.verify(plan)
        assert report.verdict == Verdict.FAIL
        assert report.score == 0

    def test_valid_plan_pass(self):
        plan = Plan(id="2", description="valid", steps=[
            PlanStep(action="write", file="a.py", description="create"),
        ])
        report = self.pv.verify(plan)
        assert report.verdict != Verdict.FAIL

    def test_file_conflict_warns(self):
        plan = Plan(id="3", description="conflict", steps=[
            PlanStep(action="edit", file="a.py", description="step1"),
            PlanStep(action="edit", file="a.py", description="step2"),
        ])
        report = self.pv.verify(plan)
        assert len(report.warnings) > 0

    def test_too_many_steps_penalty(self):
        steps = [PlanStep(action="read", file=f"f{i}.py", description=f"step{i}") for i in range(12)]
        plan = Plan(id="4", description="many steps", steps=steps)
        report = self.pv.verify(plan)
        assert report.score < 100

    def test_compare_ranking(self):
        plans = [
            Plan(id="p1", description="good", steps=[PlanStep(action="read", file="a.py", description="x")]),
            Plan(id="p2", description="empty", steps=[]),
        ]
        results = self.pv.compare(plans)
        assert results[0][0].id == "p1"
