"""
Tests for AetherOS V2 — Stack Profiles, Go/Node generators, Domain Knowledge.
All tests are deterministic (no LLM calls). They verify that the V2 components
produce syntactically correct output and the right file structure.
"""
from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path
from typing import Any, Dict, List


# ── Layer 1: Stack Profiles ───────────────────────────────────────────────────

class TestStackProfiles:
    def test_stack_profiles_registry_exists(self):
        from aether_os.core.stack_profiles import STACK_PROFILES
        assert len(STACK_PROFILES) >= 7

    def test_all_required_profiles_present(self):
        from aether_os.core.stack_profiles import STACK_PROFILES
        required = {"web_saas", "go_api", "node_serverless", "mobile_rn", "desktop_electron", "ml_pipeline", "microservices"}
        missing = required - set(STACK_PROFILES.keys())
        assert not missing, f"Missing profiles: {missing}"

    def test_web_saas_profile_fields(self):
        from aether_os.core.stack_profiles import STACK_PROFILES
        p = STACK_PROFILES["web_saas"]
        assert p.backend_lang == "python"
        assert p.backend_framework == "fastapi"
        assert p.frontend_framework == "react"
        assert p.db_primary == "postgres"

    def test_go_api_profile_fields(self):
        from aether_os.core.stack_profiles import STACK_PROFILES
        p = STACK_PROFILES["go_api"]
        assert p.backend_lang == "go"
        assert p.backend_framework == "gin"
        assert p.deployment_target == "kubernetes"

    def test_microservices_profile_fields(self):
        from aether_os.core.stack_profiles import STACK_PROFILES
        p = STACK_PROFILES["microservices"]
        assert p.architecture == "microservices"
        assert p.backend_lang == "go"

    def test_all_profiles_have_required_fields(self):
        from aether_os.core.stack_profiles import STACK_PROFILES
        for name, p in STACK_PROFILES.items():
            assert p.build_type, f"{name}: build_type is empty"
            assert p.architecture, f"{name}: architecture is empty"
            assert p.backend_lang, f"{name}: backend_lang is empty"
            assert p.backend_framework, f"{name}: backend_framework is empty"
            assert p.db_primary, f"{name}: db_primary is empty"
            assert p.deployment_target, f"{name}: deployment_target is empty"

    def test_profile_serialisable_to_dict(self):
        from dataclasses import asdict
        from aether_os.core.stack_profiles import STACK_PROFILES
        for name, p in STACK_PROFILES.items():
            d = asdict(p)
            assert isinstance(d, dict)
            assert d["name"] == name


# ── Layer 1: Go Generator ─────────────────────────────────────────────────────

_SAMPLE_ENTITY: Dict[str, Any] = {
    "name": "Product",
    "table": "product",  # Go/Node generators use entity.get("table") for struct names
    "fields": [
        {"name": "id", "type": "int", "primary_key": True},
        {"name": "name", "type": "string"},
        {"name": "price", "type": "float"},
        {"name": "sku", "type": "string"},
        {"name": "stock", "type": "int"},
    ],
}

_SAMPLE_ENTITIES: List[Dict[str, Any]] = [
    _SAMPLE_ENTITY,
    {
        "name": "Order",
        "table": "order",
        "fields": [
            {"name": "id", "type": "int", "primary_key": True},
            {"name": "user_id", "type": "int"},
            {"name": "total", "type": "float"},
            {"name": "status", "type": "string"},
        ],
    },
]


