"""KAN-109: p05e lambda output is valid YAML, authenticated, and free of SQL injection."""
import importlib.util
import json

import jwt
import pytest
import yaml

from aether_os.phases.p05e_serverless.lambda_generator import gen_authorizer, gen_entity_lambda_handler, gen_sam_template

ENTITIES = [{"name": "order", "fields": [{"name": "title"}, {"name": "qty"}]},
            {"name": "Bad Name; DROP", "fields": [{"name": "x y"}]}]


class _Loader(yaml.SafeLoader):
    pass


_Loader.add_multi_constructor("!", lambda loader, suffix, node: None)


def _load_module(tmp_path, name, code):
    f = tmp_path / f"{name}.py"
    f.write_text(code)
    spec = importlib.util.spec_from_file_location(name, f)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_template_is_valid_yaml_with_authorizer_on_entity_routes_only():
    t = yaml.load(gen_sam_template('Acme "Q" App', ENTITIES), Loader=_Loader)
    res = t["Resources"]
    assert "AuthorizerFunction" in res and "OrderFunction" in res and "BadNameDropFunction" in res
    api = next(v for v in res.values() if v["Type"] == "AWS::Serverless::Api")
    assert api["Properties"]["Auth"]["DefaultAuthorizer"] == "JwtAuthorizer"
    for ev in res["OrderFunction"]["Properties"]["Events"].values():
        assert ev["Properties"]["Auth"]["Authorizer"] == "JwtAuthorizer"
    for ev in res["MainAppFunction"]["Properties"]["Events"].values():
        assert ev["Properties"]["Auth"]["Authorizer"] == "NONE"


def test_update_cannot_inject_sql_through_body_keys(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/t.db")
    mod = _load_module(tmp_path, "order_handler", gen_entity_lambda_handler(ENTITIES[0]))
    import sqlalchemy as sa
    with mod._get_engine().begin() as c:
        c.execute(sa.text("CREATE TABLE orders (id INTEGER PRIMARY KEY, title TEXT, qty INT)"))
        c.execute(sa.text("INSERT INTO orders (title, qty) VALUES ('a', 1)"))

    def call(body):
        return mod.lambda_handler({"httpMethod": "PUT", "pathParameters": {"id": "1"}, "body": json.dumps(body)}, None)

    assert call({"title = 'x', qty": 99})["statusCode"] == 400              # fragment is not a column
    assert call({"title": "b", "id; DROP TABLE orders --": 1})["statusCode"] == 200
    with mod._get_engine().connect() as c:
        assert c.execute(sa.text("SELECT title, qty FROM orders")).one() == ("b", 1)
    assert mod.lambda_handler({"httpMethod": "PUT", "pathParameters": {"id": "1"}, "body": "[1]"}, None)["statusCode"] == 400


def test_hostile_entity_and_field_names_do_not_reach_the_generated_code():
    code = gen_entity_lambda_handler({"name": 'x"; import os #', "fields": [{"name": "a'); DROP"}]})
    compile(code, "h.py", "exec")
    assert "DROP" not in code and "x\";" not in code


def test_authorizer_verifies_signature(tmp_path, monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "k" * 40)
    monkeypatch.delenv("JWT_PUBLIC_KEY", raising=False)
    mod = _load_module(tmp_path, "authorizer", gen_authorizer())
    ev = lambda tok: {"authorizationToken": tok, "methodArn": "arn:aws:execute-api:r:1:api/prod/GET/orders"}
    good = jwt.encode({"sub": "u1", "type": "access", "role": "admin"}, "k" * 40, algorithm="HS256")
    out = mod.lambda_handler(ev("Bearer " + good), None)
    assert out["principalId"] == "u1" and out["policyDocument"]["Statement"][0]["Effect"] == "Allow"
    forged = jwt.encode({"sub": "u1", "type": "access"}, "other" * 10, algorithm="HS256")
    for bad in ("Bearer " + forged, "Bearer garbage", "", good, "Bearer " + jwt.encode({"sub": "u", "type": "refresh"}, "k" * 40)):
        with pytest.raises(Exception, match="Unauthorized"):
            mod.lambda_handler(ev(bad), None)
