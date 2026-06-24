"""
V2 Integration Tests — stack profile routing, domain pack loading,
Go/Node generator output, compliance manifest, and business model generation.

All tests are deterministic (no LLM calls). They verify end-to-end wiring
between V2 components: stack profiles, generators, domain packs, and writers.
"""
from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import AsyncMock, patch

import pytest


# ── Stack Profile Routing ─────────────────────────────────────────────────────

class TestStackProfileRouting:
    """All 8 required profiles exist with correct fields and are JSON-serialisable."""

    def test_all_eight_required_profiles_present(self):
        from aether_os.core.stack_profiles import STACK_PROFILES
        required = {
            "web_saas", "go_api", "node_serverless", "mobile_rn",
            "desktop_electron", "ml_pipeline", "microservices", "web_saas_sqlite",
        }
        assert not (required - set(STACK_PROFILES.keys()))

    def test_web_saas_routes_to_fastapi_react(self):
        from aether_os.core.stack_profiles import STACK_PROFILES
        p = STACK_PROFILES["web_saas"]
        assert p.backend_framework == "fastapi"
        assert p.frontend_framework == "react"
        assert p.backend_lang == "python"
        assert p.db_primary == "postgres"

    def test_go_api_routes_to_go_gin_kubernetes(self):
        from aether_os.core.stack_profiles import STACK_PROFILES
        p = STACK_PROFILES["go_api"]
        assert p.backend_lang == "go"
        assert p.backend_framework == "gin"
        assert p.performance_tier == "high_throughput"
        assert p.deployment_target == "kubernetes"

    def test_mobile_rn_routes_to_react_native(self):
        from aether_os.core.stack_profiles import STACK_PROFILES
        p = STACK_PROFILES["mobile_rn"]
        assert p.frontend_framework == "react_native"
        assert p.build_type == "mobile"

    def test_microservices_routes_to_go_kafka_k8s(self):
        from aether_os.core.stack_profiles import STACK_PROFILES
        p = STACK_PROFILES["microservices"]
        assert p.architecture == "microservices"
        assert p.backend_lang == "go"
        assert p.message_queue == "kafka"
        assert p.deployment_target == "kubernetes"

    def test_remaining_profile_fields(self):
        from aether_os.core.stack_profiles import STACK_PROFILES
        assert STACK_PROFILES["node_serverless"].backend_lang == "typescript"
        assert STACK_PROFILES["desktop_electron"].build_type == "desktop"
        assert STACK_PROFILES["ml_pipeline"].performance_tier == "batch"

    def test_get_profile_returns_named_profile(self):
        from aether_os.core.stack_profiles import get_profile, STACK_PROFILES
        for name in STACK_PROFILES:
            assert get_profile(name).name == name

    def test_get_profile_falls_back_to_web_saas(self):
        from aether_os.core.stack_profiles import get_profile, DEFAULT_PROFILE
        assert get_profile("nonexistent_xyz").name == DEFAULT_PROFILE.name

    def test_profile_to_dict_all_keys_json_serialisable(self):
        from aether_os.core.stack_profiles import profile_to_dict, STACK_PROFILES
        required_keys = {
            "name", "build_type", "architecture", "backend_lang",
            "backend_framework", "frontend_framework", "db_primary",
            "db_secondary", "message_queue", "deployment_target",
            "performance_tier", "description",
        }
        for name, profile in STACK_PROFILES.items():
            d = profile_to_dict(profile)
            assert not (required_keys - set(d.keys())), f"{name}: missing keys"
            rt = json.loads(json.dumps(d))
            assert rt["name"] == name

    def test_inject_into_brief_sets_build_profile(self):
        from aether_os.core.stack_profiles import STACK_PROFILES
        from aether_os.phases.p00_research.stack_selector import inject_into_brief
        brief: Dict[str, Any] = {"spec": "test"}
        result = inject_into_brief(brief, STACK_PROFILES["go_api"])
        assert result["build_profile"]["name"] == "go_api"
        assert result["build_profile"]["backend_lang"] == "go"


# ── Stack Selector with Mock LLM ─────────────────────────────────────────────