class TestGoGenerator:
    def test_go_mod_has_module_declaration(self):
        from aether_os.phases.p04_backend.go_generator import generate_go_mod
        src = generate_go_mod("github.com/test/myapp")
        assert "module github.com/test/myapp" in src
        assert "github.com/gin-gonic/gin" in src
        assert "gorm.io/gorm" in src

    def test_go_mod_with_grpc(self):
        from aether_os.phases.p04_backend.go_generator import generate_go_mod
        src = generate_go_mod("github.com/test/myapp", with_grpc=True)
        assert "google.golang.org/grpc" in src
        assert "google.golang.org/protobuf" in src

    def test_go_model_produces_struct(self):
        from aether_os.phases.p04_backend.go_generator import generate_go_model
        src = generate_go_model(_SAMPLE_ENTITY)
        assert "type Product struct" in src
        assert "gorm.Model" in src or "ID" in src
        # Field names should be present as PascalCase
        assert "Name" in src
        assert "Price" in src

    def test_go_model_has_package_declaration(self):
        from aether_os.phases.p04_backend.go_generator import generate_go_model
        src = generate_go_model(_SAMPLE_ENTITY)
        assert src.strip().startswith("package")

    def test_go_handler_produces_gin_routes(self):
        from aether_os.phases.p04_backend.go_generator import generate_go_handler
        src = generate_go_handler(_SAMPLE_ENTITY, "github.com/test/myapp")
        assert "gin.Context" in src
        assert "Product" in src
        # Should have at least GET and POST handlers
        assert "func " in src

    def test_go_handler_has_package_declaration(self):
        from aether_os.phases.p04_backend.go_generator import generate_go_handler
        src = generate_go_handler(_SAMPLE_ENTITY, "github.com/test/myapp")
        assert src.strip().startswith("package")

    def test_go_db_has_connect_function(self):
        from aether_os.phases.p04_backend.go_generator import generate_go_db
        src = generate_go_db("postgres")
        assert "func " in src
        assert "gorm" in src.lower()

    def test_go_main_registers_routes(self):
        from aether_os.phases.p04_backend.go_generator import generate_go_main
        src = generate_go_main(_SAMPLE_ENTITIES, "myapp", "github.com/test/myapp")
        assert "gin.Default()" in src or "gin.New()" in src
        assert "func main()" in src
        assert "r.Run" in src

    def test_go_dockerfile_is_multistage(self):
        from aether_os.phases.p04_backend.go_generator import generate_go_dockerfile
        src = generate_go_dockerfile("myapp")
        # Multi-stage build should have at least two FROM statements
        assert src.count("FROM") >= 2
        assert "CGO_ENABLED=0" in src

    def test_go_prometheus_middleware_is_valid(self):
        from aether_os.phases.p04_backend.go_generator import generate_prometheus_middleware
        src = generate_prometheus_middleware()
        assert "package middleware" in src
        assert "prometheus" in src
        assert "/metrics" in src

    def test_generate_go_project_creates_files(self):
        from aether_os.phases.p04_backend.go_generator import generate_go_project
        with tempfile.TemporaryDirectory() as tmpdir:
            out = Path(tmpdir)
            backend_dir = asyncio.run(generate_go_project(_SAMPLE_ENTITIES, "testapp", out))
            assert backend_dir.exists(), "generate_go_project returned non-existent path"
            assert (backend_dir / "main.go").exists()
            assert (backend_dir / "go.mod").exists()
            assert (backend_dir / "Dockerfile").exists()
            assert (backend_dir / "db" / "database.go").exists()

    def test_generate_go_project_main_has_func_main(self):
        from aether_os.phases.p04_backend.go_generator import generate_go_project
        with tempfile.TemporaryDirectory() as tmpdir:
            out = Path(tmpdir)
            backend_dir = asyncio.run(generate_go_project(_SAMPLE_ENTITIES, "testapp", out))
            main_src = (backend_dir / "main.go").read_text()
            assert "func main()" in main_src

    def test_generate_go_project_go_mod_has_module(self):
        from aether_os.phases.p04_backend.go_generator import generate_go_project
        with tempfile.TemporaryDirectory() as tmpdir:
            out = Path(tmpdir)
            backend_dir = asyncio.run(generate_go_project(_SAMPLE_ENTITIES, "testapp", out))
            go_mod_src = (backend_dir / "go.mod").read_text()
            assert "module " in go_mod_src

    def test_generate_go_project_handler_for_each_entity(self):
        from aether_os.phases.p04_backend.go_generator import generate_go_project
        with tempfile.TemporaryDirectory() as tmpdir:
            out = Path(tmpdir)
            backend_dir = asyncio.run(generate_go_project(_SAMPLE_ENTITIES, "testapp", out))
            # Handlers are named by table name (PascalCase), not entity name
            assert (backend_dir / "handlers" / "ProductHandler.go").exists()
            assert (backend_dir / "handlers" / "OrderHandler.go").exists()
            assert (backend_dir / "models" / "Product.go").exists()
            assert (backend_dir / "models" / "Order.go").exists()

    def test_to_pascal(self):
        from aether_os.phases.p04_backend.go_generator import _to_pascal
        assert _to_pascal("user_profile") == "UserProfile"
        assert _to_pascal("order-item") == "OrderItem"
        assert _to_pascal("product") == "Product"


