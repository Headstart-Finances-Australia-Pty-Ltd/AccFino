"""Admin Console > Open Banking: Basiq platform set-up (stored encrypted, env wins, admin-only, never echoed) and that the Basiq modules read it live.
Run from backend/:  PYTHONPATH=. python -m pytest ../AccFino_Testing_additions/openbanking_setup_test.py -q"""
import os, sys
import pytest
sys.path.insert(0, os.path.dirname(__file__))
from csv_import_harness import make_db, make_org
from accfino_core import models as m, openbanking_setup as OB


class Resp:
    def __init__(self, code): self.status_code = code


@pytest.fixture()
def env(monkeypatch):
    db = make_db(); org, ctx = make_org(db)
    for k in ("BASIQ_API_KEY", "BASIQ_BASE_URL", "BASIQ_VERSION"):
        monkeypatch.delenv(k, raising=False)
    OB.forget_cache()
    yield db, org, ctx
    OB.forget_cache(); db.close()


def test_saved_key_is_encrypted_used_with_defaults_and_never_echoed(env):
    db, org, ctx = env
    assert OB.basiq_status(db) == {"configured": False, "source": None, "base_url": OB.DEFAULT_BASE, "version": OB.DEFAULT_VERSION, "locked_by_environment": False}
    OB.save_basiq(db, api_key="  KEY-123  "); db.commit()
    raw = db.get(m.SystemSetting, "basiq.api_key").value
    assert "KEY-123" not in raw and OB.unseal(raw) == "KEY-123"                                  # sealed at rest
    c = OB.basiq_config(db)
    assert c["api_key"] == "KEY-123" and c["source"] == "admin" and c["base_url"] == OB.DEFAULT_BASE and c["version"] == "3.0"   # defaults: admin only needs the key
    assert "KEY-123" not in str(OB.basiq_status(db))                                              # status carries no secret
    OB.save_basiq(db, api_key="", base_url="https://au-api.basiq.io/", version="3.0"); db.commit()
    assert OB.basiq_config(db)["api_key"] == "KEY-123"                                            # a blank key keeps the saved one
    OB.save_basiq(db, clear=True); db.commit()
    assert OB.basiq_status(db)["configured"] is False
    with pytest.raises(ValueError): OB.save_basiq(db, base_url="http://insecure.example")        # https only


def test_server_environment_wins_over_the_admin_screen(env, monkeypatch):
    db, org, ctx = env
    OB.save_basiq(db, api_key="ADMIN-KEY"); db.commit()
    monkeypatch.setenv("BASIQ_API_KEY", "ENV-KEY"); monkeypatch.setenv("BASIQ_BASE_URL", "https://env.example/")
    c = OB.basiq_config(db)
    assert (c["api_key"], c["source"], c["base_url"]) == ("ENV-KEY", "environment", "https://env.example")
    assert OB.basiq_status(db)["locked_by_environment"] is True


def test_test_button_reports_plainly_and_never_leaks_the_key(env, monkeypatch):
    db, org, ctx = env
    assert OB.test_basiq(db)["ok"] is False and "No Basiq API key" in OB.test_basiq(db)["message"]
    OB.save_basiq(db, api_key="SECRET-KEY"); db.commit()
    seen = {}
    def fake(url, headers):
        seen.update(url=url, auth=headers["Authorization"], ver=headers["basiq-version"]); return Resp(200)
    monkeypatch.setattr(OB, "_http_post", fake)
    assert OB.test_basiq(db) == {"ok": True, "message": "Connected to Basiq."}
    assert seen == {"url": OB.DEFAULT_BASE + "/token", "auth": "Basic SECRET-KEY", "ver": "3.0"}
    monkeypatch.setattr(OB, "_http_post", lambda u, h: Resp(401))
    bad = OB.test_basiq(db); assert bad["ok"] is False and "rejected the API key" in bad["message"] and "SECRET-KEY" not in bad["message"]
    def boom(u, h): raise RuntimeError("connection to https://x failed with token SECRET-KEY")
    monkeypatch.setattr(OB, "_http_post", boom)
    assert "SECRET-KEY" not in OB.test_basiq(db)["message"]


def test_basiq_modules_read_the_admin_settings_live(env, monkeypatch):
    db, org, ctx = env
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend", "main_app"))
    try:
        from backend.open_banking import auth as BA
    except Exception as e:
        pytest.skip(f"Basiq module not importable in this environment: {e}")
    monkeypatch.setattr(OB, "_load", lambda d=None: OB._rows(db))
    with pytest.raises(ValueError) as e: BA._require_basiq_config()
    assert "Admin Console" in str(e.value)                                                        # clear message instead of 'missing env variables'
    OB.save_basiq(db, api_key="K1"); db.commit()
    assert BA._require_basiq_config() == OB.DEFAULT_BASE + "/token"
    BA.ACCESS_TOKEN, BA.TOKEN_EXPIRY, BA._TOKEN_KEY = "OLD", 9e12, "K1"
    OB.save_basiq(db, api_key="K2"); db.commit()
    class R:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return {"access_token": "NEW"}
    monkeypatch.setattr(BA.requests, "post", lambda *a, **k: R())
    assert BA.get_access_token() == "NEW"                                                         # replacing the key never reuses the old token


def test_http_basiq_setup_is_admin_only(env):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from accfino_core.api import openbanking_admin_api as API
    from accfino_core.security.context import current_auth
    from db_app.database import get_db
    db, org, ctx = env
    st = {"admin": False}
    app = FastAPI(); app.include_router(API.router, prefix="/admin/open-banking")
    app.dependency_overrides[get_db] = lambda: db
    @app.middleware("http")
    async def _auth(request, call_next):                                  # what the real auth middleware does: put the caller on request.state
        request.state.auth = {"user_id": 1, "username": "t", "is_admin": st["admin"]}
        return await call_next(request)
    c = TestClient(app)
    assert c.get("/admin/open-banking").status_code == 403 and c.put("/admin/open-banking/basiq", json={"api_key": "x"}).status_code == 403
    assert c.post("/admin/open-banking/basiq/test").status_code == 403
    st["admin"] = True
    out = c.put("/admin/open-banking/basiq", json={"api_key": "ADMIN-SAVED"}).json()
    assert out["configured"] is True and "ADMIN-SAVED" not in str(out)
    full = c.get("/admin/open-banking").json()
    assert full["basiq"]["configured"] is True and "ADMIN-SAVED" not in str(full) and set(full["openfeed"]) >= {"ready", "hasKeys", "hasIds", "missing"}
    assert c.put("/admin/open-banking/basiq", json={"base_url": "http://x"}).status_code == 422
