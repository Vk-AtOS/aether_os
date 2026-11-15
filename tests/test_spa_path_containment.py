"""KAN-121: the SPA file server serves only files really inside dist/ (a sibling dir with the same prefix is not)."""
import os

from aether_os.gateway.routers.spa_router import _file_inside


def test_only_real_files_inside_the_base_are_served(tmp_path):
    dist, sibling = tmp_path / "dist", tmp_path / "dist-secrets"
    (dist / "assets").mkdir(parents=True)
    sibling.mkdir()
    (dist / "assets" / "app.js").write_text("ok")
    (sibling / "key.txt").write_text("secret")
    (tmp_path / "outside.txt").write_text("x")
    os.symlink(tmp_path / "outside.txt", dist / "link.txt")
    base = str(dist)
    assert _file_inside(base, "assets/app.js") == os.path.realpath(dist / "assets" / "app.js")
    assert _file_inside(base, "../dist-secrets/key.txt") is None   # same string prefix, other directory
    assert _file_inside(base, "../outside.txt") is None
    assert _file_inside(base, "link.txt") is None                    # a link leading out of the tree
    assert _file_inside(base, "assets") is None and _file_inside(base, "") is None
    assert _file_inside(base, "missing.js") is None
