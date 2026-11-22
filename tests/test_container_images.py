"""KAN-47: image hygiene that can be checked without Docker: pinned bases, non-root, no baked secrets, health endpoints."""
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
DOCKERFILES = [ROOT / "Dockerfile", ROOT / "core/sandbox/Dockerfile"]


def _image_refs(text):
    stages = set(re.findall(r"^FROM\s+\S+\s+AS\s+(\S+)", text, re.M | re.I))
    refs = re.findall(r"^FROM\s+(\S+)", text, re.M) + re.findall(r"^COPY\s+--from=(\S+)", text, re.M)
    return [r for r in refs if r not in stages]


def test_every_base_image_is_pinned_by_digest():
    for f in DOCKERFILES:
        refs = _image_refs(f.read_text())
        assert refs
        for ref in refs:
            assert "@sha256:" in ref, f"{f.name}: {ref} is not pinned by digest"


def test_compose_third_party_images_are_pinned_and_velaris_image_is_supplied():
    for name in ("docker-compose.yml", "docker-compose.staging.yml"):
        for svc, d in yaml.safe_load((ROOT / name).read_text())["services"].items():
            image = d.get("image", "")
            if image and not image.startswith("${"):
                assert "@sha256:" in image, f"{name}: {svc} uses {image}"


def test_images_run_as_non_root_and_bake_no_secrets():
    for f in DOCKERFILES:
        text = f.read_text()
        users = re.findall(r"^USER\s+(\S+)", text, re.M)
        assert users and users[-1] not in ("root", "0"), f"{f.name} must end as a non-root user"
        for env in re.findall(r"^(?:ENV|ARG)\s+(\S+)", text, re.M):
            assert not re.search(r"SECRET|PASSWORD|TOKEN|PRIVATE|API_KEY", env.split("=")[0]), f"{f.name} bakes {env}"


def test_api_image_healthcheck_is_the_liveness_endpoint_not_a_dependency_check():
    text = (ROOT / "Dockerfile").read_text()
    assert "HEALTHCHECK" in text and "/healthz" in text and "/readyz" not in text


def test_observability_stack_is_opt_in_and_out_of_the_main_compose_file():
    """Compose interpolates ${VAR:?...} in every service of a file, profile or not. When Prometheus and Grafana lived in
    docker-compose.yml behind a profile, their required variables broke every plain `docker compose up` (production
    redeploy, 22 Nov 2026). They now live in docker-compose.observability.yml, used only with an explicit -f."""
    from pathlib import Path
    import yaml
    root = Path(__file__).resolve().parents[1]
    main = yaml.safe_load((root / "docker-compose.yml").read_text())
    assert not {"prometheus", "grafana"} & set(main["services"])
    obs = yaml.safe_load((root / "docker-compose.observability.yml").read_text())
    assert {"prometheus", "grafana"} <= set(obs["services"])
    for svc in obs["services"].values():
        assert "@sha256:" in svc["image"]


def test_image_keeps_pkg_resources_for_razorpay():
    """setuptools 81 removed pkg_resources; razorpay (billing) imports it, and the API aborted at startup on production
    (22 Nov 2026) after an unbounded `setuptools>=78.1.1` upgrade in the image. Keep the upper bound until razorpay drops it."""
    from pathlib import Path
    dockerfile = (Path(__file__).resolve().parents[1] / "Dockerfile").read_text()
    assert '"setuptools>=78.1.1,<81"' in dockerfile
