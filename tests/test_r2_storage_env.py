"""KAN-131: the generated .env and the generated storage client agree on bucket variable names."""
import re

from aether_os.core.cloud_primitives.storage import generate_storage_package


def test_every_env_var_the_client_reads_is_written_to_env_storage(tmp_path):
    ents = [{"table": "order"}, {"table": "address"}, {"table": "order_item"}]
    d = generate_storage_package(ents, "my-shop", tmp_path, "docker_compose")
    env = dict(l.split("=", 1) for l in (d / ".env.storage").read_text().splitlines() if l.startswith("BUCKET_"))
    client = (d / "storage_client.py").read_text()
    wanted = re.findall(r'os\.environ\["(BUCKET_\w+)"\]', client)
    assert len(wanted) == 3 and set(wanted) <= set(env)          # no KeyError at start-up
    assert env["BUCKET_ADDRESSS"] == "my-shop-addresss"
    assert all(re.fullmatch(r"[a-z0-9][a-z0-9-]*[a-z0-9]", b) for b in env.values()), env  # valid S3 names
