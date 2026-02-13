from pathlib import Path

from gbb.git import parse_branches, parse_tracking_status, parse_worktrees


WORKTREE_OUTPUT = """\
worktree /Users/mk/projects/app
HEAD abc1234def5678901234567890abcdef12345678
branch refs/heads/main

worktree /Users/mk/projects/app-feature
HEAD def5678abc1234901234567890abcdef12345678
branch refs/heads/feature-x

"""


def test_parse_worktrees():
    result = parse_worktrees(WORKTREE_OUTPUT)
    assert len(result) == 2
    assert result["main"].path == Path("/Users/mk/projects/app")
    assert result["main"].head == "abc1234"
    assert result["feature-x"].path == Path("/Users/mk/projects/app-feature")


def test_parse_worktrees_bare():
    output = "worktree /Users/mk/projects/app\nHEAD abc1234\nbranch (detached)\n\n"
    result = parse_worktrees(output)
    assert len(result) == 0


FOR_EACH_REF_OUTPUT = """\
main abc1234 1707000000
feature-x def5678 1707100000
old-branch 999aaaa 1600000000
"""


def test_parse_branches():
    result = parse_branches(FOR_EACH_REF_OUTPUT)
    assert len(result) == 3
    assert result["main"].commit == "abc1234"
    assert result["main"].name == "main"
    assert result["feature-x"].timestamp == 1707100000


def test_parse_branches_has_deletable_fields():
    result = parse_branches(FOR_EACH_REF_OUTPUT)
    branch = result["main"]
    assert branch.deletable is False
    assert branch.delete_reason is None


TRACKING_OUTPUT = """\
main
feature-x [gone]
dev [ahead 2]
stale [gone]
"""


def test_parse_tracking_status():
    result = parse_tracking_status(TRACKING_OUTPUT)
    assert result["feature-x"] is True
    assert result["stale"] is True
    assert result.get("main") is False or result.get("main") is None
    assert result.get("dev") is False or result.get("dev") is None
