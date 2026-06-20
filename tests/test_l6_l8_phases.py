"""
AetherOS — L6–L8 Phase Agent Tests

Covers:
  phases/p05e_serverless/
  phases/p16_iam/
  phases/p17_control_plane/
  phases/p18_billing_metering/
  phases/p19_service_catalog/
  phases/p20_multiregion/
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


# ═══════════════════════════════════════════════════════════════════════════════
# P05e — Serverless (Knative)
# ═══════════════════════════════════════════════════════════════════════════════

class TestP05eServerless:
    def test_knative_service_manifest(self):
        from aether_os.phases.p05e_serverless.serverless_generator import generate_knative_service_manifest
        yaml = generate_knative_service_manifest("order", "created", "myapp", "myapp/order-fn:latest")
        assert "myapp-order-created" in yaml
        assert 'autoscaling.knative.dev/target: "100"' in yaml
        assert "myapp/order-fn:latest" in yaml

    def test_knative_service_manifest_has_scale_to_zero(self):
        from aether_os.phases.p05e_serverless.serverless_generator import generate_knative_service_manifest
        yaml = generate_knative_service_manifest("item", "deleted", "svc", "gcr.io/fn:v1")
        assert 'autoscaling.knative.dev/minScale: "0"' in yaml

    def test_generate_serverless_package_writes_manifests(self, tmp_path):
        from aether_os.phases.p05e_serverless.serverless_generator import generate_serverless_package
        entities = [{"table": "order", "fields": []}, {"table": "product", "fields": []}]
        sl_dir = generate_serverless_package(entities, "myapp", tmp_path, "python")
        assert sl_dir.exists()
        yamls = list(sl_dir.rglob("*.yaml"))
        assert len(yamls) > 0

    @pytest.mark.asyncio
    async def test_p05e_run_skips_non_serverless(self, tmp_path):
        from aether_os.phases.p05e_serverless.task_agent import run

        class PhaseInput:
            input_data = {"build_profile": {"architecture": "monolith"}}

        result = await run(PhaseInput(), [], tmp_path / "out")
        assert result.success is True
        assert result.metadata.get("skipped") is True

    @pytest.mark.asyncio
    async def test_p05e_run_generates_for_serverless(self, tmp_path):
        from aether_os.phases.p05e_serverless.task_agent import run

        class PhaseInput:
            input_data = {
                "project_name": "MyApp",
                "build_profile": {"architecture": "serverless", "backend_language": "python"},
                "domain_ir": {"entities": [{"table": "order", "fields": []}]},
            }

        result = await run(PhaseInput(), [], tmp_path / "out")
        assert result.success is True
        assert result.metadata.get("function_count", 0) > 0

    @pytest.mark.asyncio
    async def test_p05e_run_generates_for_event_driven(self, tmp_path):
        from aether_os.phases.p05e_serverless.task_agent import run

        class PhaseInput:
            input_data = {
                "project_name": "EventApp",
                "build_profile": {"architecture": "event_driven", "backend_language": "python"},
                "domain_ir": {"entities": [{"table": "event", "fields": []}]},
            }

        result = await run(PhaseInput(), [], tmp_path / "out")
        assert result.success is True


# ═══════════════════════════════════════════════════════════════════════════════
# P16 — IAM (OPA + Keycloak)
# ═══════════════════════════════════════════════════════════════════════════════

class TestP16IAM:
    def test_opa_policy_default_roles(self):
        from aether_os.phases.p16_iam.iam_generator import generate_opa_policy
        policy = generate_opa_policy({}, "myapp")
        assert "package authz" in policy
        assert "allow" in policy

    def test_opa_policy_custom_rules(self):
        from aether_os.phases.p16_iam.iam_generator import generate_opa_policy
        pm = {
            "rules": [
                {"role": "superuser", "resource": "*", "actions": ["create", "read", "update", "delete"]},
                {"role": "guest", "resource": "product", "actions": ["read"]},
            ]
        }
        policy = generate_opa_policy(pm, "shop")
        assert "package authz" in policy
        assert "superuser" in policy

    def test_keycloak_realm_valid_json(self):
        from aether_os.phases.p16_iam.iam_generator import generate_keycloak_realm
        realm_str = generate_keycloak_realm("myapp", ["admin", "user", "viewer"])
        realm = json.loads(realm_str)
        assert realm["realm"] == "myapp"
        assert realm["enabled"] is True
        roles = [r["name"] for r in realm["roles"]["realm"]]
        assert "admin" in roles
        assert "user" in roles

    def test_keycloak_realm_default_roles_on_empty(self):
        from aether_os.phases.p16_iam.iam_generator import generate_keycloak_realm
        realm_str = generate_keycloak_realm("app", [])
        realm = json.loads(realm_str)
        role_names = [r["name"] for r in realm["roles"]["realm"]]
        assert len(role_names) > 0

    def test_keycloak_realm_has_api_client(self):
        from aether_os.phases.p16_iam.iam_generator import generate_keycloak_realm
        realm = json.loads(generate_keycloak_realm("shop", ["admin", "user"]))
        client_ids = [c["clientId"] for c in realm.get("clients", [])]
        assert "api-client" in client_ids

    def test_generate_iam_package_writes_files(self, tmp_path):
        from aether_os.phases.p16_iam.iam_generator import generate_iam_package
        iam_dir = generate_iam_package({}, "myapp", tmp_path)
        assert (iam_dir / "policy.rego").exists()
        assert (iam_dir / "keycloak-realm.json").exists()

    @pytest.mark.asyncio
    async def test_p16_run_always_succeeds(self, tmp_path):
        from aether_os.phases.p16_iam.task_agent import run

        class PhaseInput:
            input_data = {"project_name": "My App"}

        result = await run(PhaseInput(), [], tmp_path / "out")
        assert result.success is True
        assert result.confidence == 0.90

    @pytest.mark.asyncio
    async def test_p16_run_uses_default_roles_on_empty_model(self, tmp_path):
        from aether_os.phases.p16_iam.task_agent import run

        class PhaseInput:
            input_data = {"project_name": "Test", "permission_model": {}}

        result = await run(PhaseInput(), [], tmp_path / "out")
        assert result.success is True
        assert "roles" in result.metadata

    @pytest.mark.asyncio
    async def test_p16_run_uses_custom_roles(self, tmp_path):
        from aether_os.phases.p16_iam.task_agent import run

        class PhaseInput:
            input_data = {
                "project_name": "Shop",
                "permission_model": {
                    "roles": ["owner", "staff", "customer"],
                    "rules": [
                        {"role": "owner", "resource": "*", "actions": ["create", "read", "update", "delete"]},
                    ]
                }
            }

        result = await run(PhaseInput(), [], tmp_path / "out")
        assert result.success is True
        assert "owner" in result.metadata.get("roles", [])


# ═══════════════════════════════════════════════════════════════════════════════
# P17 — Control Plane (Kubernetes Operator)
# ═══════════════════════════════════════════════════════════════════════════════

class TestP17ControlPlane:
    def test_pascal_helper(self):
        from aether_os.phases.p17_control_plane.operator_generator import _pascal
        assert _pascal("order_item") == "OrderItem"
        assert _pascal("my-resource") == "MyResource"

    def test_field_type_mapping(self):
        from aether_os.phases.p17_control_plane.operator_generator import _field_type_to_openapi
        assert _field_type_to_openapi("str") == "string"
        assert _field_type_to_openapi("int") == "integer"
        assert _field_type_to_openapi("bool") == "boolean"
        assert _field_type_to_openapi("email") == "string"
        assert _field_type_to_openapi("unknown_type") == "string"

    def test_crd_yaml_contains_kind(self):
        from aether_os.phases.p17_control_plane.operator_generator import generate_crd_yaml
        entity = {"table": "order", "fields": [{"name": "status", "type": "string"}]}
        yaml = generate_crd_yaml(entity, "myapp")
        assert "kind: CustomResourceDefinition" in yaml
        assert "Order" in yaml

    def test_crd_yaml_has_spec_fields(self):
        from aether_os.phases.p17_control_plane.operator_generator import generate_crd_yaml
        entity = {
            "table": "product",
            "fields": [
                {"name": "name", "type": "string"},
                {"name": "price", "type": "float"},
                {"name": "in_stock", "type": "bool"},
            ]
        }
        yaml = generate_crd_yaml(entity, "shop")
        assert "Product" in yaml
        assert "name:" in yaml

    def test_generate_operator_package_writes_main_go(self, tmp_path):
        from aether_os.phases.p17_control_plane.operator_generator import generate_operator_package
        entities = [{"table": "order", "fields": [{"name": "status", "type": "string"}]}]
        op_dir = generate_operator_package(entities, "myapp", tmp_path)
        assert (op_dir / "main.go").exists()

    def test_generate_operator_package_writes_crd_per_entity(self, tmp_path):
        from aether_os.phases.p17_control_plane.operator_generator import generate_operator_package
        entities = [
            {"table": "order", "fields": []},
            {"table": "product", "fields": []},
        ]
        op_dir = generate_operator_package(entities, "shop", tmp_path)
        crd_dir = op_dir / "config" / "crd"
        assert crd_dir.exists()
        crds = list(crd_dir.glob("*.yaml"))
        assert len(crds) >= 2

    @pytest.mark.asyncio
    async def test_p17_run_skips_for_monolith(self, tmp_path):
        from aether_os.phases.p17_control_plane.task_agent import run

        class PhaseInput:
            input_data = {"build_profile": {"architecture": "monolith", "deployment_target": "docker_compose"}}

        result = await run(PhaseInput(), [], tmp_path / "out")
        assert result.success is True
        assert result.metadata.get("skipped") is True

    @pytest.mark.asyncio
    async def test_p17_run_generates_for_microservices(self, tmp_path):
        from aether_os.phases.p17_control_plane.task_agent import run

        class PhaseInput:
            input_data = {
                "project_name": "My Platform",
                "build_profile": {"architecture": "microservices", "deployment_target": "kubernetes"},
                "domain_ir": {"entities": [{"table": "service", "fields": [{"name": "name", "type": "string"}]}]},
            }

        result = await run(PhaseInput(), [], tmp_path / "out")
        assert result.success is True
        assert result.metadata.get("entity_count", 0) >= 1

    @pytest.mark.asyncio
    async def test_p17_run_generates_for_kubernetes_target(self, tmp_path):
        from aether_os.phases.p17_control_plane.task_agent import run

        class PhaseInput:
            input_data = {
                "project_name": "K8sApp",
                "build_profile": {"architecture": "monolith", "deployment_target": "kubernetes"},
                "domain_ir": {"entities": [{"table": "item", "fields": []}]},
            }

        result = await run(PhaseInput(), [], tmp_path / "out")
        assert result.success is True
        assert not result.metadata.get("skipped")


# ═══════════════════════════════════════════════════════════════════════════════
# P18 — Billing & Metering (OpenMeter + Stripe)
# ═══════════════════════════════════════════════════════════════════════════════

class TestP18BillingMetering:
    def test_openmeter_config_has_meters_per_entity(self):
        from aether_os.phases.p18_billing_metering.metering_generator import generate_openmeter_config
        entities = [{"table": "order"}, {"table": "product"}]
        yaml = generate_openmeter_config("shop", entities)
        assert "order" in yaml.lower()
        assert "product" in yaml.lower()

    def test_openmeter_uses_unique_count_for_user_entity(self):
        from aether_os.phases.p18_billing_metering.metering_generator import generate_openmeter_config
        entities = [{"table": "user"}]
        yaml = generate_openmeter_config("app", entities)
        assert "UNIQUE_COUNT" in yaml

    def test_openmeter_uses_sum_for_storage_entity(self):
        from aether_os.phases.p18_billing_metering.metering_generator import generate_openmeter_config
        entities = [{"table": "file"}]
        yaml = generate_openmeter_config("app", entities)
        assert "SUM" in yaml

    def test_openmeter_uses_count_for_generic_entity(self):
        from aether_os.phases.p18_billing_metering.metering_generator import generate_openmeter_config
        entities = [{"table": "order"}]
        yaml = generate_openmeter_config("shop", entities)
        assert "COUNT" in yaml

    def test_generate_billing_package_writes_all_files(self, tmp_path):
        from aether_os.phases.p18_billing_metering.metering_generator import generate_billing_package
        entities = [{"table": "order"}, {"table": "user"}]
        billing_dir = generate_billing_package(entities, "shop", tmp_path)
        assert (billing_dir / "openmeter-config.yaml").exists()
        assert (billing_dir / "billing_webhook.py").exists()
        assert (billing_dir / "metering_middleware.py").exists()
        assert (billing_dir / "event-schema.json").exists()

    def test_billing_webhook_is_valid_python(self, tmp_path):
        import ast
        from aether_os.phases.p18_billing_metering.metering_generator import generate_billing_package
        entities = [{"table": "subscription"}]
        billing_dir = generate_billing_package(entities, "saas", tmp_path)
        code = (billing_dir / "billing_webhook.py").read_text()
        ast.parse(code)

    def test_event_schema_is_valid_json(self, tmp_path):
        from aether_os.phases.p18_billing_metering.metering_generator import generate_billing_package
        entities = [{"table": "order"}]
        billing_dir = generate_billing_package(entities, "shop", tmp_path)
        schema_str = (billing_dir / "event-schema.json").read_text()
        schema = json.loads(schema_str)
        assert isinstance(schema, dict)

    @pytest.mark.asyncio
    async def test_p18_run_always_succeeds(self, tmp_path):
        from aether_os.phases.p18_billing_metering.task_agent import run

        class PhaseInput:
            input_data = {"project_name": "My SaaS"}

        result = await run(PhaseInput(), [], tmp_path / "out")
        assert result.success is True

    @pytest.mark.asyncio
    async def test_p18_run_uses_default_entity_on_empty_ir(self, tmp_path):
        from aether_os.phases.p18_billing_metering.task_agent import run

        class PhaseInput:
            input_data = {"project_name": "Empty", "domain_ir": {}}

        result = await run(PhaseInput(), [], tmp_path / "out")
        assert result.success is True
        assert result.metadata.get("entity_count") == 1


# ═══════════════════════════════════════════════════════════════════════════════
# P19 — Service Catalog (Cloud Console)
# ═══════════════════════════════════════════════════════════════════════════════

class TestP19ServiceCatalog:
    def test_catalog_models_has_service_instance(self):
        from aether_os.phases.p19_service_catalog.catalog_generator import generate_catalog_models
        code = generate_catalog_models("myplatform")
        assert "ServiceInstance" in code
        assert "InstanceStatus" in code

    def test_catalog_api_has_platform_endpoints(self):
        from aether_os.phases.p19_service_catalog.catalog_generator import generate_catalog_api
        entities = [{"table": "service", "columns": ["id", "name"]}]
        code = generate_catalog_api(entities, "myplatform", "python")
        assert "/api/platform/stats" in code
        assert "/api/services" in code

    def test_generate_catalog_package_writes_router(self, tmp_path):
        from aether_os.phases.p19_service_catalog.catalog_generator import generate_catalog_package
        entities = [{"table": "service", "columns": ["id", "name"]}]
        cat_dir = generate_catalog_package(entities, "myplatform", tmp_path, "python")
        assert (cat_dir / "router.py").exists()

    def test_generate_catalog_package_writes_models_and_migration(self, tmp_path):
        from aether_os.phases.p19_service_catalog.catalog_generator import generate_catalog_package
        entities = [{"table": "resource", "columns": ["id", "name", "status"]}]
        cat_dir = generate_catalog_package(entities, "platform", tmp_path, "python")
        assert (cat_dir / "models.py").exists()
        assert (cat_dir / "migration.sql").exists()

    @pytest.mark.asyncio
    async def test_p19_run_skips_non_cloud_platform(self, tmp_path):
        from aether_os.phases.p19_service_catalog.task_agent import run

        class PhaseInput:
            input_data = {"build_profile": {"build_type": "saas"}}

        result = await run(PhaseInput(), [], tmp_path / "out")
        assert result.success is True
        assert result.metadata.get("skipped") is True

    @pytest.mark.asyncio
    async def test_p19_run_generates_for_cloud_platform(self, tmp_path):
        from aether_os.phases.p19_service_catalog.task_agent import run

        class PhaseInput:
            input_data = {
                "project_name": "My Cloud",
                "build_profile": {"build_type": "cloud_platform", "backend_lang": "python"},
                "domain_ir": {"entities": [{"table": "service", "columns": ["id", "name"]}]},
                "services": [{"name": "compute", "port": 8001}],
            }

        with patch(
            "aether_os.phases.p05_frontend.cloud_console_generator.generate_cloud_console",
            new_callable=AsyncMock,
        ) as mock_gen:
            mock_console_dir = tmp_path / "out" / "cloud_console"
            mock_console_dir.mkdir(parents=True, exist_ok=True)
            mock_gen.return_value = mock_console_dir
            result = await run(PhaseInput(), [], tmp_path / "out")

        assert result.success is True
        assert result.metadata.get("entity_count", 0) >= 1


# ═══════════════════════════════════════════════════════════════════════════════
# P20 — Multi-Region
# ═══════════════════════════════════════════════════════════════════════════════

class TestP20MultiRegion:
    def test_multiregion_generator_writes_terraform(self, tmp_path):
        from aether_os.phases.p20_multiregion.multiregion_generator import generate_multiregion_package
        entities = [{"table": "order"}]
        mr_dir = generate_multiregion_package(entities, "myapp", tmp_path)
        assert mr_dir.exists()
        tf_files = list(mr_dir.rglob("*.tf"))
        assert len(tf_files) > 0

    @pytest.mark.asyncio
    async def test_p20_run_skips_non_kubernetes(self, tmp_path):
        from aether_os.phases.p20_multiregion.task_agent import run

        class PhaseInput:
            input_data = {
                "build_profile": {
                    "deployment_target": "docker_compose",
                    "architecture": "microservices",
                }
            }

        result = await run(PhaseInput(), [], tmp_path / "out")
        assert result.success is True
        assert result.metadata.get("skipped") is True

    @pytest.mark.asyncio
    async def test_p20_run_skips_non_microservices(self, tmp_path):
        from aether_os.phases.p20_multiregion.task_agent import run

        class PhaseInput:
            input_data = {
                "build_profile": {
                    "deployment_target": "kubernetes",
                    "architecture": "monolith",
                }
            }

        result = await run(PhaseInput(), [], tmp_path / "out")
        assert result.success is True
        assert result.metadata.get("skipped") is True

    @pytest.mark.asyncio
    async def test_p20_run_generates_for_kubernetes_microservices(self, tmp_path):
        from aether_os.phases.p20_multiregion.task_agent import run

        class PhaseInput:
            input_data = {
                "project_name": "My Platform",
                "build_profile": {
                    "deployment_target": "kubernetes",
                    "architecture": "microservices",
                    "performance_tier": "high_throughput",
                    "message_queue": "nats",
                },
                "domain_ir": {"entities": [
                    {"table": "order", "fields": [{"name": "status", "type": "string"}]},
                ]},
            }

        result = await run(PhaseInput(), [], tmp_path / "out")
        assert result.success is True
        assert len(result.metadata.get("files_written", [])) > 0

    @pytest.mark.asyncio
    async def test_p20_run_for_event_driven(self, tmp_path):
        from aether_os.phases.p20_multiregion.task_agent import run

        class PhaseInput:
            input_data = {
                "project_name": "EventPlatform",
                "build_profile": {
                    "deployment_target": "kubernetes",
                    "architecture": "event_driven",
                    "performance_tier": "standard",
                    "message_queue": "",
                },
                "domain_ir": {"entities": [{"table": "event", "fields": []}]},
            }

        result = await run(PhaseInput(), [], tmp_path / "out")
        assert result.success is True

    @pytest.mark.asyncio
    async def test_p20_slug_sanitizes_special_chars(self, tmp_path):
        from aether_os.phases.p20_multiregion.task_agent import run

        class PhaseInput:
            input_data = {
                "project_name": "My App 2.0!",
                "build_profile": {
                    "deployment_target": "kubernetes",
                    "architecture": "microservices",
                    "performance_tier": "standard",
                },
                "domain_ir": {},
            }

        result = await run(PhaseInput(), [], tmp_path / "out")
        assert result.success is True
        slug = result.metadata.get("slug", "")
        assert "!" not in slug
        assert " " not in slug
