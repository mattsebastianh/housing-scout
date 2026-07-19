import json
from pathlib import Path

import structlog

from scout.core.logging_setup import setup_logging


def test_setup_logging_writes_json_lines(tmp_path):
    """setup_logging writes structlog events as JSON lines to the given file."""
    log_path = tmp_path / "run.log"
    setup_logging(log_path)
    log = structlog.get_logger("test")
    log.info("hello", foo=1)
    content = log_path.read_text(encoding="utf-8").strip()
    record = json.loads(content.splitlines()[-1])
    assert record["event"] == "hello"
    assert record["foo"] == 1
    assert "timestamp" in record
