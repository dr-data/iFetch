import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))

from ifetch.cli import parse_selection  # noqa: E402


def test_parse_selection_all():
    assert parse_selection("all", 3) == [0, 1, 2]


def test_parse_selection_numbers():
    assert parse_selection("3,1,3", 4) == [0, 2]


def test_parse_selection_invalid_token():
    with pytest.raises(ValueError, match="Invalid selection token"):
        parse_selection("1,a", 3)


def test_parse_selection_out_of_range():
    with pytest.raises(ValueError, match="Selection out of range"):
        parse_selection("5", 3)
