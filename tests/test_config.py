"""Offline tests for config.py helpers."""

import config


def test_safe_int_valid():
    assert config._safe_int("5", 180) == 5
    assert config._safe_int(7, 180) == 7


def test_safe_int_falls_back_on_garbage():
    assert config._safe_int("abc", 180) == 180
    assert config._safe_int(None, 180) == 180
    assert config._safe_int("", 42) == 42


def test_is_ollama_cloud_matches_cloud_host_and_subdomain():
    # The known cloud host (and its subdomains) is the ONLY place a key attaches.
    assert config._is_ollama_cloud("https://ollama.com") is True
    assert config._is_ollama_cloud("https://ollama.com/api/chat") is True
    assert config._is_ollama_cloud("https://api.ollama.com") is True


def test_is_ollama_cloud_rejects_local_and_private_hosts():
    # Loopback, LAN and private (RFC1918) daemons must stay credential-free.
    for base in (
        "http://localhost:11434",
        "http://127.0.0.1:11434",
        "http://192.168.1.10:11434",
        "http://10.0.0.5:11434",
        "http://ollama.local:11434",
        "",
    ):
        assert config._is_ollama_cloud(base) is False, base


def test_is_ollama_cloud_not_fooled_by_substring_lookalikes():
    # Hostname parsing (not substring scanning) blocks masquerade attempts.
    assert config._is_ollama_cloud("http://ollama.com.attacker.net") is False
    assert config._is_ollama_cloud("http://localhost.ollama.com.evil/") is False
    assert config._is_ollama_cloud("http://notollama.com") is False
