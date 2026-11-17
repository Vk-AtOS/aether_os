"""KAN-187: a change or reset cannot go back to one of the last passwords."""

NEW1, NEW2 = "Another@Pass456!", "Third#Pass789?x"


def _change(gw, auth, cur, new):
    return gw.client.post("/auth/change-password", headers=auth, json={"current_password": cur, "new_password": new})


def test_change_password_refuses_the_current_and_the_previous_passwords(gw):
    u = gw.register("pwhist")
    assert _change(gw, u.auth, gw.password, gw.password).status_code == 422          # same as the current one
    assert _change(gw, u.auth, gw.password, NEW1).status_code == 200
    back = _change(gw, u.auth, NEW1, gw.password)                                      # back to the first one
    assert back.status_code == 422 and "reuse" in back.json()["detail"]
    assert _change(gw, u.auth, NEW1, NEW2).status_code == 200


def test_history_window_is_configurable_and_zero_disables_it(gw, monkeypatch):
    monkeypatch.setenv("AETHER_PASSWORD_HISTORY", "0")
    u = gw.register("pwhist0")
    assert _change(gw, u.auth, gw.password, NEW1).status_code == 200
    assert _change(gw, u.auth, NEW1, gw.password).status_code == 200


def test_migration_chains_after_api_key_scopes_and_only_hashes_are_stored(gw):
    import importlib.util
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[1] / "alembic" / "versions"
    spec = importlib.util.spec_from_file_location("m", root / "add_password_history.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.down_revision == "add_api_key_scopes"
    u = gw.register("pwhash")
    assert _change(gw, u.auth, gw.password, NEW1).status_code == 200
    rows = gw.sql("SELECT password_hash FROM password_history")
    assert rows and all(gw.password not in str(r) for r in rows)
