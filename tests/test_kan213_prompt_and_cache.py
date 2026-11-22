"""KAN-213: stable prompt prefix and cache hit-rate logging."""
from aether_os.core.llm.client import build_full_prompt


def test_prompt_prefix_is_identical_for_two_files_in_one_run():
    ctx = {"spec": "Task app", "arch": {"b": 1, "a": 2}}
    p1 = build_full_prompt("Fix file A.tsx", ctx)
    p2 = build_full_prompt("Fix file B.tsx", {"arch": {"a": 2, "b": 1}, "spec": "Task app"})
    cut = p1.index("Fix file")
    assert p2[:cut] == p1[:cut] and p1 != p2
    assert build_full_prompt("x", None) == "x"


def test_cache_hit_rate_is_logged(caplog):
    from aether_os.core.llm import cache

    cache._stats.update(hits=0, misses=0)
    with caplog.at_level("INFO", logger=cache.logger.name):
        for i in range(10):
            cache._record(i < 3)
    assert "hit rate: 3/10 = 30%" in caplog.text
