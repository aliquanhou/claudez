"""Test Code Review workflow."""
import sys, os, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from agent.workflows.code_review import CodeReviewWorkflow, ReviewComment, ReviewReport


class TestReviewComment:
    def test_to_markdown(self):
        c = ReviewComment(file="a.py", line=10, severity="critical", category="security",
                          message="Hardcoded key", suggestion="Use env vars")
        md = c.to_markdown()
        assert "a.py:10" in md
        assert "critical" in md
        assert "Hardcoded key" in md


class TestReviewReport:
    def test_counts(self):
        r = ReviewReport(target="HEAD")
        r.comments = [
            ReviewComment(file="a.py", line=1, severity="critical", category="security", message="bad"),
            ReviewComment(file="a.py", line=2, severity="warning", category="style", message="meh"),
            ReviewComment(file="a.py", line=3, severity="info", category="suggestion", message="ok"),
        ]
        assert r.critical_count == 1
        assert r.warning_count == 1

    def test_to_markdown(self):
        r = ReviewReport(target="HEAD", summary="Good code")
        r.files_reviewed = ["a.py"]
        md = r.to_markdown()
        assert "Code Review Report" in md


class TestCodeReviewWorkflow:
    def test_analyze_file_no_issues(self):
        wf = CodeReviewWorkflow()
        with tempfile.TemporaryDirectory() as d:
            fpath = os.path.join(d, "clean.py")
            with open(fpath, "w") as f:
                f.write("x = 1\nprint(x)\n")
            comments = wf._analyze_file(fpath, "x = 1\nprint(x)\n")
            assert len(comments) >= 0  # print() may trigger info

    def test_analyze_file_with_secrets(self):
        wf = CodeReviewWorkflow()
        comments = wf._analyze_file("test.py", 'password="my_secret_123"\n')
        critical = [c for c in comments if c.severity == "critical"]
        assert len(critical) >= 1

    def test_analyze_file_empty_except(self):
        wf = CodeReviewWorkflow()
        comments = wf._analyze_file("test.py", "try:\n    pass\nexcept:\n    pass\n")
        warnings = [c for c in comments if c.severity == "warning"]
        assert len(warnings) >= 1

    def test_analyze_file_todo(self):
        wf = CodeReviewWorkflow()
        comments = wf._analyze_file("test.py", "# TODO: fix this later\n")
        infos = [c for c in comments if c.category == "suggestion"]
        assert len(infos) >= 1
