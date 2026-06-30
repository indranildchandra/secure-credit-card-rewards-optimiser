"""Offline tests for config.py helpers."""

import config


def test_safe_int_valid():
    assert config._safe_int("5", 180) == 5
    assert config._safe_int(7, 180) == 7


def test_safe_int_falls_back_on_garbage():
    assert config._safe_int("abc", 180) == 180
    assert config._safe_int(None, 180) == 180
    assert config._safe_int("", 42) == 42
