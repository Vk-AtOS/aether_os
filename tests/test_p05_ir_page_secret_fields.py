"""Production run 29 (23 Nov 2026): the generated Users page showed "Password Hash" as a plain-text input and a
required "Created At" date, posted password_hash, and the users API answered 422 "password: Field required"."""
from aether_os.core.domain_ir import AetherType, IREntity, IRField
from aether_os.phases.p05_frontend.ir_generators import generate_ir_entity_page

USER = IREntity(name="User", table="users", fields=[
    IRField(name="email", type="email"), IRField(name="password_hash", type="string"),
    IRField(name="full_name", type="string", nullable=True), IRField(name="is_active", type=AetherType.BOOLEAN),
    IRField(name="created_at", type=AetherType.DATETIME)])


def test_a_stored_secret_is_never_shown_and_a_password_is_asked_instead():
    page = generate_ir_entity_page(USER)
    assert "password_hash" not in page and "Password Hash" not in page
    assert 'type="password" name="password"' in page and "required={!item}" in page
    assert "password: fd.get('password') as string || undefined," in page


def test_server_set_columns_are_shown_but_never_inputs_or_payload():
    page = generate_ir_entity_page(USER)
    assert "Created At" in page                      # still a column in the table
    assert 'name="created_at"' not in page and "created_at: fd.get" not in page


def test_entities_without_secrets_get_no_password_field():
    page = generate_ir_entity_page(IREntity(name="Project", table="projects", fields=[IRField(name="name", type="string")]))
    assert 'name="password"' not in page