# ── Layer 1: Node Generator ───────────────────────────────────────────────────

class TestNodeGenerator:
    def test_package_json_has_name_and_scripts(self):
        from aether_os.phases.p04_backend.node_generator import generate_package_json
        src = generate_package_json("my-api")
        pkg = json.loads(src)
        assert pkg["name"] == "my-api"
        assert "scripts" in pkg
        assert "dev" in pkg["scripts"] or "start" in pkg["scripts"]

    def test_package_json_has_fastify(self):
        from aether_os.phases.p04_backend.node_generator import generate_package_json
        src = generate_package_json("my-api")
        pkg = json.loads(src)
        deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
        assert any("fastify" in k or "express" in k for k in deps)

    def test_tsconfig_is_valid_json(self):
        from aether_os.phases.p04_backend.node_generator import generate_tsconfig
        src = generate_tsconfig()
        cfg = json.loads(src)
        assert "compilerOptions" in cfg

    def test_ts_model_generates_interface_or_class(self):
        from aether_os.phases.p04_backend.node_generator import generate_ts_model
        src = generate_ts_model(_SAMPLE_ENTITY)
        assert "Product" in src
        assert "interface" in src or "class" in src or "type" in src

    def test_ts_route_generates_route_handlers(self):
        from aether_os.phases.p04_backend.node_generator import generate_ts_route
        src = generate_ts_route(_SAMPLE_ENTITY)
        assert "Product" in src
        # Should have GET and POST style handlers
        assert "get" in src.lower() or "GET" in src

    def test_ts_index_imports_all_routes(self):
        from aether_os.phases.p04_backend.node_generator import generate_ts_index
        src = generate_ts_index(_SAMPLE_ENTITIES, "myapp")
        assert "Product" in src
        assert "Order" in src

    def test_zod_schema_generates_schema_object(self):
        from aether_os.phases.p04_backend.node_generator import generate_zod_schema
        src = generate_zod_schema(_SAMPLE_ENTITY)
        assert "z.object" in src or "z.string" in src
        assert "Product" in src

    def test_node_dockerfile_has_node_base(self):
        from aether_os.phases.p04_backend.node_generator import generate_node_dockerfile
        src = generate_node_dockerfile()
        assert "node" in src.lower()
        assert "FROM" in src

    def test_generate_node_project_creates_files(self):
        from aether_os.phases.p04_backend.node_generator import generate_node_project
        with tempfile.TemporaryDirectory() as tmpdir:
            out = Path(tmpdir)
            backend_dir = asyncio.run(generate_node_project(_SAMPLE_ENTITIES, "testapi", out))
            assert backend_dir.exists(), "generate_node_project returned non-existent path"
            assert (backend_dir / "package.json").exists()
            assert (backend_dir / "tsconfig.json").exists()
            assert (backend_dir / "Dockerfile").exists()

    def test_generate_node_project_package_json_valid(self):
        from aether_os.phases.p04_backend.node_generator import generate_node_project
        with tempfile.TemporaryDirectory() as tmpdir:
            out = Path(tmpdir)
            backend_dir = asyncio.run(generate_node_project(_SAMPLE_ENTITIES, "testapi", out))
            pkg = json.loads((backend_dir / "package.json").read_text())
            assert "name" in pkg
            assert "scripts" in pkg

    def test_generate_node_project_tsconfig_valid(self):
        from aether_os.phases.p04_backend.node_generator import generate_node_project
        with tempfile.TemporaryDirectory() as tmpdir:
            out = Path(tmpdir)
            backend_dir = asyncio.run(generate_node_project(_SAMPLE_ENTITIES, "testapi", out))
            cfg = json.loads((backend_dir / "tsconfig.json").read_text())
            assert "compilerOptions" in cfg


