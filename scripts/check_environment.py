"""Check installed tools without invoking a paid model or modifying project evidence."""

from __future__ import annotations

import asyncio
import importlib.metadata
import json
import sqlite3
import sys
import tempfile
import tomllib
from contextlib import closing
from pathlib import Path

import httpx
import jieba
from dotenv import dotenv_values
from fastapi import FastAPI
from pydantic import BaseModel, ConfigDict, ValidationError
from rank_bm25 import BM25Okapi

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class StrictProbe(BaseModel):
    """Make sure the configured Pydantic major supports strict data contracts."""

    model_config = ConfigDict(strict=True, extra="forbid")
    count: int


async def check_api(app: FastAPI) -> None:
    """Probe ASGI directly through the selected HTTPX client without opening a port."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://local-probe") as client:
        response = await client.get("/probe")
        if response.status_code != 200 or response.json() != {"status": "ok"}:
            raise RuntimeError("FastAPI/HTTPX integration probe failed.")


def main() -> int:
    """Run small real local probes; never print environment values or credentials."""
    if sys.version_info[:2] != (3, 12):
        raise RuntimeError("This project requires Python 3.12.")
    with (PROJECT_ROOT / "configs" / "default.toml").open("rb") as config_file:
        config = tomllib.load(config_file)
    if config["app"]["host"] != "127.0.0.1" or config["app"]["workers"] != 1:
        raise RuntimeError("Bootstrap configuration must be local and single-worker.")

    app = FastAPI()

    @app.get("/probe")
    def probe() -> dict[str, str]:
        return {"status": "ok"}

    asyncio.run(check_api(app))

    try:
        StrictProbe(count="1")
    except ValidationError:
        pass
    else:
        raise RuntimeError("Pydantic strict mode unexpectedly accepted a string integer.")
    if StrictProbe(count=1).count != 1:
        raise RuntimeError("Pydantic valid input failed.")

    # Use an actual temporary DB because an in-memory database cannot verify WAL mode.
    with tempfile.TemporaryDirectory(prefix="evidence-agent-check-") as temp_dir:
        database = Path(temp_dir) / "probe.sqlite3"
        # sqlite3's context manager manages transactions but does not close the connection.
        # Explicit closing releases Windows file handles before TemporaryDirectory cleans up.
        with closing(sqlite3.connect(database)) as connection:
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA synchronous=FULL")
            mode = connection.execute("PRAGMA journal_mode=WAL").fetchone()[0]
            if mode.lower() != "wal":
                raise RuntimeError("SQLite WAL is unavailable.")
            connection.execute("CREATE TABLE parent (id INTEGER PRIMARY KEY)")
            connection.execute("CREATE TABLE child (parent_id INTEGER REFERENCES parent(id))")
            try:
                connection.execute("INSERT INTO child VALUES (999)")
            except sqlite3.IntegrityError:
                pass
            else:
                raise RuntimeError("SQLite foreign keys are not enforced.")

    documents = [
        "熊猫以竹子为主要食物。",
        "鲸鱼生活在海洋中。",
        "火星是一颗行星。",
    ]
    # This synthetic corpus checks integration without reading private reference documents.
    tokenizer = jieba.Tokenizer()
    tokenizer.initialize()
    tokenized = [list(tokenizer.cut(document)) for document in documents]
    scores = BM25Okapi(tokenized).get_scores(list(tokenizer.cut("熊猫 竹子")))
    if max(range(len(documents)), key=lambda index: scores[index]) != 0:
        raise RuntimeError("Chinese tokenization/BM25 integration probe failed.")

    # MockTransport checks HTTPX without reaching a remote model or any other network endpoint.
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"ok": True}))
    with httpx.Client(transport=transport) as client:
        if client.get("https://environment-check.invalid").json() != {"ok": True}:
            raise RuntimeError("HTTPX transport probe failed.")

    env = dotenv_values(PROJECT_ROOT / ".env")
    allow_no_key = str(env.get("LLM_ALLOW_NO_API_KEY", "false")).lower() == "true"
    required_names = [
        "LLM_BASE_URL",
        "LLM_MODEL",
        "LLM_CONTEXT_TOKEN_LIMIT",
        "LLM_MAX_OUTPUT_TOKENS",
    ]
    if not allow_no_key:
        required_names.append("LLM_API_KEY")
    configured = all(bool(env.get(name)) for name in required_names)
    package_names = [
        "evidence-agent",
        "fastapi",
        "uvicorn",
        "pydantic",
        "httpx",
        "jieba",
        "rank-bm25",
        "python-dotenv",
        "pytest",
        "ruff",
    ]
    result = {
        "python": sys.version.split()[0],
        "sqlite": sqlite3.sqlite_version,
        "packages": {name: importlib.metadata.version(name) for name in package_names},
        "checks": {
            "configuration_parse": "passed",
            "fastapi_httpx": "passed",
            "pydantic_strict": "passed",
            "sqlite_wal_foreign_keys": "passed",
            "jieba_bm25": "passed",
            "httpx_local_transport": "passed",
        },
        "model_required_fields_present": configured,
        "model_connection_tested": False,
        "business_pipeline_implemented": False,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
