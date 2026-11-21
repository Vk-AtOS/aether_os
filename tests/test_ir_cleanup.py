"""Model-written IR items without a name are dropped at extraction, not allowed to sink the whole spec in p04b."""
from aether_os.phases.p02b_domain_ir.ir_cleanup import drop_unnamed
from aether_os.phases.p04b_business_logic.safe_names import check_logic_names


def test_blank_names_are_dropped_and_the_rest_kept():
    notifs = [{"event": "task_overdue"}, {"event": ""}, {"event": "  "}, {"channel": "email"}, {"event": "task_done"}]
    assert drop_unnamed(notifs, "event", "notification") == [{"event": "task_overdue"}, {"event": "task_done"}]
    assert drop_unnamed(None, "event", "notification") == []


def test_spec_with_a_blank_event_now_passes_p04b_but_a_dangerous_name_is_still_refused():
    # Regression (AWS testbed, 21 Nov 2026, Nemotron): one notification with event '' made p04b refuse the IR.
    ir = {"notifications": drop_unnamed([{"event": "task_overdue"}, {"event": ""}], "event", "notification")}
    assert check_logic_names(ir) == []
    bad = {"notifications": drop_unnamed([{"event": "../../etc/x"}], "event", "notification")}
    assert check_logic_names(bad) and "unsafe_name" in check_logic_names(bad)[0]