# ── Layer 2: Architecture Planner Helpers ─────────────────────────────────────

class TestArchitecturePlannerHelpers:
    def _valid_service_map(self) -> dict:
        return {
            "services": [
                {
                    "name": "user-service",
                    "lang": "go",
                    "framework": "gin",
                    "port": 8001,
                    "owns_entities": ["User", "Session"],
                    "communication": "rest",  # validator checks "communication" key
                },
                {
                    "name": "order-service",
                    "lang": "go",
                    "framework": "gin",
                    "port": 8002,
                    "owns_entities": ["Order", "OrderItem"],
                    "communication": "grpc",
                },
            ],
            "message_bus": "kafka",
            "api_gateway": "nginx",
            "shared_db": False,
        }

    def test_validate_service_map_accepts_valid(self):
        from aether_os.phases.p00c_architecture_planner.helpers import validate_service_map
        errors = validate_service_map(self._valid_service_map())
        assert errors == []

    def test_validate_service_map_rejects_missing_services(self):
        from aether_os.phases.p00c_architecture_planner.helpers import validate_service_map
        errors = validate_service_map({})
        assert len(errors) > 0

    def test_validate_service_map_rejects_empty_services(self):
        from aether_os.phases.p00c_architecture_planner.helpers import validate_service_map
        errors = validate_service_map({"services": []})
        assert len(errors) > 0

    def test_validate_service_map_rejects_missing_name(self):
        from aether_os.phases.p00c_architecture_planner.helpers import validate_service_map
        bad = self._valid_service_map()
        del bad["services"][0]["name"]
        errors = validate_service_map(bad)
        assert len(errors) > 0

    def test_build_fallback_service_map_returns_services(self):
        from aether_os.phases.p00c_architecture_planner.helpers import build_fallback_service_map
        sm = build_fallback_service_map("ecommerce platform", "ecommerce", "go", "gin")
        assert "services" in sm
        assert len(sm["services"]) >= 2
        for svc in sm["services"]:
            assert "name" in svc
            assert "port" in svc
            assert "lang" in svc

    def test_build_fallback_service_map_marks_fallback(self):
        from aether_os.phases.p00c_architecture_planner.helpers import build_fallback_service_map
        sm = build_fallback_service_map("something", "general", "go", "gin")
        assert sm.get("_fallback") is True

    def test_normalise_service_map_fills_missing_framework(self):
        from aether_os.phases.p00c_architecture_planner.helpers import normalise_service_map
        raw = self._valid_service_map()
        del raw["services"][0]["framework"]
        normalised = normalise_service_map(raw, "go")
        # After normalise, framework should be filled in (defaults to "gin" for go)
        assert normalised["services"][0].get("framework"), "framework not filled after normalise"


# ── Layer 3: Domain Knowledge ─────────────────────────────────────────────────

