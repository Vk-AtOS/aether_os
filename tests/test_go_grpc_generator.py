"""
AetherOS — Go gRPC Generator Unit Tests

Covers:
  phases/p04_backend/go_grpc_generator.py — proto generation, gRPC server
                                             code generation, file writing
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
# Proto Generation
# ═══════════════════════════════════════════════════════════════════════════════

class TestGoGrpcProtoGeneration:
    """Tests for go_grpc_generator.generate_proto."""

    def test_proto_has_proto3_syntax(self):
        from aether_os.phases.p04_backend.go_grpc_generator import generate_proto
        src = generate_proto("order-svc", [_ENTITY_USER])
        assert 'syntax = "proto3"' in src

    def test_proto_has_entity_message(self):
        from aether_os.phases.p04_backend.go_grpc_generator import generate_proto
        src = generate_proto("order-svc", [_ENTITY_USER])
        assert "message User {" in src

    def test_proto_has_list_request_and_response_messages(self):
        from aether_os.phases.p04_backend.go_grpc_generator import generate_proto
        src = generate_proto("svc", [_ENTITY_USER])
        assert "message ListUserRequest" in src
        assert "message ListUserResponse" in src

    def test_proto_has_get_request_message(self):
        from aether_os.phases.p04_backend.go_grpc_generator import generate_proto
        src = generate_proto("svc", [_ENTITY_USER])
        assert "message GetUserRequest" in src

    def test_proto_has_delete_request_and_response_messages(self):
        from aether_os.phases.p04_backend.go_grpc_generator import generate_proto
        src = generate_proto("svc", [_ENTITY_USER])
        assert "message DeleteUserRequest" in src
        assert "message DeleteUserResponse" in src

    def test_proto_has_service_definition(self):
        from aether_os.phases.p04_backend.go_grpc_generator import generate_proto
        src = generate_proto("my-svc", [_ENTITY_USER])
        assert "service MySvcService {" in src

    def test_proto_has_rpc_methods(self):
        from aether_os.phases.p04_backend.go_grpc_generator import generate_proto
        src = generate_proto("svc", [_ENTITY_USER])
        assert "rpc ListUser" in src
        assert "rpc GetUser" in src
        assert "rpc CreateUser" in src
        assert "rpc UpdateUser" in src
        assert "rpc DeleteUser" in src

    def test_proto_id_field_is_int64(self):
        from aether_os.phases.p04_backend.go_grpc_generator import generate_proto
        src = generate_proto("svc", [_ENTITY_USER])
        assert "int64 id = 1" in src

    def test_proto_string_field_maps_to_string(self):
        from aether_os.phases.p04_backend.go_grpc_generator import generate_proto
        src = generate_proto("svc", [_ENTITY_USER])
        assert "string username" in src or "string email" in src

    def test_proto_float_field_maps_to_double(self):
        from aether_os.phases.p04_backend.go_grpc_generator import generate_proto
        entity = {"table": "product", "fields": [{"name": "price", "type": "float"}]}
        src = generate_proto("svc", [entity])
        assert "double price" in src

    def test_proto_bool_field_maps_to_bool(self):
        from aether_os.phases.p04_backend.go_grpc_generator import generate_proto
        entity = {"table": "item", "fields": [{"name": "active", "type": "bool"}]}
        src = generate_proto("svc", [entity])
        assert "bool active" in src

    def test_proto_has_created_at_and_updated_at(self):
        from aether_os.phases.p04_backend.go_grpc_generator import generate_proto
        src = generate_proto("svc", [_ENTITY_USER])
        assert "created_at" in src
        assert "updated_at" in src

    def test_proto_package_strips_dashes(self):
        from aether_os.phases.p04_backend.go_grpc_generator import generate_proto
        src = generate_proto("order-svc", [_ENTITY_USER])
        assert "package ordersvc;" in src

    def test_proto_go_package_option_set(self):
        from aether_os.phases.p04_backend.go_grpc_generator import generate_proto
        src = generate_proto("svc", [_ENTITY_USER])
        assert "option go_package" in src

    def test_proto_multiple_entities(self):
        from aether_os.phases.p04_backend.go_grpc_generator import generate_proto
        src = generate_proto("svc", _ENTITIES)
        assert "message User {" in src
        assert "message Order {" in src
        assert "rpc ListUser" in src
        assert "rpc ListOrder" in src

    def test_proto_repeated_items_in_list_response(self):
        from aether_os.phases.p04_backend.go_grpc_generator import generate_proto
        src = generate_proto("svc", [_ENTITY_USER])
        # ListUserResponse must have a repeated field
        assert "repeated User items" in src

    def test_proto_fk_type_maps_to_int64(self):
        from aether_os.phases.p04_backend.go_grpc_generator import generate_proto
        entity = {"table": "post", "fields": [{"name": "author_id", "type": "fk"}]}
        src = generate_proto("svc", [entity])
        assert "int64 author_id" in src

    def test_proto_integer_type_maps_to_int64(self):
        from aether_os.phases.p04_backend.go_grpc_generator import generate_proto
        entity = {"table": "score", "fields": [{"name": "value", "type": "integer"}]}
        src = generate_proto("svc", [entity])
        assert "int64 value" in src


# ═══════════════════════════════════════════════════════════════════════════════
# gRPC Server Generation
# ═══════════════════════════════════════════════════════════════════════════════

class TestGoGrpcServerGeneration:
    """Tests for go_grpc_generator.generate_grpc_server."""

    def test_server_package_is_grpc(self):
        from aether_os.phases.p04_backend.go_grpc_generator import generate_grpc_server
        src = generate_grpc_server("my-svc", [_ENTITY_USER], _MODULE)
        assert "package grpc" in src

    def test_server_struct_name_pascal_cased(self):
        from aether_os.phases.p04_backend.go_grpc_generator import generate_grpc_server
        src = generate_grpc_server("my-svc", [_ENTITY_USER], _MODULE)
        assert "type MySvcServer struct" in src

    def test_server_has_new_server_constructor(self):
        from aether_os.phases.p04_backend.go_grpc_generator import generate_grpc_server
        src = generate_grpc_server("my-svc", [_ENTITY_USER], _MODULE)
        assert "func NewMySvcServer(" in src

    def test_server_has_list_method(self):
        from aether_os.phases.p04_backend.go_grpc_generator import generate_grpc_server
        src = generate_grpc_server("svc", [_ENTITY_USER], _MODULE)
        assert "func (s *SvcServer) ListUser" in src

    def test_server_has_get_method(self):
        from aether_os.phases.p04_backend.go_grpc_generator import generate_grpc_server
        src = generate_grpc_server("svc", [_ENTITY_USER], _MODULE)
        assert "func (s *SvcServer) GetUser" in src

    def test_server_has_create_method(self):
        from aether_os.phases.p04_backend.go_grpc_generator import generate_grpc_server
        src = generate_grpc_server("svc", [_ENTITY_USER], _MODULE)
        assert "func (s *SvcServer) CreateUser" in src

    def test_server_has_update_method(self):
        from aether_os.phases.p04_backend.go_grpc_generator import generate_grpc_server
        src = generate_grpc_server("svc", [_ENTITY_USER], _MODULE)
        assert "func (s *SvcServer) UpdateUser" in src

    def test_server_has_delete_method(self):
        from aether_os.phases.p04_backend.go_grpc_generator import generate_grpc_server
        src = generate_grpc_server("svc", [_ENTITY_USER], _MODULE)
        assert "func (s *SvcServer) DeleteUser" in src

    def test_server_has_start_grpc_func(self):
        from aether_os.phases.p04_backend.go_grpc_generator import generate_grpc_server
        src = generate_grpc_server("svc", [_ENTITY_USER], _MODULE)
        assert "func StartGRPC(" in src

    def test_server_uses_grpc_status_errors(self):
        from aether_os.phases.p04_backend.go_grpc_generator import generate_grpc_server
        src = generate_grpc_server("svc", [_ENTITY_USER], _MODULE)
        assert "status.Errorf" in src

    def test_server_embeds_unimplemented_server(self):
        from aether_os.phases.p04_backend.go_grpc_generator import generate_grpc_server
        src = generate_grpc_server("svc", [_ENTITY_USER], _MODULE)
        assert "Unimplemented" in src

    def test_server_delete_returns_success_bool(self):
        from aether_os.phases.p04_backend.go_grpc_generator import generate_grpc_server
        src = generate_grpc_server("svc", [_ENTITY_USER], _MODULE)
        assert "Success: true" in src or "Success: false" in src

    def test_server_db_field_type_is_gorm_db(self):
        from aether_os.phases.p04_backend.go_grpc_generator import generate_grpc_server
        src = generate_grpc_server("svc", [_ENTITY_USER], _MODULE)
        assert "*gorm.DB" in src

    def test_server_imports_context(self):
        from aether_os.phases.p04_backend.go_grpc_generator import generate_grpc_server
        src = generate_grpc_server("svc", [_ENTITY_USER], _MODULE)
        assert '"context"' in src

    def test_server_imports_grpc_codes(self):
        from aether_os.phases.p04_backend.go_grpc_generator import generate_grpc_server
        src = generate_grpc_server("svc", [_ENTITY_USER], _MODULE)
        assert "codes" in src

    def test_server_multiple_entities_have_all_methods(self):
        from aether_os.phases.p04_backend.go_grpc_generator import generate_grpc_server
        src = generate_grpc_server("svc", _ENTITIES, _MODULE)
        assert "func (s *SvcServer) ListUser" in src
        assert "func (s *SvcServer) ListOrder" in src
        assert "func (s *SvcServer) CreateOrder" in src


# ═══════════════════════════════════════════════════════════════════════════════
# gRPC File Writing (async)
# ═══════════════════════════════════════════════════════════════════════════════

class TestGoGrpcFileGeneration:
    """Tests for go_grpc_generator.generate_grpc_files — verifies file system output."""

    def test_generate_grpc_files_writes_proto_file(self, tmp_path):
        from aether_os.phases.p04_backend.go_grpc_generator import generate_grpc_files
        asyncio.run(generate_grpc_files("my-svc", [_ENTITY_USER], tmp_path, _MODULE))
        proto_file = tmp_path / "proto" / "mysvc.proto"
        assert proto_file.exists(), "Expected mysvc.proto to be written"

    def test_generate_grpc_files_writes_server_go(self, tmp_path):
        from aether_os.phases.p04_backend.go_grpc_generator import generate_grpc_files
        asyncio.run(generate_grpc_files("svc", [_ENTITY_USER], tmp_path, _MODULE))
        server_file = tmp_path / "grpc" / "server.go"
        assert server_file.exists(), "Expected grpc/server.go to be written"

    def test_generate_grpc_files_proto_content_valid(self, tmp_path):
        from aether_os.phases.p04_backend.go_grpc_generator import generate_grpc_files
        asyncio.run(generate_grpc_files("svc", [_ENTITY_USER], tmp_path, _MODULE))
        proto_src = (tmp_path / "proto" / "svc.proto").read_text()
        assert 'syntax = "proto3"' in proto_src

    def test_generate_grpc_files_server_content_has_package(self, tmp_path):
        from aether_os.phases.p04_backend.go_grpc_generator import generate_grpc_files
        asyncio.run(generate_grpc_files("svc", [_ENTITY_USER], tmp_path, _MODULE))
        server_src = (tmp_path / "grpc" / "server.go").read_text()
        assert "package grpc" in server_src

    def test_generate_grpc_files_creates_proto_dir(self, tmp_path):
        from aether_os.phases.p04_backend.go_grpc_generator import generate_grpc_files
        asyncio.run(generate_grpc_files("svc", [_ENTITY_ORDER], tmp_path, _MODULE))
        assert (tmp_path / "proto").is_dir()

    def test_generate_grpc_files_creates_grpc_dir(self, tmp_path):
        from aether_os.phases.p04_backend.go_grpc_generator import generate_grpc_files
        asyncio.run(generate_grpc_files("svc", [_ENTITY_ORDER], tmp_path, _MODULE))
        assert (tmp_path / "grpc").is_dir()

    def test_generate_grpc_files_server_has_start_grpc(self, tmp_path):
        from aether_os.phases.p04_backend.go_grpc_generator import generate_grpc_files
        asyncio.run(generate_grpc_files("svc", [_ENTITY_USER], tmp_path, _MODULE))
        server_src = (tmp_path / "grpc" / "server.go").read_text()
        assert "func StartGRPC(" in server_src


# ═══════════════════════════════════════════════════════════════════════════════
# gRPC Type Mapper Helper
# ═══════════════════════════════════════════════════════════════════════════════

class TestGrpcTypeMapper:
    """Tests for _go_type_to_proto — verifies Go→proto type mapping."""

    def test_string_maps_to_string(self):
        from aether_os.phases.p04_backend.go_grpc_generator import _go_type_to_proto
        assert _go_type_to_proto("string") == "string"

    def test_text_maps_to_string(self):
        from aether_os.phases.p04_backend.go_grpc_generator import _go_type_to_proto
        assert _go_type_to_proto("text") == "string"

    def test_int_maps_to_int64(self):
        from aether_os.phases.p04_backend.go_grpc_generator import _go_type_to_proto
        assert _go_type_to_proto("int") == "int64"

    def test_integer_maps_to_int64(self):
        from aether_os.phases.p04_backend.go_grpc_generator import _go_type_to_proto
        assert _go_type_to_proto("integer") == "int64"

    def test_float_maps_to_double(self):
        from aether_os.phases.p04_backend.go_grpc_generator import _go_type_to_proto
        assert _go_type_to_proto("float") == "double"

    def test_float64_maps_to_double(self):
        from aether_os.phases.p04_backend.go_grpc_generator import _go_type_to_proto
        assert _go_type_to_proto("float64") == "double"

    def test_bool_maps_to_bool(self):
        from aether_os.phases.p04_backend.go_grpc_generator import _go_type_to_proto
        assert _go_type_to_proto("bool") == "bool"

    def test_boolean_maps_to_bool(self):
        from aether_os.phases.p04_backend.go_grpc_generator import _go_type_to_proto
        assert _go_type_to_proto("boolean") == "bool"

    def test_datetime_maps_to_string(self):
        from aether_os.phases.p04_backend.go_grpc_generator import _go_type_to_proto
        assert _go_type_to_proto("datetime") == "string"

    def test_date_maps_to_string(self):
        from aether_os.phases.p04_backend.go_grpc_generator import _go_type_to_proto
        assert _go_type_to_proto("date") == "string"

    def test_fk_maps_to_int64(self):
        from aether_os.phases.p04_backend.go_grpc_generator import _go_type_to_proto
        assert _go_type_to_proto("fk") == "int64"

    def test_uint_maps_to_int64(self):
        from aether_os.phases.p04_backend.go_grpc_generator import _go_type_to_proto
        assert _go_type_to_proto("uint") == "int64"

    def test_unknown_type_defaults_to_string(self):
        from aether_os.phases.p04_backend.go_grpc_generator import _go_type_to_proto
        assert _go_type_to_proto("blob") == "string"
        assert _go_type_to_proto("json") == "string"

    def test_case_insensitive_lookup(self):
        from aether_os.phases.p04_backend.go_grpc_generator import _go_type_to_proto
        # The function uses .lower() so uppercase input should still work
        assert _go_type_to_proto("STRING") == "string"
        assert _go_type_to_proto("INT") == "int64"
