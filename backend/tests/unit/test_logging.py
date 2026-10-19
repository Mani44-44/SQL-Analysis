from __future__ import annotations

import json
import logging

from app.core.logging import JsonFormatter, request_id_var


def test_json_formatter_includes_request_id_and_extras() -> None:
    token = request_id_var.set("abc123")
    try:
        record = logging.LogRecord("t", logging.INFO, __file__, 1, "hello %s", ("x",), None)
        record.workspace_id = "w1"
        out = json.loads(JsonFormatter().format(record))
    finally:
        request_id_var.reset(token)
    assert out["msg"] == "hello x"
    assert out["request_id"] == "abc123"
    assert out["workspace_id"] == "w1"
    assert out["level"] == "INFO"