class TestStackSelectorRouting:
    """classify_build routes spec text to expected profiles via mocked LLM."""

    def _classify(self, profile_key: str, spec: str, domain: str):
        from aether_os.phases.p00_research.stack_selector import classify_build

        async def run():
            mock_llm = AsyncMock()
            mock_llm.call_json = AsyncMock(
                return_value={"profile": profile_key, "confidence": 0.9, "reason": "test"}
            )
            with patch("aether_os.core.llm.client.get_llm_client", return_value=mock_llm):
                return await classify_build(spec, domain)

        return asyncio.run(run())

    def test_saas_dashboard_spec_returns_web_saas(self):
        p = self._classify("web_saas", "build a SaaS dashboard", "saas")
        assert p.name == "web_saas"
        assert p.backend_framework == "fastapi"

    def test_trading_api_spec_returns_go_api(self):
        p = self._classify("go_api", "build a high-throughput trading API", "fintech")
        assert p.name == "go_api"
        assert p.backend_lang == "go"

    def test_mobile_field_tech_spec_returns_mobile_rn(self):
        p = self._classify("mobile_rn", "build a mobile app for field technicians", "logistics")
        assert p.name == "mobile_rn"
        assert p.frontend_framework == "react_native"

    def test_microservices_platform_spec_returns_microservices(self):
        p = self._classify("microservices", "build a microservices platform", "ecommerce")
        assert p.name == "microservices"
        assert p.architecture == "microservices"

    def test_unknown_profile_falls_back_to_default(self):
        from aether_os.core.stack_profiles import DEFAULT_PROFILE
        p = self._classify("nonexistent_abc", "build something", "general")
        assert p.name == DEFAULT_PROFILE.name

    def test_llm_failure_falls_back_to_default(self):
        from aether_os.phases.p00_research.stack_selector import classify_build
        from aether_os.core.stack_profiles import DEFAULT_PROFILE

        async def run():
            with patch(
                "aether_os.core.llm.client.get_llm_client",
                side_effect=RuntimeError("LLM unavailable"),
            ):
                return await classify_build("build a SaaS dashboard", "saas")

        assert asyncio.run(run()).name == DEFAULT_PROFILE.name


# ── Domain Pack Integration ───────────────────────────────────────────────────

_ALL_PACK_DOMAINS = [
    "fintech", "healthcare", "ecommerce", "erp", "logistics",
    "saas", "trading", "legaltech", "real_estate", "manufacturing",
    "edtech", "govtech",
]


class TestDomainPackIntegration:
    """All 12 packs load without error and have required fields."""

    def test_all_12_packs_load_without_error(self):
        from aether_os.core.domain_knowledge.loader import load_pack, _cache
        _cache.clear()
        for domain in _ALL_PACK_DOMAINS:
            assert load_pack(domain) is not None, f"{domain!r} failed to load"

    def test_all_packs_have_display_name_entities_and_compliance(self):
        from aether_os.core.domain_knowledge.loader import load_pack
        for domain in _ALL_PACK_DOMAINS:
            pack = load_pack(domain)
            assert pack.display_name, f"{domain}: empty display_name"
            assert len(pack.entities) >= 1, f"{domain}: empty entities"
            assert len(pack.compliance) >= 1, f"{domain}: empty compliance"

    def test_all_packs_workflow_templates_field_exists(self):
        from aether_os.core.domain_knowledge.loader import load_pack
        for domain in _ALL_PACK_DOMAINS:
            pack = load_pack(domain)
            assert isinstance(pack.workflows, list), f"{domain}: workflows not a list"

    def test_all_packs_to_dict_full_required_keys(self):
        """to_dict_full() must return nested JSON with name, entities, compliance."""
        from aether_os.core.domain_knowledge.loader import load_pack
        required = {"domain", "display_name", "entities", "compliance", "workflows"}
        for domain in _ALL_PACK_DOMAINS:
            d = load_pack(domain).to_dict_full()
            assert not (required - set(d.keys())), f"{domain}: to_dict_full missing keys"
            for entity in d["entities"]:
                assert "name" in entity and "fields" in entity, f"{domain}: entity missing keys"

    def test_all_packs_to_dict_full_is_valid_json(self):
        from aether_os.core.domain_knowledge.loader import load_pack
        for domain in _ALL_PACK_DOMAINS:
            pack = load_pack(domain)
            rt = json.loads(json.dumps(pack.to_dict_full()))
            assert rt["domain"] == pack.domain

    def test_all_packs_compliance_rules_have_non_empty_standard_and_rule(self):
        from aether_os.core.domain_knowledge.loader import load_pack
        for domain in _ALL_PACK_DOMAINS:
            for rule in load_pack(domain).compliance:
                assert rule.standard, f"{domain}: compliance rule with empty standard"
                assert rule.rule, f"{domain}: compliance rule with empty rule text"


# ── Go Generator Integration ─────────────────────────────────────────────────

