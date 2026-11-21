"""
Guardian file-integrity baseline is tied to the deployed build.

Regression: the baseline was written to Redis on first boot only and the Redis volume outlives image rebuilds, so every
legitimate deploy raised `TAMPER DETECTED` at critical. A new build must re-establish the baseline; a file changing while
the same build runs (also across a restart) must still be detected.
"""
import asyncio
import json

import pytest

from aether_os.core.guardian import build_identity as bi
from aether_os.core.guardian import threat_detector as td


class FakeRedis:
    """The subset of redis.asyncio (decode_responses=True) the detector uses."""

    def __init__(self):
        self.kv = {}
        self.hashes = {}
        self.ttl = {}

    async def get(self, k):
        return self.kv.get(k)

    async def set(self, k, v, ex=None):
        self.kv[k] = v

    async def hget(self, k, f):
        return self.hashes.get(k, {}).get(f)

    async def hset(self, k, f, v):
        self.hashes.setdefault(k, {})[f] = v

    async def hsetnx(self, k, f, v):
        h = self.hashes.setdefault(k, {})
        if f in h:
            return 0
        h[f] = v
        return 1

    async def expire(self, k, s):
        self.ttl[k] = s


@pytest.fixture
def tree(tmp_path, monkeypatch):
    """A fake package root with two critical files; the detector is pointed at it."""
    root = tmp_path / "pkg"
    (root / "core").mkdir(parents=True)
    files = [root / "core" / "db.py", root / "core" / "models.py"]
    for f in files:
        f.write_text(f"# {f.name} v1\n")
    manifest = root / bi.MANIFEST_NAME
    monkeypatch.setattr(td, "_PACKAGE_ROOT", root)
    monkeypatch.setattr(td, "_CRITICAL_FILES", files)
    monkeypatch.setattr(td, "_MANIFEST_PATH", manifest)
    monkeypatch.delenv(bi.BUILD_ID_ENV, raising=False)
    return root, files, manifest


def _use_redis(monkeypatch, redis):
    async def fake_get_redis():
        return redis
    monkeypatch.setattr(td, "_get_redis", fake_get_redis)


def _build(root, manifest):
    """What the Dockerfile does at image build time."""
    bi.write_manifest(manifest, root)


def _boot_and_check(redis_or_none, monkeypatch):
    _use_redis(monkeypatch, redis_or_none)
    det = td.ThreatDetector()

    async def go():
        await det.load_or_create_baseline()
        return await det.check_file_integrity()
    return asyncio.run(go())


def _tamper_events(events):
    return [e for e in events if e["event_type"] == "file_tamper"]


def test_same_build_file_changed_is_detected_even_after_restart(tree, monkeypatch):
    root, files, manifest = tree
    redis = FakeRedis()
    _build(root, manifest)
    assert _tamper_events(_boot_and_check(redis, monkeypatch)) == []

    files[0].write_text("# db.py backdoored\n")
    # Each _boot_and_check is a fresh detector, i.e. a container restart of the same build: it must not launder it.
    for _ in range(2):
        events = _tamper_events(_boot_and_check(redis, monkeypatch))
        assert [e["detail"]["file"] for e in events] == ["db.py"]
        assert events[0]["severity"] == "critical"


def test_same_build_env_id_restart_with_rewritten_manifest_still_detected(tree, monkeypatch):
    """With AETHER_BUILD_ID (image config, not writable from inside the container), rewriting the manifest too does
    not re-baseline: the build's first-stored hashes win."""
    root, files, manifest = tree
    monkeypatch.setenv(bi.BUILD_ID_ENV, "abc123")
    redis = FakeRedis()
    _build(root, manifest)
    assert _tamper_events(_boot_and_check(redis, monkeypatch)) == []

    files[0].write_text("# db.py backdoored\n")
    _build(root, manifest)  # attacker regenerates the manifest
    assert [e["detail"]["file"] for e in _tamper_events(_boot_and_check(redis, monkeypatch))] == ["db.py"]


def test_new_build_reestablishes_baseline_without_alert(tree, monkeypatch, caplog):
    root, files, manifest = tree
    redis = FakeRedis()
    _build(root, manifest)
    assert _tamper_events(_boot_and_check(redis, monkeypatch)) == []
    first_build = redis.kv[td._CURRENT_BUILD_KEY]

    # Legitimate deploy: code changes, image rebuilt (new manifest), Redis volume kept.
    files[0].write_text("# db.py v2\n")
    _build(root, manifest)
    with caplog.at_level("WARNING"):
        assert _tamper_events(_boot_and_check(redis, monkeypatch)) == []
    second_build = redis.kv[td._CURRENT_BUILD_KEY]
    assert second_build != first_build
    assert redis.ttl == {td._BUILD_BASELINE_PREFIX + first_build: td._OLD_BUILD_TTL_SECONDS}
    assert "baseline re-established" in caplog.text


