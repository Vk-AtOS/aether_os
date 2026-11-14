"""
AetherOS — L5 Cloud Primitives Tests

Covers:
  core/cloud_primitives/storage.py (MinIO)
  core/cloud_primitives/queue.py   (NATS JetStream)
  core/cloud_primitives/gateway.py (Kong)
  core/cell_architecture/cell_planner.py
  core/chaos_engineering/chaos_generator.py
  core/capacity_planner/planner.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


# ═══════════════════════════════════════════════════════════════════════════════
# Cloud Primitives — Storage (MinIO)
# ═══════════════════════════════════════════════════════════════════════════════

class TestStoragePrimitives:
    def test_minio_helm_values_contains_slug(self):
        from aether_os.core.cloud_primitives.storage import generate_minio_helm_values
        yaml = generate_minio_helm_values("myapp", storage_size_gb=100)
        assert "myapp" in yaml
        assert "100Gi" in yaml
        assert "replicas: 3" in yaml

    def test_minio_helm_values_default_size(self):
        from aether_os.core.cloud_primitives.storage import generate_minio_helm_values
        yaml = generate_minio_helm_values("testapp")
        assert "50Gi" in yaml

    def test_bucket_policy_valid_json(self):
        from aether_os.core.cloud_primitives.storage import generate_bucket_policy
        policy_str = generate_bucket_policy("order", "myapp")
        policy = json.loads(policy_str)
        assert policy["Version"] == "2012-10-17"
        statements = policy["Statement"]
        assert len(statements) == 2
        assert any("PutObject" in str(s["Action"]) for s in statements)

    def test_bucket_policy_entity_in_resource(self):
        from aether_os.core.cloud_primitives.storage import generate_bucket_policy
        policy = json.loads(generate_bucket_policy("product", "shop"))
        resources = " ".join(str(s["Resource"]) for s in policy["Statement"])
        assert "shop-products" in resources

    def test_storage_env_has_bucket_vars(self):
        from aether_os.core.cloud_primitives.storage import generate_storage_env
        env = generate_storage_env("myapp", ["myapp-orders", "myapp-products"])
        assert "MINIO_ENDPOINT" in env
        assert "BUCKET_" in env
        assert "myapp-orders" in env

    def test_storage_env_has_minio_credentials(self):
        from aether_os.core.cloud_primitives.storage import generate_storage_env
        env = generate_storage_env("svc", ["svc-items"])
        assert "MINIO_ACCESS_KEY" in env
        assert "MINIO_SECRET_KEY" in env

    def test_python_storage_client_is_valid_python(self):
        import ast
        from aether_os.core.cloud_primitives.storage import generate_python_storage_client
        entities = [{"table": "order"}, {"table": "product"}]
        code = generate_python_storage_client(entities)
        ast.parse(code)
        assert "class StorageClient" in code
        assert "upload_file" in code
        assert "download_file" in code
        assert "presigned_url" in code

    def test_minio_docker_compose_has_slug_network(self):
        from aether_os.core.cloud_primitives.storage import generate_minio_docker_compose
        compose = generate_minio_docker_compose("myapp")
        assert "minio:" in compose
        assert "myapp_network" in compose
        assert "9000:9000" in compose

    def test_generate_storage_package_writes_all_files(self, tmp_path):
        from aether_os.core.cloud_primitives.storage import generate_storage_package
        entities = [{"table": "order"}, {"table": "product"}]
        storage_dir = generate_storage_package(entities, "shop", tmp_path, "kubernetes")
        assert (storage_dir / "minio-values.yaml").exists()
        assert (storage_dir / ".env.storage").exists()
        assert (storage_dir / "storage_client.py").exists()
        assert (storage_dir / "docker-compose.storage.yml").exists()

    def test_generate_storage_package_writes_bucket_policies(self, tmp_path):
        from aether_os.core.cloud_primitives.storage import generate_storage_package
        entities = [{"table": "item"}, {"table": "file"}]
        storage_dir = generate_storage_package(entities, "app", tmp_path, "docker_compose")
        policies_dir = storage_dir / "bucket-policies"
        assert policies_dir.exists()
        assert (policies_dir / "item-policy.json").exists()
        assert (policies_dir / "file-policy.json").exists()


# ═══════════════════════════════════════════════════════════════════════════════
# Cloud Primitives — Queue (NATS)
# ═══════════════════════════════════════════════════════════════════════════════

class TestQueuePrimitives:
    def test_nats_helm_values_contains_slug(self):
        from aether_os.core.cloud_primitives.queue import generate_nats_helm_values
        yaml = generate_nats_helm_values("myapp")
        assert "myapp" in yaml
        assert "jetstream:" in yaml
        assert "replicas: 3" in yaml

    def test_stream_config_has_dlq(self):
        from aether_os.core.cloud_primitives.queue import generate_stream_config
        yaml = generate_stream_config("order", "myapp")
        assert "MYAPP_ORDER" in yaml
        assert "MYAPP_ORDER_DLQ" in yaml
        assert "max_deliver: 5" in yaml

    def test_stream_config_has_subjects(self):
        from aether_os.core.cloud_primitives.queue import generate_stream_config
        yaml = generate_stream_config("payment", "shop")
        assert "shop.payment.>" in yaml

    def test_python_queue_client_is_valid_python(self):
        import ast
        from aether_os.core.cloud_primitives.queue import generate_python_queue_client
        entities = [{"table": "order"}, {"table": "invoice"}]
        code = generate_python_queue_client(entities)
        ast.parse(code)
        assert "class QueueClient" in code
        assert "async def publish" in code
        assert "async def subscribe" in code

    def test_nats_docker_compose_has_slug_network(self):
        from aether_os.core.cloud_primitives.queue import generate_nats_docker_compose
        compose = generate_nats_docker_compose("myapp")
        assert "nats:" in compose
        assert "myapp_network" in compose
        assert "4222:4222" in compose

    def test_generate_queue_package_writes_all_files(self, tmp_path):
        from aether_os.core.cloud_primitives.queue import generate_queue_package
        entities = [{"table": "order"}, {"table": "notification"}]
        queue_dir = generate_queue_package(entities, "svc", tmp_path, "kubernetes")
        assert (queue_dir / "nats-values.yaml").exists()
        assert (queue_dir / "queue_client.py").exists()
        assert (queue_dir / "docker-compose.queue.yml").exists()
        streams_dir = queue_dir / "streams"
        assert (streams_dir / "order-stream.yaml").exists()
        assert (streams_dir / "notification-stream.yaml").exists()


# ═══════════════════════════════════════════════════════════════════════════════
# Cloud Primitives — Gateway (Kong)
# ═══════════════════════════════════════════════════════════════════════════════

class TestGatewayPrimitives:
    def test_kong_config_has_services(self):
        from aether_os.core.cloud_primitives.gateway import generate_kong_declarative_config
        services = [
            {"name": "orders", "port": 8001, "path_prefix": "/orders"},
            {"name": "products", "port": 8002, "path_prefix": "/products"},
        ]
        yaml = generate_kong_declarative_config(services, "myapp")
        assert "myapp-orders" in yaml
        assert "myapp-products" in yaml
        assert "_format_version: \"3.0\"" in yaml

    def test_kong_config_has_plugins(self):
        from aether_os.core.cloud_primitives.gateway import generate_kong_declarative_config
        services = [{"name": "api", "port": 8000, "path_prefix": "/api"}]
        yaml = generate_kong_declarative_config(services, "app")
        assert "rate-limiting" in yaml
        assert "jwt" in yaml
        assert "cors" in yaml

    def test_kong_helm_values_dbless(self):
        from aether_os.core.cloud_primitives.gateway import generate_kong_helm_values
        yaml = generate_kong_helm_values("myapp")
        assert 'database: "off"' in yaml
        assert "myapp-kong-config" in yaml
        assert "replicaCount: 2" in yaml

    def test_kong_helm_values_autoscaling(self):
        from aether_os.core.cloud_primitives.gateway import generate_kong_helm_values
        yaml = generate_kong_helm_values("app")
        assert "autoscaling:" in yaml
        assert "maxReplicas: 10" in yaml

    def test_generate_gateway_package_writes_files(self, tmp_path):
        from aether_os.core.cloud_primitives.gateway import generate_gateway_package
        services = [{"name": "api", "port": 8000, "path_prefix": "/api"}]
        gateway_dir = generate_gateway_package(services, "app", tmp_path)
        assert (gateway_dir / "kong.yaml").exists()
        assert (gateway_dir / "kong-values.yaml").exists()


# ═══════════════════════════════════════════════════════════════════════════════
# Chaos Engineering
# ═══════════════════════════════════════════════════════════════════════════════

class TestChaosEngineering:
    def test_pod_delete_experiment_yaml(self):
        from aether_os.core.chaos_engineering.chaos_generator import generate_pod_delete_experiment
        yaml = generate_pod_delete_experiment("orders", "myapp", "production")
        assert "orders-pod-delete" in yaml
        assert "pod-delete" in yaml
        assert "PODS_AFFECTED_PERC" in yaml

    def test_pod_delete_has_health_probe(self):
        from aether_os.core.chaos_engineering.chaos_generator import generate_pod_delete_experiment
        yaml = generate_pod_delete_experiment("api", "shop", "default")
        assert "httpProbe" in yaml
        assert "/health" in yaml

    def test_network_partition_experiment_yaml(self):
        from aether_os.core.chaos_engineering.chaos_generator import generate_network_partition_experiment
        yaml = generate_network_partition_experiment("payments", "myapp", "prod")
        assert "payments-network-partition" in yaml
        assert "pod-network-partition" in yaml

    def test_cpu_hog_experiment_references_hpa(self):
        from aether_os.core.chaos_engineering.chaos_generator import generate_cpu_hog_experiment
        yaml = generate_cpu_hog_experiment("worker", "app", "staging")
        assert "worker-cpu-hog" in yaml
        assert "horizontalpodautoscalers" in yaml
        assert "worker-hpa" in yaml

    def test_generate_chaos_package_writes_all_files(self, tmp_path):
        from aether_os.core.chaos_engineering.chaos_generator import generate_chaos_package
        entities = [{"table": "order"}, {"table": "payment"}]
        chaos_dir = generate_chaos_package(entities, "shop", tmp_path)
        assert (chaos_dir / "rbac.yaml").exists()
        assert (chaos_dir / "chaos-schedule.yaml").exists()
        assert (chaos_dir / "CHAOS_TEST_PLAN.md").exists()
        exp_dir = chaos_dir / "experiments"
        assert (exp_dir / "order-pod-delete.yaml").exists()
        assert (exp_dir / "payment-cpu-hog.yaml").exists()

    def test_generate_chaos_package_three_experiments_per_entity(self, tmp_path):
        from aether_os.core.chaos_engineering.chaos_generator import generate_chaos_package
        entities = [{"table": "item"}]
        chaos_dir = generate_chaos_package(entities, "app", tmp_path)
        exp_dir = chaos_dir / "experiments"
        experiments = list(exp_dir.glob("*.yaml"))
        assert len(experiments) == 3  # pod-delete, network-partition, cpu-hog


# ═══════════════════════════════════════════════════════════════════════════════
# Capacity Planner
# ═══════════════════════════════════════════════════════════════════════════════

class TestCapacityPlanner:
    def test_hpa_standard_tier(self):
        from aether_os.core.capacity_planner.planner import generate_hpa
        yaml = generate_hpa("api", "myapp", "standard", "production")
        assert "api-hpa" in yaml
        assert "minReplicas: 2" in yaml
        assert "maxReplicas: 10" in yaml

    def test_hpa_high_throughput_tier(self):
        from aether_os.core.capacity_planner.planner import generate_hpa
        yaml = generate_hpa("worker", "app", "high_throughput", "default")
        assert "minReplicas: 3" in yaml
        assert "maxReplicas: 50" in yaml

    def test_hpa_real_time_has_latency_metric(self):
        from aether_os.core.capacity_planner.planner import generate_hpa
        yaml = generate_hpa("stream", "svc", "real_time", "staging")
        assert "request_latency_p99" in yaml
        assert "minReplicas: 5" in yaml

    def test_hpa_batch_tier(self):
        from aether_os.core.capacity_planner.planner import generate_hpa
        yaml = generate_hpa("batch", "app", "batch", "default")
        assert "minReplicas: 1" in yaml
        assert "maxReplicas: 20" in yaml

    def test_hpa_unknown_tier_falls_back_to_standard(self):
        from aether_os.core.capacity_planner.planner import generate_hpa
        yaml = generate_hpa("svc", "app", "turbo_extreme_mode", "ns")
        assert "minReplicas: 2" in yaml

    def test_generate_capacity_package_writes_hpa_per_entity(self, tmp_path):
        from aether_os.core.capacity_planner.planner import generate_capacity_package
        entities = [{"table": "order"}, {"table": "payment"}]
        cap_dir = generate_capacity_package(entities, "shop", tmp_path, "standard", "")
        assert (cap_dir / "hpa" / "order-hpa.yaml").exists()
        assert (cap_dir / "hpa" / "payment-hpa.yaml").exists()

    def test_generate_capacity_package_writes_pdb_and_quotas(self, tmp_path):
        from aether_os.core.capacity_planner.planner import generate_capacity_package
        entities = [{"table": "item"}]
        cap_dir = generate_capacity_package(entities, "app", tmp_path, "standard", "")
        assert (cap_dir / "pdb" / "item-pdb.yaml").exists()
        assert (cap_dir / "resource-quotas.yaml").exists()

    def test_generate_capacity_package_keda_with_queue(self, tmp_path):
        from aether_os.core.capacity_planner.planner import generate_capacity_package
        entities = [{"table": "job"}]
        cap_dir = generate_capacity_package(entities, "app", tmp_path, "standard", "nats")
        keda_file = cap_dir / "keda" / "job-scaledobject.yaml"
        assert keda_file.exists()
        assert not (cap_dir / "hpa" / "job-hpa.yaml").exists()  # KEDA owns the HPA for this target
        content = keda_file.read_text()
        assert "ScaledObject" in content


# ═══════════════════════════════════════════════════════════════════════════════
# Cell Architecture
# ═══════════════════════════════════════════════════════════════════════════════

class TestCellArchitecture:
    def test_cell_terraform_has_per_region_modules(self):
        from aether_os.core.cell_architecture.cell_planner import generate_cell_terraform
        tf = generate_cell_terraform("myapp", ["us-east-1", "eu-west-1"])
        assert "module \"cell_us_east_1\"" in tf
        assert "module \"cell_eu_west_1\"" in tf

    def test_cell_terraform_default_three_regions(self):
        from aether_os.core.cell_architecture.cell_planner import (
            generate_cell_terraform,
            DEFAULT_REGIONS,
        )
        tf = generate_cell_terraform("app", DEFAULT_REGIONS)
        for region in DEFAULT_REGIONS:
            assert region in tf

    def test_generate_cell_package_writes_terraform(self, tmp_path):
        from aether_os.core.cell_architecture.cell_planner import generate_cell_package
        entities = [{"table": "order"}]
        cell_dir = generate_cell_package(entities, "myapp", tmp_path)
        assert (cell_dir / "main.tf").exists()
        content = (cell_dir / "main.tf").read_text()
        assert "module" in content

    def test_generate_cell_package_writes_nginx_conf(self, tmp_path):
        from aether_os.core.cell_architecture.cell_planner import generate_cell_package
        entities = [{"table": "item"}]
        cell_dir = generate_cell_package(entities, "app", tmp_path)
        assert (cell_dir / "nginx-cell-router.conf").exists()

    def test_generate_cell_package_writes_failover_runbook(self, tmp_path):
        from aether_os.core.cell_architecture.cell_planner import generate_cell_package
        entities = [{"table": "item"}]
        cell_dir = generate_cell_package(entities, "app", tmp_path)
        assert (cell_dir / "FAILOVER_RUNBOOK.md").exists()