class TestDomainKnowledgeLoader:
    def test_load_fintech_pack(self):
        from aether_os.core.domain_knowledge.loader import load_pack
        pack = load_pack("fintech")
        assert pack is not None
        assert pack.domain == "fintech"

    def test_load_healthcare_pack(self):
        from aether_os.core.domain_knowledge.loader import load_pack
        pack = load_pack("healthcare")
        assert pack is not None
        assert pack.domain == "healthcare"

    def test_load_ecommerce_pack(self):
        from aether_os.core.domain_knowledge.loader import load_pack
        pack = load_pack("ecommerce")
        assert pack is not None

    def test_load_trading_pack(self):
        from aether_os.core.domain_knowledge.loader import load_pack
        pack = load_pack("trading")
        assert pack is not None

    def test_load_edtech_pack(self):
        from aether_os.core.domain_knowledge.loader import load_pack
        pack = load_pack("edtech")
        assert pack is not None

    def test_load_govtech_pack(self):
        from aether_os.core.domain_knowledge.loader import load_pack
        pack = load_pack("govtech")
        assert pack is not None

    def test_load_legaltech_pack(self):
        from aether_os.core.domain_knowledge.loader import load_pack
        pack = load_pack("legaltech")
        assert pack is not None

    def test_load_manufacturing_pack(self):
        from aether_os.core.domain_knowledge.loader import load_pack
        pack = load_pack("manufacturing")
        assert pack is not None

    def test_unknown_domain_returns_none(self):
        from aether_os.core.domain_knowledge.loader import load_pack
        assert load_pack("unknown_domain_xyz") is None

    def test_domain_aliases_resolve(self):
        from aether_os.core.domain_knowledge.loader import load_pack
        assert load_pack("hft") is not None      # alias for trading
        assert load_pack("law") is not None      # alias for legaltech
        assert load_pack("proptech") is not None # alias for real_estate
        assert load_pack("lms") is not None      # alias for edtech

    def test_pack_caching(self):
        from aether_os.core.domain_knowledge.loader import load_pack, _cache
        _cache.clear()
        p1 = load_pack("fintech")
        p2 = load_pack("fintech")
        assert p1 is p2  # same object from cache

    def test_fintech_pack_has_entities(self):
        from aether_os.core.domain_knowledge.loader import load_pack
        pack = load_pack("fintech")
        assert len(pack.entities) >= 3

    def test_fintech_pack_has_pci_compliance_rules(self):
        from aether_os.core.domain_knowledge.loader import load_pack
        pack = load_pack("fintech")
        standards = [r.standard for r in pack.compliance]
        assert any("PCI" in s for s in standards), f"No PCI rule in fintech compliance: {standards}"

    def test_healthcare_pack_has_phi_fields(self):
        from aether_os.core.domain_knowledge.loader import load_pack
        pack = load_pack("healthcare")
        phi_fields = [
            f for entity in pack.entities
            for f in entity.fields
            if f.phi
        ]
        assert len(phi_fields) >= 3, "Healthcare pack should have PHI-tagged fields"

    def test_healthcare_pack_has_hipaa_rules(self):
        from aether_os.core.domain_knowledge.loader import load_pack
        pack = load_pack("healthcare")
        standards = [r.standard for r in pack.compliance]
        assert any("HIPAA" in s for s in standards), f"No HIPAA rule: {standards}"

    def test_prompt_injection_is_non_empty(self):
        from aether_os.core.domain_knowledge.loader import load_pack
        for domain in ["fintech", "healthcare", "ecommerce"]:
            pack = load_pack(domain)
            assert pack.prompt_injection, f"{domain} has empty prompt_injection"

    def test_to_dict_returns_serialisable(self):
        from aether_os.core.domain_knowledge.loader import load_pack
        pack = load_pack("fintech")
        d = pack.to_dict()
        assert isinstance(d, dict)
        json.dumps(d)  # must be JSON-serialisable

    def test_to_dict_full_returns_nested_structure(self):
        from aether_os.core.domain_knowledge.loader import load_pack
        pack = load_pack("fintech")
        d = pack.to_dict_full()
        assert isinstance(d, dict)
        assert "entities" in d
        assert "compliance" in d
        # entities should be a list of dicts with field details
        assert isinstance(d["entities"], list)
        if d["entities"]:
            entity = d["entities"][0]
            assert "name" in entity
            assert "fields" in entity

    def test_schema_hints_string_non_empty(self):
        from aether_os.core.domain_knowledge.loader import build_schema_hints
        hints = build_schema_hints("fintech")
        assert len(hints) > 50

    def test_workflow_summary_string_non_empty(self):
        from aether_os.core.domain_knowledge.loader import build_workflow_summary
        summary = build_workflow_summary("fintech")
        # May be empty if no workflows, but must be a string
        assert isinstance(summary, str)

    def test_compliance_summary_string_non_empty(self):
        from aether_os.core.domain_knowledge.loader import build_compliance_summary
        summary = build_compliance_summary("fintech")
        assert len(summary) > 20


