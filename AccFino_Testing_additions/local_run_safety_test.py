"""Problems seen when running AccFino locally on Windows (server log, Oct 2026):
  1. GET /modules.json -> 500  'charmap' codec can't decode byte 0x8f      (text files read with the Windows default encoding; modules.json contains emoji)
  2. QueuePool limit of size 2 overflow 3 reached, connection timed out    (the auth middleware did its database lookups ON the event loop)
Run from backend/:  PYTHONPATH=. python -m pytest ../AccFino_Testing_additions/local_run_safety_test.py -q"""
import ast, asyncio, os, pathlib, sys
import pytest

BACKEND = pathlib.Path(__file__).resolve().parent.parent / "backend"


def test_every_text_file_read_or_write_names_its_encoding():
    """Path.read_text()/write_text() with no encoding use cp1252 on Windows and fail on any non-ASCII character (emoji in modules.json). Always say utf-8."""
    scan = [BACKEND / "main_app" / "react_api.py", *(BACKEND / "accfino_core").rglob("*.py"), *(BACKEND / "db_app").rglob("*.py")]
    bad = []
    for f in scan:
        if "__pycache__" in str(f):
            continue
        for n in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in ("read_text", "write_text"):
                positional = len(n.args) >= (1 if n.func.attr == "read_text" else 2)                    # read_text("utf-8") / write_text(data, "utf-8") are fine too
                if not positional and not any(k.arg == "encoding" for k in n.keywords):
                    bad.append(f"{f.relative_to(BACKEND)}:{n.lineno} {n.func.attr}")
    assert bad == []


def test_modules_json_really_contains_non_ascii_so_the_encoding_matters():
    raw = (BACKEND.parent / "frontend" / "src" / "config" / "modules.json").read_bytes()
    assert any(b > 127 for b in raw)
    with pytest.raises(UnicodeDecodeError):
        raw.decode("cp1252")                         # what Windows did before
    assert raw.decode("utf-8")                       # what the server does now


def test_auth_lookup_runs_off_the_event_loop():
    """The authentication check hits the database. On the event loop it blocks the server whenever the pool is busy, and the busy connections can only be
    released by that same loop - a deadlock that lasts until the pool timeout. It must run in a worker thread."""
    os.environ.setdefault("DATABASE_URL", "postgresql+psycopg2://x:x@localhost/x"); os.environ.setdefault("JWT_SECRET", "x" * 64)
    sys.path.insert(0, str(BACKEND))
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from accfino_core.security import middleware as MW
    seen = []

    def stub(headers):
        try:
            asyncio.get_running_loop(); seen.append("event-loop")
        except RuntimeError:
            seen.append("worker-thread")
        return None, "missing_token"

    app = FastAPI()

    @app.get("/health")
    def health(): return {"ok": True}
    MW.AuthGuard._authenticate = staticmethod(stub)
    guarded = MW.AuthGuard(app, fastapi_app=app)
    client = TestClient(guarded)
    assert client.get("/health").status_code == 200
    assert seen == ["worker-thread"]


def test_pool_settings_are_tunable_and_a_little_larger():
    src = (BACKEND / "db_app" / "database.py").read_text(encoding="utf-8")
    assert "DB_POOL_SIZE" in src and "DB_MAX_OVERFLOW" in src and "DB_POOL_TIMEOUT" in src and "pool_size=2" not in src
