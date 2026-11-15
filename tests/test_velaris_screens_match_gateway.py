"""The dashboard screens (dashboard/src/components/velaris/screens.js) only call what the gateway serves, and a
member-level screen never needs an admin-only row. Keeps the two tables from drifting (KAN-137..151)."""
import re
from pathlib import Path

from aether_os.gateway.routers import velaris_chat_router, velaris_mail_router
from aether_os.gateway.velaris_hr_table import HR_ALLOW, HR_ROUTES

SRC = (Path(__file__).resolve().parents[1] / "dashboard/src/components/velaris/screens.js").read_text()
ADMIN = {tuple(r.path.strip("/").split("/")) for r in HR_ROUTES if r.admin}
CONFIRM = {tuple(r.path.strip("/").split("/")): r.confirm for r in HR_ROUTES if r.confirm}


def _screens():
    out = []
    for block in re.split(r"\n  \{ id: '", SRC)[1:]:
        sid = block.split("'")[0]
        role = re.search(r"role: '(\w+)'", block).group(1)
        out.append((sid, role, block))
    return out


def test_every_hr_call_is_a_gateway_row_and_roles_agree():
    n = 0
    for sid, role, block in _screens():
        for agent, method in re.findall(r"H\('(\w+)', '(\w+)'\)", block):
            assert method in HR_ALLOW.get(agent, ()), (sid, agent, method)
            if role == "member":
                assert (agent, method) not in ADMIN, f"{sid}: member screen calls admin-only {agent}.{method}"
            n += 1
    assert n > 70


def test_generic_agent_calls_are_for_agents_the_hr_proxy_does_not_serve():
    for sid, _, block in _screens():
        for agent, _m in re.findall(r"A\('(\w+)', '(\w+)'\)", block):
            assert agent not in HR_ALLOW, (sid, agent)


def test_destructive_rows_have_the_same_typed_word_in_the_screen():
    for sid, _, block in _screens():
        for m in re.finditer(r"H\('(\w+)', '(\w+)'\)[^\n]*", block):
            key = (m.group(1), m.group(2))
            if key in CONFIRM:
                assert f"typed: '{CONFIRM[key]}'" in m.group(0), (sid, key)
    # the exact export/erase rows are all on a screen
    assert {k for k in CONFIRM if f"H('{k[0]}', '{k[1]}')" in SRC} == set(CONFIRM)


def test_path_calls_match_a_gateway_row():
    rows = {(r.method, "/chat" + re.sub(r"\{\w+\}", "{}", r.path)) for r in velaris_chat_router.ROUTES}
    rows |= {(r.method, "/mail" + re.sub(r"\{\w+\}", "{}", r.path)) for r in velaris_mail_router.ROUTES}
    found = re.findall(r"(?:P\('(\w+)', '|method: '(\w+)', path: ')(/(?:chat|mail)/[^']+)'", SRC)
    assert len(found) >= 14
    for a, b, path in found:
        assert ((a or b).upper(), re.sub(r"\{\w+\}", "{}", path)) in rows, path
