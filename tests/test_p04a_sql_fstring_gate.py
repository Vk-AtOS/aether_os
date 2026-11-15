"""KAN-196: the raw-SQL gate rejects injection-prone code and never rewrites valid code into TODO stubs."""
import pytest

from aether_os.phases.p04a_backend_codegen.crud_generator import _check_and_fix_sql_injection

SAFE = '''x = f"user {name}"
@router.delete("/items/{id}")
async def delete_item(id: int):
    await db.execute(select(Item).where(Item.id == id))
    msg = f"deleted {id}"
    q = "SELECT 1"
'''


def test_valid_code_is_returned_unchanged():
    assert _check_and_fix_sql_injection(SAFE) == SAFE


@pytest.mark.parametrize("bad", [
    'q = f"SELECT * FROM users WHERE name = \'x\' AND id = {uid}"',
    "db.execute(text(f'delete from items where id = {item_id}'))",
])
def test_fstring_sql_is_rejected_not_stubbed(bad):
    with pytest.raises(ValueError):
        _check_and_fix_sql_injection(SAFE + bad + "\n")
