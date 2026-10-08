"""Throwaway: proves a red CI blocks a merge. This branch is never merged."""


def test_deliberately_red():
    raise AssertionError("proof only: this must turn 'tests passed' red")
