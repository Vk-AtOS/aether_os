"""Notification events written as sentences get identifier names instead of failing the IR (KAN-218)."""
from aether_os.phases.p04b_business_logic.safe_names import check_logic_names, normalise_event_names


def _ir(*events):
    return {"notifications": [{"event": e, "template": "t"} for e in events]}


def test_run_16_events_become_identifiers_and_pass_the_check():
    ir = _ir("Task.assignee_id changed from null to user", "Daily cron: Task.due_date < CURRENT_DATE",
             "Task.status changed to Done", "task_created")
    renamed = normalise_event_names(ir)
    names = [n["event"] for n in ir["notifications"]]
    assert names == ["task_assignee_id_changed_from_null_to_user", "daily_cron_task_due_date_current_date",
                     "task_status_changed_to_done", "task_created"]
    assert len(renamed) == 3 and ir["notifications"][0]["trigger"] == "Task.assignee_id changed from null to user"
    assert check_logic_names(ir) == []


def test_duplicates_get_suffixes_and_digits_get_a_prefix():
    ir = _ir("Task done!", "task done", "3 days overdue")
    normalise_event_names(ir)
    assert [n["event"] for n in ir["notifications"]] == ["task_done", "task_done_2", "event_3_days_overdue"]


def test_path_or_code_syntax_is_not_renamed_and_stays_refused():
    for hostile in ("../../etc/passwd", "a'); import os; ('", "x\\y", "`id`"):
        ir = _ir(hostile)
        assert normalise_event_names(ir) == []
        assert ir["notifications"][0]["event"] == hostile and check_logic_names(ir)


def test_nothing_left_is_still_refused():
    ir = _ir("!!!")
    normalise_event_names(ir)
    assert check_logic_names(ir)            # empty slug stays refused
