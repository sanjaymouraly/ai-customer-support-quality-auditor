"""Keep integration-test persistence isolated from the user's local audit history."""

import os
import tempfile
from pathlib import Path

_test_db = Path(tempfile.gettempdir()) / f"support-auditor-tests-{os.getpid()}.db"
os.environ["DATABASE_URL"] = f"sqlite:///{_test_db}"
# Tests must never make paid provider calls or inherit a user's local auth setting.
for _key in (
    "API_ACCESS_TOKEN",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "OPENROUTER_API_KEY",
    "CUSTOM_API_KEY",
    "OLLAMA_API_KEY",
):
    os.environ[_key] = ""