def test_new_env_build_id_reestablishes_baseline_without_alert(tree, monkeypatch):
    root, files, manifest = tree
    redis = FakeRedis()
    monkeypatch.setenv(bi.BUILD_ID_ENV, "build-1")
    _build(root, manifest)
    assert _tamper_events(_boot_and_check(redis, monkeypatch)) == []

    files[0].write_text("# db.py v2\n")
    monkeypatch.setenv(bi.BUILD_ID_ENV, "build-2")
    _build(root, manifest)
    assert _tamper_events(_boot_and_check(redis, monkeypatch)) == []
    assert redis.kv[td._CURRENT_BUILD_KEY] == "env:build-2"


def test_manifest_catches_change_made_before_first_boot(tree, monkeypatch):
    """The baseline comes from build time, so a file altered between image build and first start is still caught."""
    root, files, manifest = tree
    _build(root, manifest)
    monkeypatch.setenv(bi.BUILD_ID_ENV, "abc123")  # keep the id fixed while the file changes
    files[1].write_text("# models.py altered in the container\n")
    assert [e["detail"]["file"] for e in _tamper_events(_boot_and_check(FakeRedis(), monkeypatch))] == ["models.py"]


def test_redis_unavailable_uses_memory_baseline(tree, monkeypatch):
    root, files, manifest = tree
    _build(root, manifest)
    _use_redis(monkeypatch, None)
    det = td.ThreatDetector()

    async def go():
        await det.load_or_create_baseline()
        clean = await det.check_file_integrity()
        files[0].write_text("# db.py backdoored\n")
        dirty = await det.check_file_integrity()
        return clean, dirty
    clean, dirty = asyncio.run(go())
    assert _tamper_events(clean) == []
    assert [e["detail"]["file"] for e in _tamper_events(dirty)] == ["db.py"]


def test_redis_unavailable_without_manifest_still_works(tree, monkeypatch):
    root, files, manifest = tree
    _use_redis(monkeypatch, None)
    det = td.ThreatDetector()

    async def go():
        await det.load_or_create_baseline()
        await det.update_baseline(files[0])
        return await det.check_file_integrity()
    assert _tamper_events(asyncio.run(go())) == []
    assert det._build_id is None


def test_no_build_identity_keeps_legacy_keys(tree, monkeypatch):
    """Bare-metal installs (no manifest, no AETHER_BUILD_ID) keep the guardian:file_hash:<md5> keys post-deploy.sh writes."""
    root, files, manifest = tree
    redis = FakeRedis()
    assert _tamper_events(_boot_and_check(redis, monkeypatch)) == []
    assert td._legacy_key(files[0]) in redis.kv
    assert redis.hashes == {}

    files[0].write_text("# db.py changed\n")
    assert [e["detail"]["file"] for e in _tamper_events(_boot_and_check(redis, monkeypatch))] == ["db.py"]

    # Admin re-baseline (update_all_baselines) clears it, as before.
    _use_redis(monkeypatch, redis)
    det = td.ThreatDetector()

    async def go():
        await det.load_or_create_baseline()
        await det.update_all_baselines()
        return await det.check_file_integrity()
    assert _tamper_events(asyncio.run(go())) == []


def test_update_baseline_writes_current_build_scope(tree, monkeypatch):
    root, files, manifest = tree
    redis = FakeRedis()
    _build(root, manifest)
    _boot_and_check(redis, monkeypatch)
    files[0].write_text("# db.py hotfix accepted by admin\n")
    det = td.ThreatDetector()

    async def go():
        await det.load_or_create_baseline()
        await det.update_baseline(files[0])
        return await det.check_file_integrity()
    assert _tamper_events(asyncio.run(go())) == []


def test_unreadable_manifest_falls_back(tree, monkeypatch):
    root, files, manifest = tree
    manifest.write_text("{not json")
    assert bi.resolve_build_identity(manifest) == (None, None)
    manifest.write_text(json.dumps({"files": {"core/db.py": "x"}}))
    build_id, files_map = bi.resolve_build_identity(manifest)
    assert build_id.startswith("manifest:") and files_map == {"core/db.py": "x"}
