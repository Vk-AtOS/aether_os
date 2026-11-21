"""KAN-69 defence in depth: p05e refuses a table name that is not a plain identifier."""
import pytest

from aether_os.phases.p05e_serverless.serverless_generator import generate_serverless_package


@pytest.mark.parametrize("bad", ["../../etc", "a/b", "x: y", "", "1abc", "a b", None, "a\nb"])
def test_unsafe_table_rejected(tmp_path, bad):
    with pytest.raises(ValueError):
        generate_serverless_package([{"table": bad}], "acme", tmp_path, "python")
    assert not list(tmp_path.rglob("*-created"))


def test_plain_table_ok(tmp_path):
    out = generate_serverless_package([{"table": "order_items"}], "acme", tmp_path, "python")
    assert (out / "order_items-created" / "knative-service.yaml").exists()