_SIMPLE_ENTITIES: List[Dict[str, Any]] = [
    {
        "name": "Widget",
        "table": "widget",
        "fields": [
            {"name": "id", "type": "int", "primary_key": True},
            {"name": "title", "type": "string"},
            {"name": "count", "type": "int"},
        ],
    }
]


class TestGoGeneratorIntegration:
    """go_generator.py produces valid Go syntax (package main, import, func)."""

    def test_go_project_has_package_main_import_func_main(self):
        from aether_os.phases.p04_backend.go_generator import generate_go_project
        with tempfile.TemporaryDirectory() as tmpdir:
            backend_dir = asyncio.run(generate_go_project(_SIMPLE_ENTITIES, "widgetapp", Path(tmpdir)))
            src = (backend_dir / "main.go").read_text()
            assert "package main" in src
            assert "import" in src
            assert "func main()" in src

    def test_go_model_has_struct_syntax(self):
        from aether_os.phases.p04_backend.go_generator import generate_go_model
        src = generate_go_model(_SIMPLE_ENTITIES[0])
        assert "package" in src
        assert "struct" in src

    def test_go_handler_has_gin_context_and_func(self):
        from aether_os.phases.p04_backend.go_generator import generate_go_handler
        src = generate_go_handler(_SIMPLE_ENTITIES[0], "github.com/test/widgetapp")
        assert "package" in src
        assert "func " in src
        assert "gin.Context" in src

    def test_go_mod_has_module_declaration(self):
        from aether_os.phases.p04_backend.go_generator import generate_go_mod
        src = generate_go_mod("github.com/test/widgetapp")
        assert src.strip().startswith("module")
        assert "github.com/test/widgetapp" in src

    def test_go_dockerfile_multistage(self):
        from aether_os.phases.p04_backend.go_generator import generate_go_dockerfile
        src = generate_go_dockerfile("widgetapp")
        assert src.count("FROM") >= 2
        assert "CGO_ENABLED=0" in src


# ── Node Generator Integration ────────────────────────────────────────────────

class TestNodeGeneratorIntegration:
    """node_generator.py produces valid TypeScript/Express output."""

    def test_node_project_has_package_json_with_name(self):
        from aether_os.phases.p04_backend.node_generator import generate_node_project
        with tempfile.TemporaryDirectory() as tmpdir:
            backend_dir = asyncio.run(generate_node_project(_SIMPLE_ENTITIES, "widgetapi", Path(tmpdir)))
            pkg = json.loads((backend_dir / "package.json").read_text())
            assert pkg["name"] == "widgetapi"

    def test_ts_model_has_typescript_type_markers(self):
        from aether_os.phases.p04_backend.node_generator import generate_ts_model
        src = generate_ts_model(_SIMPLE_ENTITIES[0])
        assert "Widget" in src
        assert "interface" in src or "class" in src or "type" in src

    def test_ts_route_has_handler_syntax(self):
        from aether_os.phases.p04_backend.node_generator import generate_ts_route
        src = generate_ts_route(_SIMPLE_ENTITIES[0])
        assert "Widget" in src
        assert "get" in src.lower() or "router" in src.lower() or "Route" in src

    def test_package_json_has_express_or_fastify(self):
        from aether_os.phases.p04_backend.node_generator import generate_package_json
        pkg = json.loads(generate_package_json("widgetapi"))
        all_deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
        assert any("fastify" in k or "express" in k for k in all_deps)

    def test_tsconfig_has_compiler_options(self):
        from aether_os.phases.p04_backend.node_generator import generate_tsconfig
        cfg = json.loads(generate_tsconfig())
        assert "compilerOptions" in cfg

    def test_node_dockerfile_uses_node_base_image(self):
        from aether_os.phases.p04_backend.node_generator import generate_node_dockerfile
        src = generate_node_dockerfile()
        assert "node" in src.lower() and "FROM" in src


# ── Compliance Manifest Writer ────────────────────────────────────────────────

