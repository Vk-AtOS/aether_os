"""
AetherOS — Go/Gin Generator Unit Tests

Covers:
  phases/p04_backend/go_generator.py — struct/model, route/handler, middleware,
                                        env, main.go, Dockerfile, multiservice
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Dict, List

import pytest

# ── Shared fixtures ────────────────────────────────────────────────────────────

_ENTITY_USER: Dict[str, Any] = {
    "table": "user",
    "fields": [
        {"name": "username", "type": "string"},
        {"name": "email", "type": "string"},
        {"name": "age", "type": "int"},
        {"name": "active", "type": "bool"},
        {"name": "score", "type": "float"},
        {"name": "org_id", "type": "fk"},
    ],
}

_ENTITY_ORDER: Dict[str, Any] = {
    "table": "order",
    "fields": [
        {"name": "total", "type": "float"},
        {"name": "status", "type": "string"},
        {"name": "created_date", "type": "datetime"},
    ],
}

_ENTITIES: List[Dict[str, Any]] = [_ENTITY_USER, _ENTITY_ORDER]
_MODULE = "github.com/aetheros/myapp"


# ═══════════════════════════════════════════════════════════════════════════════
# Struct / Model Generation
# ═══════════════════════════════════════════════════════════════════════════════

class TestGoModelGeneration:
    """Tests for generate_go_model — verifies correct Go struct output."""

    def test_model_package_is_models(self):
        from aether_os.phases.p04_backend.go_generator import generate_go_model
        src = generate_go_model(_ENTITY_USER)
        assert src.strip().startswith("package models")

    def test_model_struct_name_is_pascal_cased(self):
        from aether_os.phases.p04_backend.go_generator import generate_go_model
        src = generate_go_model({"table": "order_item", "fields": []})
        assert "type OrderItem struct" in src

    def test_model_has_gorm_primary_key(self):
        from aether_os.phases.p04_backend.go_generator import generate_go_model
        src = generate_go_model(_ENTITY_USER)
        assert "primarykey" in src

    def test_model_maps_field_types_correctly(self):
        from aether_os.phases.p04_backend.go_generator import generate_go_model
        src = generate_go_model(_ENTITY_USER)
        assert "int" in src
        assert "float64" in src
        assert "bool" in src
        assert "uint" in src

    def test_model_datetime_field_maps_to_time(self):
        from aether_os.phases.p04_backend.go_generator import generate_go_model
        src = generate_go_model(_ENTITY_ORDER)
        assert "time.Time" in src

    def test_model_table_name_method_returns_table(self):
        from aether_os.phases.p04_backend.go_generator import generate_go_model
        src = generate_go_model(_ENTITY_USER)
        assert 'return "user"' in src

    def test_model_field_names_pascal_cased(self):
        from aether_os.phases.p04_backend.go_generator import generate_go_model
        src = generate_go_model(_ENTITY_USER)
        assert "OrgId" in src

    def test_model_unknown_type_falls_back_to_string(self):
        from aether_os.phases.p04_backend.go_generator import generate_go_model
        entity = {"table": "thing", "fields": [{"name": "data", "type": "blob"}]}
        src = generate_go_model(entity)
        assert "string" in src

    def test_model_includes_json_tag(self):
        from aether_os.phases.p04_backend.go_generator import generate_go_model
        src = generate_go_model(_ENTITY_USER)
        assert "json:" in src

    def test_model_has_created_at_updated_at(self):
        from aether_os.phases.p04_backend.go_generator import generate_go_model
        src = generate_go_model(_ENTITY_USER)
        assert "CreatedAt" in src
        assert "UpdatedAt" in src


# ═══════════════════════════════════════════════════════════════════════════════
# Route / Handler Generation
# ═══════════════════════════════════════════════════════════════════════════════

class TestGoHandlerGeneration:
    """Tests for generate_go_handler — verifies CRUD handler functions."""

    def test_handler_package_is_handlers(self):
        from aether_os.phases.p04_backend.go_generator import generate_go_handler
        src = generate_go_handler(_ENTITY_USER, _MODULE)
        assert src.strip().startswith("package handlers")

    def test_handler_has_list_function(self):
        from aether_os.phases.p04_backend.go_generator import generate_go_handler
        src = generate_go_handler(_ENTITY_USER, _MODULE)
        assert "func ListUser" in src

    def test_handler_has_create_function(self):
        from aether_os.phases.p04_backend.go_generator import generate_go_handler
        src = generate_go_handler(_ENTITY_USER, _MODULE)
        assert "func CreateUser" in src

    def test_handler_has_get_function(self):
        from aether_os.phases.p04_backend.go_generator import generate_go_handler
        src = generate_go_handler(_ENTITY_USER, _MODULE)
        assert "func GetUser" in src

    def test_handler_has_update_function(self):
        from aether_os.phases.p04_backend.go_generator import generate_go_handler
        src = generate_go_handler(_ENTITY_USER, _MODULE)
        assert "func UpdateUser" in src

    def test_handler_has_delete_function(self):
        from aether_os.phases.p04_backend.go_generator import generate_go_handler
        src = generate_go_handler(_ENTITY_USER, _MODULE)
        assert "func DeleteUser" in src

    def test_handler_registers_routes(self):
        from aether_os.phases.p04_backend.go_generator import generate_go_handler
        src = generate_go_handler(_ENTITY_USER, _MODULE)
        assert "func RegisterUserRoutes" in src

    def test_handler_uses_correct_http_status_codes(self):
        from aether_os.phases.p04_backend.go_generator import generate_go_handler
        src = generate_go_handler(_ENTITY_USER, _MODULE)
        assert "http.StatusOK" in src
        assert "http.StatusCreated" in src
        assert "http.StatusBadRequest" in src

    def test_handler_imports_module_db(self):
        from aether_os.phases.p04_backend.go_generator import generate_go_handler
        src = generate_go_handler(_ENTITY_USER, _MODULE)
        assert f'"{_MODULE}/db"' in src

    def test_handler_imports_module_models(self):
        from aether_os.phases.p04_backend.go_generator import generate_go_handler
        src = generate_go_handler(_ENTITY_USER, _MODULE)
        assert f'"{_MODULE}/models"' in src

    def test_handler_table_route_path_in_gin_group(self):
        from aether_os.phases.p04_backend.go_generator import generate_go_handler
        src = generate_go_handler(_ENTITY_USER, _MODULE)
        assert '"/user"' in src

    def test_handler_uses_strconv_param_parsing(self):
        from aether_os.phases.p04_backend.go_generator import generate_go_handler
        src = generate_go_handler(_ENTITY_USER, _MODULE)
        assert "strconv.Atoi" in src or "c.Param" in src


# ═══════════════════════════════════════════════════════════════════════════════
# Middleware Injection
# ═══════════════════════════════════════════════════════════════════════════════

class TestGoMiddleware:
    """Tests for generate_prometheus_middleware and generate_zerolog_setup."""

    def test_prometheus_middleware_package_is_middleware(self):
        from aether_os.phases.p04_backend.go_generator import generate_prometheus_middleware
        src = generate_prometheus_middleware()
        assert "package middleware" in src

    def test_prometheus_middleware_has_metrics_func(self):
        from aether_os.phases.p04_backend.go_generator import generate_prometheus_middleware
        src = generate_prometheus_middleware()
        assert "func Metrics()" in src

    def test_prometheus_middleware_has_handler_func(self):
        from aether_os.phases.p04_backend.go_generator import generate_prometheus_middleware
        src = generate_prometheus_middleware()
        assert "func MetricsHandler()" in src

    def test_prometheus_middleware_counters_with_method_path_status(self):
        from aether_os.phases.p04_backend.go_generator import generate_prometheus_middleware
        src = generate_prometheus_middleware()
        assert "method" in src
        assert "path" in src
        assert "status" in src

    def test_prometheus_middleware_imports_prometheus(self):
        from aether_os.phases.p04_backend.go_generator import generate_prometheus_middleware
        src = generate_prometheus_middleware()
        assert "prometheus/client_golang" in src

    def test_zerolog_setup_package_is_logger(self):
        from aether_os.phases.p04_backend.go_generator import generate_zerolog_setup
        src = generate_zerolog_setup()
        assert "package logger" in src

    def test_zerolog_setup_has_init_func(self):
        from aether_os.phases.p04_backend.go_generator import generate_zerolog_setup
        src = generate_zerolog_setup()
        assert "func Init(" in src

    def test_zerolog_setup_exports_log_var(self):
        from aether_os.phases.p04_backend.go_generator import generate_zerolog_setup
        src = generate_zerolog_setup()
        assert "var Log" in src

    def test_zerolog_setup_includes_service_name_field(self):
        from aether_os.phases.p04_backend.go_generator import generate_zerolog_setup
        src = generate_zerolog_setup()
        assert "service" in src

    def test_main_wires_prometheus_middleware(self):
        from aether_os.phases.p04_backend.go_generator import generate_go_main
        src = generate_go_main(_ENTITIES, "myapp", _MODULE)
        assert "middleware.Metrics()" in src

    def test_main_wires_metrics_endpoint(self):
        from aether_os.phases.p04_backend.go_generator import generate_go_main
        src = generate_go_main(_ENTITIES, "myapp", _MODULE)
        assert "middleware.MetricsHandler()" in src


# ═══════════════════════════════════════════════════════════════════════════════
# go.mod and Environment
# ═══════════════════════════════════════════════════════════════════════════════

class TestGoModAndEnv:
    def test_go_mod_sqlite_driver_included(self):
        from aether_os.phases.p04_backend.go_generator import generate_go_mod
        src = generate_go_mod("github.com/test/app")
        assert "gorm.io/driver/sqlite" in src

    def test_go_db_sqlite_uses_sqlite_open(self):
        from aether_os.phases.p04_backend.go_generator import generate_go_db
        src = generate_go_db("sqlite")
        assert "sqlite.Open" in src
        assert "DATABASE_PATH" in src

    def test_go_db_postgres_uses_postgres_open(self):
        from aether_os.phases.p04_backend.go_generator import generate_go_db
        src = generate_go_db("postgres")
        assert "postgres.Open" in src
        assert "DATABASE_URL" in src

    def test_env_example_sqlite_has_database_path(self):
        from aether_os.phases.p04_backend.go_generator import generate_env_example
        src = generate_env_example("sqlite")
        assert "DATABASE_PATH" in src
        assert "DATABASE_URL" not in src

    def test_env_example_postgres_has_database_url(self):
        from aether_os.phases.p04_backend.go_generator import generate_env_example
        src = generate_env_example("postgres")
        assert "DATABASE_URL" in src

    def test_env_example_has_jwt_secret(self):
        from aether_os.phases.p04_backend.go_generator import generate_env_example
        src = generate_env_example()
        assert "JWT_SECRET" in src

    def test_env_example_has_port(self):
        from aether_os.phases.p04_backend.go_generator import generate_env_example
        src = generate_env_example()
        assert "PORT" in src


# ═══════════════════════════════════════════════════════════════════════════════
# main.go generation
# ═══════════════════════════════════════════════════════════════════════════════

class TestGoMainGeneration:
    def test_main_has_health_endpoint(self):
        from aether_os.phases.p04_backend.go_generator import generate_go_main
        src = generate_go_main(_ENTITIES, "myapp", _MODULE)
        assert '"/health"' in src

    def test_main_includes_project_name_in_health_response(self):
        from aether_os.phases.p04_backend.go_generator import generate_go_main
        src = generate_go_main(_ENTITIES, "myapp", _MODULE)
        assert '"myapp"' in src

    def test_main_registers_all_entity_routes(self):
        from aether_os.phases.p04_backend.go_generator import generate_go_main
        src = generate_go_main(_ENTITIES, "myapp", _MODULE)
        assert "handlers.RegisterUserRoutes" in src
        assert "handlers.RegisterOrderRoutes" in src

    def test_main_uses_env_for_port(self):
        from aether_os.phases.p04_backend.go_generator import generate_go_main
        src = generate_go_main(_ENTITIES, "myapp", _MODULE)
        assert 'os.Getenv("PORT")' in src

    def test_main_calls_db_init_with_model_refs(self):
        from aether_os.phases.p04_backend.go_generator import generate_go_main
        src = generate_go_main(_ENTITIES, "myapp", _MODULE)
        assert "db.Init(" in src

    def test_main_uses_gin_recovery_middleware(self):
        from aether_os.phases.p04_backend.go_generator import generate_go_main
        src = generate_go_main(_ENTITIES, "myapp", _MODULE)
        assert "gin.Recovery()" in src


# ═══════════════════════════════════════════════════════════════════════════════
# Dockerfile Generation
# ═══════════════════════════════════════════════════════════════════════════════

class TestGoDockerfile:
    def test_dockerfile_has_two_from_stages(self):
        from aether_os.phases.p04_backend.go_generator import generate_go_dockerfile
        src = generate_go_dockerfile("myapp")
        assert src.count("FROM") >= 2

    def test_dockerfile_uses_scratch_final_image(self):
        from aether_os.phases.p04_backend.go_generator import generate_go_dockerfile
        src = generate_go_dockerfile("myapp")
        assert "FROM scratch" in src

    def test_dockerfile_disables_cgo(self):
        from aether_os.phases.p04_backend.go_generator import generate_go_dockerfile
        src = generate_go_dockerfile("myapp")
        assert "CGO_ENABLED=0" in src

    def test_dockerfile_exposes_port(self):
        from aether_os.phases.p04_backend.go_generator import generate_go_dockerfile
        src = generate_go_dockerfile("myapp")
        assert "EXPOSE" in src

    def test_dockerfile_copies_ssl_certs(self):
        from aether_os.phases.p04_backend.go_generator import generate_go_dockerfile
        src = generate_go_dockerfile("myapp")
        assert "ca-certificates" in src


# ═══════════════════════════════════════════════════════════════════════════════
# Multiservice Generation
# ═══════════════════════════════════════════════════════════════════════════════

class TestGoMultiserviceGeneration:
    """Tests for generate_go_multiservice — verifies multiple service dirs."""

    def test_multiservice_generates_all_services(self, tmp_path):
        from aether_os.phases.p04_backend.go_generator import generate_go_multiservice
        service_map = {
            "services": [
                {"name": "user-svc", "port": 8001},
                {"name": "order-svc", "port": 8002},
            ]
        }
        paths = asyncio.run(
            generate_go_multiservice(service_map, _ENTITIES, "MyApp", tmp_path)
        )
        assert len(paths) == 2

    def test_multiservice_each_service_has_main_go(self, tmp_path):
        from aether_os.phases.p04_backend.go_generator import generate_go_multiservice
        service_map = {"services": [{"name": "auth-svc", "port": 9000}]}
        paths = asyncio.run(
            generate_go_multiservice(service_map, _ENTITIES, "MyApp", tmp_path)
        )
        for p in paths:
            assert (p / "main.go").exists(), f"main.go missing in {p}"

    def test_multiservice_entity_ownership_filters_entities(self, tmp_path):
        from aether_os.phases.p04_backend.go_generator import generate_go_multiservice
        service_map = {
            "services": [
                {"name": "user-svc", "port": 8001, "owns_entities": ["User"]},
            ]
        }
        paths = asyncio.run(
            generate_go_multiservice(service_map, _ENTITIES, "MyApp", tmp_path)
        )
        backend = paths[0]
        # Only User handler should exist; Order should not be present
        assert (backend / "handlers" / "UserHandler.go").exists()
        assert not (backend / "handlers" / "OrderHandler.go").exists()

    def test_multiservice_sqlite_service_uses_sqlite_driver(self, tmp_path):
        from aether_os.phases.p04_backend.go_generator import generate_go_multiservice
        service_map = {
            "services": [{"name": "local-svc", "port": 8100, "db": "sqlite"}]
        }
        paths = asyncio.run(
            generate_go_multiservice(service_map, _ENTITIES, "MyApp", tmp_path)
        )
        db_src = (paths[0] / "db" / "database.go").read_text()
        assert "sqlite.Open" in db_src

    def test_multiservice_returns_empty_for_no_services(self, tmp_path):
        from aether_os.phases.p04_backend.go_generator import generate_go_multiservice
        paths = asyncio.run(
            generate_go_multiservice({"services": []}, _ENTITIES, "MyApp", tmp_path)
        )
        assert paths == []


# ═══════════════════════════════════════════════════════════════════════════════
# Helper Functions
# ═══════════════════════════════════════════════════════════════════════════════

class TestGoHelpers:
    """Tests for _to_pascal and _to_camel helpers in go_generator."""

    def test_to_pascal_single_word(self):
        from aether_os.phases.p04_backend.go_generator import _to_pascal
        assert _to_pascal("product") == "Product"

    def test_to_pascal_snake_case(self):
        from aether_os.phases.p04_backend.go_generator import _to_pascal
        assert _to_pascal("user_profile") == "UserProfile"

    def test_to_pascal_kebab_case(self):
        from aether_os.phases.p04_backend.go_generator import _to_pascal
        assert _to_pascal("order-item") == "OrderItem"

    def test_to_pascal_mixed_case_input(self):
        from aether_os.phases.p04_backend.go_generator import _to_pascal
        assert _to_pascal("sales_order_line") == "SalesOrderLine"

    def test_to_camel_single_word(self):
        from aether_os.phases.p04_backend.go_generator import _to_camel
        assert _to_camel("product") == "product"

    def test_to_camel_snake_case(self):
        from aether_os.phases.p04_backend.go_generator import _to_camel
        assert _to_camel("user_profile") == "userProfile"

    def test_to_camel_kebab_case(self):
        from aether_os.phases.p04_backend.go_generator import _to_camel
        assert _to_camel("order-item") == "orderItem"
