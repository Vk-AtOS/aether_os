"""Run da281716 (team task tracker): the domain IR listed id (a uuid string), created_at and updated_at as ordinary
fields, and generate_ir_types_ts emitted its own id: number / created_at / updated_at around them. Every interface
declared them twice with conflicting types, so `tsc --noEmit` failed with TS2300/TS2717 in src/types/index.ts.
"""
from __future__ import annotations

import re

from aether_os.core.domain_ir import DomainIR, IREntity, IRField
from aether_os.phases.p05_frontend.ir_generators import generate_ir_types_ts

F = IRField


def _run_da281716_ir() -> DomainIR:
    base = [F("id", "string", nullable=False, default="gen_random_uuid()"),
            F("created_at", "datetime", nullable=False), F("updated_at", "datetime", nullable=False)]
    ir = DomainIR(domain="general", app_name="tracker")
    ir.entities = [
        IREntity("Member", "members", [base[0], F("email", "email", nullable=False),
                                       F("password_hash", "string", nullable=False), F("name", "string", nullable=False),
                                       F("team_id", "fk", nullable=False, ref_entity="Team"), *base[1:]]),
        IREntity("Task", "tasks", [base[0], F("title", "string", nullable=False),
                                   F("status", "enum", nullable=False, enum_values=["todo", "doing", "done"]),
                                   F("assignee_id", "fk", ref_entity="Member"), *base[1:]]),
    ]
    return ir


def _block(ts: str, head: str) -> str:
    m = re.search(re.escape(head) + r"(.*?)\n\}", ts, re.S)
    assert m, f"{head} not in types/index.ts"
    return m.group(1)


def test_every_interface_declares_each_member_once_with_a_numeric_id():
    ts = generate_ir_types_ts(_run_da281716_ir())
    for name in ("Member", "Task"):
        members = re.findall(r"^\s+(\w+)\??:", _block(ts, f"export interface {name} {{"), re.M)
        assert len(members) == len(set(members)), f"{name} repeats {sorted(m for m in members if members.count(m) > 1)}"
        # p04a always generates an Integer primary key (the IR's uuid id is ignored), so the client type is number.
        assert re.search(r"^\s+id: number;", _block(ts, f"export interface {name} {{"), re.M)


def test_create_schema_holds_only_client_fields():
    ts = generate_ir_types_ts(_run_da281716_ir())
    member = re.findall(r"^\s+(\w+):", _block(ts, "export const MemberSchema = z.object({"), re.M)
    assert member == ["email", "name", "team_id"]       # no id/timestamps (server-set), no password_hash (credential)
    task = _block(ts, "export const TaskSchema = z.object({")
    assert not re.search(r"^\s+(id|created_at|updated_at):", task, re.M)
    assert "status: z.enum(['todo', 'doing', 'done'])" in task


def test_enum_fields_get_a_named_union_type():
    # The model-written pages import TaskStatus; p05 used to append `export type TaskStatus = any` for them.
    assert "export type TaskStatus = 'todo' | 'doing' | 'done';" in generate_ir_types_ts(_run_da281716_ir())