class TestComplianceManifestWriter:
    """write_compliance_manifest produces valid JSON with required keys."""

    def test_manifest_written_to_disk_and_parseable(self):
        from aether_os.core.compliance.manifest_writer import write_compliance_manifest
        with tempfile.TemporaryDirectory() as tmpdir:
            write_compliance_manifest(tmpdir, "fintech", "TestApp")
            content = json.loads((Path(tmpdir) / "compliance_manifest.json").read_text())
            assert "drift_fingerprint" in content and "overall_score" in content

    def test_manifest_has_drift_fingerprint_sha256(self):
        from aether_os.core.compliance.manifest_writer import write_compliance_manifest
        with tempfile.TemporaryDirectory() as tmpdir:
            result = write_compliance_manifest(tmpdir, "fintech", "TestApp")
            assert len(result["drift_fingerprint"]) == 64

    def test_manifest_has_overall_score_and_components(self):
        from aether_os.core.compliance.manifest_writer import write_compliance_manifest
        with tempfile.TemporaryDirectory() as tmpdir:
            result = write_compliance_manifest(tmpdir, "healthcare", "ClinicPro")
            assert "overall_score" in result
            assert isinstance(result["components"], list)

    def test_manifest_records_project_name_and_domain(self):
        from aether_os.core.compliance.manifest_writer import write_compliance_manifest
        with tempfile.TemporaryDirectory() as tmpdir:
            result = write_compliance_manifest(tmpdir, "ecommerce", "ShopBot")
            assert result["project_name"] == "ShopBot"
            assert result["domain"] == "ecommerce"

    def test_manifest_empty_project_yields_zero_score(self):
        from aether_os.core.compliance.manifest_writer import write_compliance_manifest
        with tempfile.TemporaryDirectory() as tmpdir:
            result = write_compliance_manifest(tmpdir, "general", "EmptyApp")
            assert result["overall_score"] == 0
            assert result["components"] == []

    def test_manifest_with_fastapi_routes_has_fingerprint(self):
        """A main.py with routes must produce a non-empty drift fingerprint."""
        from aether_os.core.compliance.manifest_writer import write_compliance_manifest
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "main.py").write_text(
                "from fastapi import FastAPI\napp = FastAPI()\n"
                "@app.get('/health')\ndef health(): return {'ok': True}\n"
                "@app.post('/items')\ndef create_item(): return {}\n"
            )
            result = write_compliance_manifest(tmpdir, "saas", "MyApp")
            assert result["drift_fingerprint"] != ""


# ── Business Model Generator ──────────────────────────────────────────────────

class TestBusinessModelGenerator:
    """generate_business_model produces required keys even when LLM is unavailable."""

    def _run_fallback(self, requirement: str, domain: str) -> dict:
        from aether_os.phases.p00_research.business_model_generator import generate_business_model

        async def run():
            with patch(
                "aether_os.phases.p00_research.business_model_generator.get_llm_client",
                side_effect=RuntimeError("LLM not available in tests"),
            ):
                with tempfile.TemporaryDirectory() as tmpdir:
                    return await generate_business_model(
                        requirement, domain, "web_saas", Path(tmpdir)
                    )

        return asyncio.run(run())

    def test_has_target_market_and_value_proposition(self):
        result = self._run_fallback("Build a CRM for SMBs", "saas")
        assert isinstance(result["target_market"], str) and result["target_market"]
        assert isinstance(result["value_proposition"], str) and result["value_proposition"]

    def test_has_revenue_model_string(self):
        result = self._run_fallback("Build a billing platform", "fintech")
        assert isinstance(result["revenue_model"], str)

    def test_has_pricing_tiers_list(self):
        result = self._run_fallback("Build a task manager", "saas")
        assert isinstance(result["pricing_tiers"], list)
        assert len(result["pricing_tiers"]) >= 1

    def test_has_market_size_fields(self):
        result = self._run_fallback("Build an LMS", "edtech")
        for key in ("tam_usd_billions", "sam_usd_billions", "som_usd_millions"):
            assert key in result, f"missing {key}"

    def test_has_go_to_market(self):
        result = self._run_fallback("Build a marketplace", "ecommerce")
        assert isinstance(result["go_to_market"], str)

    def test_written_to_disk_as_valid_json(self):
        from aether_os.phases.p00_research.business_model_generator import generate_business_model

        async def run():
            with patch(
                "aether_os.phases.p00_research.business_model_generator.get_llm_client",
                side_effect=RuntimeError("LLM not available in tests"),
            ):
                with tempfile.TemporaryDirectory() as tmpdir:
                    path = Path(tmpdir)
                    await generate_business_model("Build a HR tool", "saas", "web_saas", path)
                    content = json.loads((path / "business_model.json").read_text())
                    assert "target_market" in content

        asyncio.run(run())

    def test_includes_domain_metadata_and_is_json_serialisable(self):
        result = self._run_fallback("Build a fleet tracker", "logistics")
        assert result["domain"] == "logistics"
        assert "generated_by" in result
        rt = json.loads(json.dumps(result))
        assert "target_market" in rt
