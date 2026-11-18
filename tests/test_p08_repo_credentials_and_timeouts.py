"""KAN-122: the p08 repo helpers must not put a token in the clone URL and must not call an API without a timeout."""
from aether_os.phases.p08_cicd.repo import pr_creator


def test_pr_and_mr_calls_have_a_timeout(monkeypatch):
    seen = []

    def fake_urlopen(req, timeout=None):
        seen.append(timeout)
        raise OSError("stop here")
    monkeypatch.setattr(pr_creator.urllib.request, "urlopen", fake_urlopen)
    c = pr_creator.PRCreator("org/app", token="t")
    assert not c.create_github_pr("b", "t", "body").success
    assert not c.create_gitlab_mr("b", "t", "body").success
    assert seen == [pr_creator._TIMEOUT_S, pr_creator._TIMEOUT_S] and pr_creator._TIMEOUT_S > 0