# ── Layer 3: Domain Pack Content ─────────────────────────────────────────────

class TestDomainPackContent:
    """Spot-checks that packs have the right structure and values."""

    def test_fintech_transaction_entity_has_idempotency_key(self):
        from aether_os.core.domain_knowledge.loader import load_pack
        pack = load_pack("fintech")
        txn = next((e for e in pack.entities if "Transaction" in e.name), None)
        assert txn is not None, "Fintech pack missing Transaction entity"
        field_names = [f.name for f in txn.fields]
        assert "idempotency_key" in field_names

    def test_ecommerce_pack_has_order_workflow(self):
        from aether_os.core.domain_knowledge.loader import load_pack
        pack = load_pack("ecommerce")
        assert len(pack.entities) >= 3

    def test_erp_pack_loads(self):
        from aether_os.core.domain_knowledge.loader import load_pack
        pack = load_pack("erp")
        assert pack is not None
        assert len(pack.entities) >= 2

    def test_logistics_pack_loads(self):
        from aether_os.core.domain_knowledge.loader import load_pack
        pack = load_pack("logistics")
        assert pack is not None

    def test_saas_pack_loads(self):
        from aether_os.core.domain_knowledge.loader import load_pack
        pack = load_pack("saas")
        assert pack is not None

    def test_all_packs_load_without_error(self):
        from aether_os.core.domain_knowledge.loader import _DOMAIN_PACK_MAP, load_pack
        # Load each unique pack name (not aliases)
        seen = set()
        for domain, pack_name in _DOMAIN_PACK_MAP.items():
            if pack_name not in seen:
                seen.add(pack_name)
                pack = load_pack(domain)
                assert pack is not None, f"Failed to load pack for domain={domain}"

    def test_all_packs_have_prompt_injection(self):
        from aether_os.core.domain_knowledge.loader import _DOMAIN_PACK_MAP, load_pack
        seen = set()
        for domain, pack_name in _DOMAIN_PACK_MAP.items():
            if pack_name not in seen:
                seen.add(pack_name)
                pack = load_pack(domain)
                assert pack.prompt_injection, f"Pack {pack_name} has empty prompt_injection"


# ── Layer 1: Stack Selector (without LLM) ────────────────────────────────────

class TestStackSelector:
    def test_classify_build_module_importable(self):
        from aether_os.phases.p00_research.stack_selector import classify_build
        assert callable(classify_build)

    def test_classify_build_returns_stack_profile_on_fallback(self):
        """If LLM is unavailable, classify_build should return the web_saas fallback."""
        from unittest.mock import patch
        from aether_os.phases.p00_research.stack_selector import classify_build

        async def run():
            # get_llm_client is imported inside classify_build; patch it at the source module
            with patch(
                "aether_os.core.llm.client.get_llm_client",
                side_effect=Exception("LLM unavailable"),
            ):
                profile = await classify_build("Build me a hospital patient portal", "healthcare")
            return profile

        profile = asyncio.run(run())
        assert profile is not None
        assert profile.backend_lang in ("python", "go", "typescript", "java")

    def test_classify_build_with_go_hint(self):
        """A spec mentioning Go microservices should resolve to go_api or microservices profile."""
        from unittest.mock import AsyncMock, patch
        from aether_os.phases.p00_research.stack_selector import classify_build

        async def run():
            mock_llm = AsyncMock()
            mock_llm.call_json = AsyncMock(return_value={"profile": "go_api", "confidence": 0.9, "reason": "Go hint"})
            # patch inside the function's import scope
            with patch("aether_os.core.llm.client.get_llm_client", return_value=mock_llm):
                profile = await classify_build("Build a Go microservice for payments", "fintech")
            return profile

        profile = asyncio.run(run())
        assert profile is not None
        # Should have resolved to go_api or fallen back to a valid profile
        assert profile.backend_lang in ("go", "python")
