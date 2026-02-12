from pathlib import Path

from gbb.git import parse_worktrees, Worktree


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
