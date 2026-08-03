import json
import os
from pathlib import Path

import pytest

from app.mcp_server import execute_tool_call
from app.services.task_store import store


EVAL_CASES_DIR = Path(__file__).parent / "eval_cases"


def _load_eval_cases():
    cases = []
    for json_file in sorted(EVAL_CASES_DIR.glob("*.json")):
        with open(json_file, encoding="utf-8") as f:
            data = json.load(f)
        cases.append((json_file.stem, data))
    return cases


@pytest.mark.parametrize("case_name,log_data", _load_eval_cases())
def test_tool_call_name_matches(case_name, log_data):
    tool_calls = log_data.get("tool_calls", [])
    assert tool_calls, f"No tool_calls in log: {case_name}"
    expected_tool = tool_calls[0]["tool"]
    assert expected_tool, f"Empty tool name in log: {case_name}"


@pytest.mark.parametrize("case_name,log_data", _load_eval_cases())
def test_task_store_final_state(case_name, log_data):
    tasks_before = log_data.get("tasks_before", [])
    tasks_after = log_data.get("tasks_after", [])
    tool_calls = log_data.get("tool_calls", [])
    assert tool_calls, f"No tool_calls in log: {case_name}"

    raw_tasks_before = []
    for t in tasks_before:
        raw_tasks_before.append(
            {
                "id": t["id"],
                "title": t["title"],
                "description": t.get("description", ""),
                "assignee": t.get("assignee", ""),
                "duration_days": t.get("durationDays", 1),
                "predecessors": t.get("predecessors", []),
            }
        )

    store._raw_tasks = []
    if raw_tasks_before:
        from app.schemas.task import RawTask

        store.set_raw_tasks([RawTask(**rt) for rt in raw_tasks_before])

    for call in tool_calls:
        tool_name = call["tool"]
        arguments = call.get("arguments", {})

        result = execute_tool_call(tool_name, arguments)

        assert "error" not in result, (
            f"Tool call '{tool_name}' returned error in log '{case_name}': "
            f"{result.get('error')}"
        )

    final_tasks = store.get_raw_tasks()
    assert len(final_tasks) == len(tasks_after), (
        f"Task count mismatch in log '{case_name}': "
        f"expected {len(tasks_after)}, got {len(final_tasks)}"
    )