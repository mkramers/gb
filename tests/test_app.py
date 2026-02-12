import time
from pathlib import Path

from gbb.app import format_age, format_ahead_behind, shorten_path


def test_format_ahead_behind():
    assert str(format_ahead_behind(0, 0)) == ""
    assert str(format_ahead_behind(3, 0)) == "↑3"
    assert str(format_ahead_behind(0, 2)) == "↓2"
    assert str(format_ahead_behind(5, 1)) == "↑5↓1"


def test_format_age():
    now = int(time.time())
    assert format_age(now - 300) == "5m"
    assert format_age(now - 7200) == "2h"
    assert format_age(now - 172800) == "2d"
    assert format_age(now - 1209600) == "2w"
