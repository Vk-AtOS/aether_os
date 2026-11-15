"""KAN-100 p08: _apply_simple_patch returns the whole patched file, and refuses a patch that does not apply."""
import pytest

from aether_os.phases.p08_cicd.sandbox.docker import _apply_simple_patch as apply

ORIG = "a = 1\nb = 2\nc = 3\nd = 4\ne = 5\n"


def test_hunk_in_the_middle_keeps_the_rest_of_the_file():
    diff = "--- a/x.py\n+++ b/x.py\n@@ -2,3 +2,3 @@\n b = 2\n-c = 3\n+c = 30\n d = 4\n"
    assert apply(ORIG, diff) == "a = 1\nb = 2\nc = 30\nd = 4\ne = 5\n"     # the old code returned only 3 lines


def test_two_hunks_pure_insert_and_delete():
    diff = "@@ -1,1 +1,2 @@\n a = 1\n+a2 = 1\n@@ -5,1 +6,0 @@\n-e = 5\n"
    assert apply(ORIG, diff) == "a = 1\na2 = 1\nb = 2\nc = 3\nd = 4\n"


def test_patch_that_does_not_apply_or_is_not_a_diff_fails():
    with pytest.raises(ValueError, match="does not apply"):
        apply(ORIG, "@@ -2,1 +2,1 @@\n-zzz\n+y\n")
    with pytest.raises(ValueError, match="not a unified diff"):
        apply(ORIG, "+only a line\n")
    assert apply(ORIG, "") == ORIG
