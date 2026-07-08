import pytest

from shogi_mcp import presets


def test_default_level_exists():
    assert presets.DEFAULT_LEVEL in presets.PRESETS


def test_get_returns_matching_level():
    d = presets.get(3)
    assert d.level == 3


def test_get_rejects_invalid_level():
    with pytest.raises(ValueError):
        presets.get(0)
    with pytest.raises(ValueError):
        presets.get(6)


def test_levels_increase_in_strength():
    levels = [presets.get(i) for i in range(1, 6)]
    node_limits = [d.nodes_limit if d.nodes_limit > 0 else float("inf") for d in levels]
    byoyomis = [d.byoyomi_ms for d in levels]
    assert node_limits == sorted(node_limits)
    assert byoyomis == sorted(byoyomis)
