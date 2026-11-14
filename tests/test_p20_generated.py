"""KAN-99/KAN-109: p20 security-group rules never open a region's own CIDR; one scaler per service."""
import re

from aether_os.core.capacity_planner.planner import generate_capacity_package
from aether_os.phases.p20_multiregion.multiregion_generator import generate_vpc_peering_tf


def test_sg_rules_admit_only_other_regions():
    tf = generate_vpc_peering_tf("shop", ["us-east-1", "eu-west-1", "ap-south-1"])
    rules = re.findall(r'cidr_blocks\s+= \[var\.vpc_cidrs\["([^"]+)"\]\]\n\s+security_group_id\s+= var\.app_security_group_ids\["([^"]+)"\]', tf)
    assert len(rules) == 6
    assert all(src != tgt for src, tgt in rules)
    assert "for_each" not in tf  # the old rule looped every CIDR over every SG
    assert tf.count("provider          = aws.") == 6


def test_hpa_and_keda_never_target_the_same_service(tmp_path):
    cap = generate_capacity_package([{"table": "job"}], "app", tmp_path / "q", "standard", "kafka")
    assert (cap / "keda" / "job-scaledobject.yaml").exists() and not (cap / "hpa" / "job-hpa.yaml").exists()
    cap = generate_capacity_package([{"table": "job"}], "app", tmp_path / "n", "standard", "")
    assert (cap / "hpa" / "job-hpa.yaml").exists() and not list((cap / "keda").glob("*.yaml"))
