"""Source of the payload helper that p07a writes into every generated CRUD test.

The generated tests used to guess the create body from the architecture's field list, or send {"name": "test"} when
entities came as bare labels. The app then answered 422 for every required field the guess missed: production
acceptance run 14 (22 Nov 2026) failed s06 on `owner_id: Field required`, and p07b could not repair it because it must
not edit tests. The helper reads the app's own OpenAPI schema at test time instead, so the body always matches the
generated schemas. Strings and emails carry a counter so tests never collide on a unique column. Fields named *_id get the signed-in test user's id (owner, assignee, created_by and similar point at
users), and the guessed payload stays the fallback when the schema has no request body.
"""
from __future__ import annotations

PAYLOAD_HELPER = r'''
import itertools
_SEQ = itertools.count(1)   # every body is distinct: an email or code the schema makes unique is created by several tests


def _resolve(spec, schema):
    while isinstance(schema, dict) and "$ref" in schema:
        name = schema["$ref"].rsplit("/", 1)[-1]
        schema = spec.get("components", {}).get("schemas", {}).get(name, {})
    return schema if isinstance(schema, dict) else {}


def _example(spec, schema, field, user_id):
    schema = _resolve(spec, schema)
    for key in ("anyOf", "oneOf", "allOf"):
        options = [s for s in schema.get(key, []) if _resolve(spec, s).get("type") != "null"]
        if options:
            return _example(spec, options[0], field, user_id)
    if "enum" in schema and schema["enum"]:
        return schema["enum"][0]
    kind, fmt = schema.get("type", "string"), schema.get("format", "")
    if field.endswith("_id") and user_id is not None:
        return user_id if kind != "string" or isinstance(user_id, str) else str(user_id)
    if kind == "integer":
        return max(int(schema.get("minimum", 1)), 1)
    if kind == "number":
        return float(max(schema.get("minimum", 1), 1))
    if kind == "boolean":
        return True
    if kind == "array":
        return []
    if kind == "object":
        return _body(spec, schema, user_id)
    if fmt == "email" or "email" in field:
        return "test_" + field[:8] + str(next(_SEQ)) + "@example.com"
    if fmt == "date-time":
        return "2030-01-01T00:00:00"
    if fmt == "date":
        return "2030-01-01"
    if fmt == "uuid":
        return "00000000-0000-4000-8000-000000000001"
    if fmt in ("uri", "url") or field.endswith("url"):
        return "https://example.com"
    value = ("test_" + field[:8] + str(next(_SEQ))).ljust(int(schema.get("minLength", 0)), "x")
    return value[: int(schema.get("maxLength", 200))]


def _body(spec, schema, user_id):
    schema = _resolve(spec, schema)
    props = schema.get("properties", {})
    return {name: _example(spec, props[name], name, user_id) for name in schema.get("required", []) if name in props}


async def _payload(client, path, fallback):
    """Create body for POST `path` built from the app's OpenAPI schema; `fallback` when it has none."""
    spec = app.openapi()
    op = spec.get("paths", {}).get(path, spec.get("paths", {}).get(path + "/", {})).get("post", {})
    content = op.get("requestBody", {}).get("content", {}).get("application/json", {})
    if not content.get("schema"):
        return dict(fallback)
    fallback = {k: (v + str(next(_SEQ)) if isinstance(v, str) else v) for k, v in fallback.items()}
    user_id = None
    me = await client.get("/api/auth/me")
    if me.status_code == 200 and isinstance(me.json(), dict):
        user_id = me.json().get("id")
    body = _body(spec, content["schema"], user_id)
    return {**fallback, **body} if set(fallback) <= set(_resolve(spec, content["schema"]).get("properties", {})) else body
'''
