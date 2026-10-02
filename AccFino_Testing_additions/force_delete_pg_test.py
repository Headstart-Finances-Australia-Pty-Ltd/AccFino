"""Force delete, platform-administrator protection and the Organisations & Users directory - on a REAL PostgreSQL (the SQLite tests cannot show these).
Needs `pip install pgserver` (a self-contained Postgres); skipped when it is not installed.
Run from backend/:  PYTHONPATH=. python -m pytest ../AccFino_Testing_additions/force_delete_pg_test.py -q"""
import os, sys, tempfile
import pytest
pgserver = pytest.importorskip("pgserver")
from types import SimpleNamespace as NS
from sqlalchemy import create_engine, text
from sqlalchemy.orm import close_all_sessions


@pytest.fixture(scope="module")
def pg():
    srv = pgserver.get_server(tempfile.mkdtemp())
    os.environ.update(DATABASE_URL="postgresql+psycopg2://x:x@localhost/x", JWT_SECRET="x" * 64, CONTACT_VERIFICATION="off")
    import db_app.database as DBM
    eng = create_engine(srv.get_uri().replace("postgresql://", "postgresql+psycopg2://", 1), pool_pre_ping=True)
    DBM.engine = eng; DBM.SessionLocal.configure(bind=eng)
    import db_app.models  # noqa
    import accfino_core.subscription.models, accfino_core.tenancy.models  # noqa
    from accfino_core import models as m, migrate
    from db_app.models.base import Base
    Base.metadata.create_all(eng); m.Base.metadata.create_all(eng)
    with eng.begin() as c:
        c.execute(text(migrate.platform_admin_protect_sql()))
        # what an older database can contain: NO ACTION references to rows that cascade from a user
        c.execute(text("CREATE TABLE zz_blk1 (id serial primary key, txn_id int references transactions(id))"))
        c.execute(text("CREATE TABLE zz_blk2 (id serial primary key, lic_id int not null references licence_records(id))"))
    yield DBM.SessionLocal, eng
    srv.cleanup()


@pytest.fixture()
def world(pg):
    SL, eng = pg
    close_all_sessions()                       # a session left open by an earlier test would block the TRUNCATE below
    with eng.connect() as c0:                  # ...and so would one a failed statement left "idle in transaction"
        c0.execute(text("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = current_database() AND pid <> pg_backend_pid() AND state LIKE 'idle in transaction%'"))
        c0.commit()
    from accfino_core import models as m, seed_demo as SD
    from accfino_core.subscription import service as S
    from db_app.models import Role, User
    with eng.begin() as c:
        c.execute(text("SET LOCAL lock_timeout = '10s'"))
        c.execute(text("TRUNCATE users RESTART IDENTITY CASCADE"))
    with eng.begin() as c:
        c.execute(text("TRUNCATE roles RESTART IDENTITY CASCADE"))
        c.execute(text("TRUNCATE organisations RESTART IDENTITY CASCADE")); c.execute(text("TRUNCATE zz_blk1, zz_blk2"))
    db = SL()
    db.add_all([Role(name="admin"), Role(name="user")]); db.commit()
    adm = User(username="admin", full_name="AccFino Admin", email="admin@accfino.com", password="x", phone="+61400000000")
    adm.roles.append(db.query(Role).filter_by(name="admin").first()); db.add(adm); db.commit()
    us = [SD._get_or_create_user(db, f"u{i}@example.com")[0] for i in range(1, 6)]
    o1 = SD._make_org(db, us[0], "Alpha Pty Ltd"); o2 = SD._make_org(db, us[2], "Beta Pty Ltd")
    db.add(m.OrgMembership(org_id=o1.id, user_id=us[1].id, role="accountant")); db.add(m.OrgMembership(org_id=o2.id, user_id=us[3].id, role="bookkeeper"))
    db.commit(); S.start_subscription(db, o1.id); db.commit()
    ids = dict(admin=adm.id, u=[u.id for u in us], o1=o1.id, o2=o2.id)
    db.close()
    yield SL, eng, ids
    close_all_sessions()


def _blockers(eng, user_id):
    """Give the user a transaction and licence row that legacy NO ACTION tables point at."""
    with eng.begin() as c:
        lid = c.execute(text("INSERT INTO licence_records (user_id, licence_type) VALUES (:u,'demo') RETURNING id"), {"u": user_id}).scalar()
        tid = c.execute(text("INSERT INTO transactions (user_id,date,bank,account,description) VALUES (:u,'2026-09-01','NAB','1','x') RETURNING id"), {"u": user_id}).scalar()
        c.execute(text("INSERT INTO zz_blk1 (txn_id) VALUES (:t)"), {"t": tid}); c.execute(text("INSERT INTO zz_blk2 (lic_id) VALUES (:l)"), {"l": lid})


def test_force_delete_clears_references_that_block_a_cascade(world):
    from fastapi import HTTPException
    from accfino_core import force_delete as FD
    SL, eng, ids = world
    victim = ids["u"][1]
    _blockers(eng, victim)
    db = SL()
    with pytest.raises(HTTPException) as e:                                  # normal delete: refused, and says to use Force delete
        FD.delete_user(db, victim, actor_id=ids["admin"], force=False)
    assert e.value.status_code == 409 and "Force delete" in e.value.detail
    db.rollback()
    info = FD.delete_user(db, victim, actor_id=ids["admin"], force=True)     # force: works, whatever the legacy tables say
    db.commit()
    assert info["id"] == victim
    with eng.connect() as c:
        assert c.execute(text("SELECT count(*) FROM users WHERE id=:u"), {"u": victim}).scalar() == 0
        assert c.execute(text("SELECT count(*) FROM zz_blk2")).scalar() == 0
        assert c.execute(text("SELECT txn_id FROM zz_blk1")).scalar() is None


def test_force_delete_failure_names_the_real_cause_not_use_force_delete(world, monkeypatch):
    from fastapi import HTTPException
    from accfino_core import force_delete as FD
    SL, eng, ids = world
    victim = ids["u"][1]; _blockers(eng, victim)
    monkeypatch.setattr(FD, "_clear_cascade_blockers", lambda db, uid: None)   # simulate a blocker the clean-up could not remove
    db = SL()
    with pytest.raises(HTTPException) as e:
        FD.delete_user(db, victim, actor_id=ids["admin"], force=True)
    db.rollback()
    assert "violates foreign key constraint" in e.value.detail and "Use Force delete" not in e.value.detail


def test_platform_admin_cannot_be_deleted_by_any_route(world):
    from fastapi import HTTPException
    from sqlalchemy.exc import DBAPIError
    from accfino_core import force_delete as FD
    SL, eng, ids = world
    db = SL()
    for force in (False, True):
        with pytest.raises(HTTPException) as e:
            FD.delete_user(db, ids["admin"], actor_id=None, force=force)
        assert e.value.status_code == 409 and "cannot be deleted" in e.value.detail
        db.rollback()
    with pytest.raises(DBAPIError) as e2:                                      # even raw SQL (database trigger)
        db.execute(text("DELETE FROM users WHERE id=:u"), {"u": ids["admin"]})
    assert "cannot be deleted" in str(e2.value)
    db.rollback()
    # selected together with ordinary users, the admin is skipped and the rest are deleted
    from accfino_core.api import force_delete_api as API
    FD.set_force_delete(db, True); db.commit()
    req = NS(state=NS(auth={"is_admin": True, "user_id": ids["u"][4], "username": "x"}), headers={}, client=NS(host="127.0.0.1"))
    out = API._run("user", API.BulkIn(ids=[ids["admin"], ids["u"][3]], force=True), req, db, FD.delete_user)
    by = {r["id"]: r for r in out["results"]}
    assert by[ids["admin"]]["ok"] is False and by[ids["u"][3]]["ok"] is True
    db.rollback(); db.close()


def test_directory_lists_orgs_with_contact_licence_and_users(world):
    from accfino_core.api import org_directory_api as OD
    SL, eng, ids = world
    db = SL()
    d = OD.org_directory(NS(state=NS(auth={"is_admin": True, "user_id": ids["admin"]})), db=db)
    assert [a["email"] for a in d["platform_admins"]] == ["admin@accfino.com"] and d["platform_admins"][0]["protected"]
    alpha = next(o for o in d["organisations"] if o["name"] == "Alpha Pty Ltd")
    assert alpha["admin"]["email"] == "u1@example.com" and alpha["admin"]["phone"].startswith("+61")
    assert alpha["licence"]["plan_name"] == "Essential" and alpha["licence"]["seats"] == 1 and alpha["licence"]["active_users"] == 2 and alpha["user_count"] == 2
    assert [(u["email"], u["role"]) for u in alpha["users"]] == [("u1@example.com", "owner"), ("u2@example.com", "accountant")]
    assert [u["email"] for u in d["unassigned_users"]] == ["u5@example.com"]
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as e:
        OD.org_directory(NS(state=NS(auth={"is_admin": False, "user_id": 2})), db=db)
    assert e.value.status_code == 403
    db.rollback(); db.close()


def test_deleting_the_last_user_removes_the_now_empty_organisation(world):
    from accfino_core import force_delete as FD, models as m
    SL, eng, ids = world
    db = SL()
    # Beta has two users (u3 owner, u4 member): deleting one keeps the organisation, deleting the last removes it
    FD.delete_user(db, ids["u"][3], actor_id=ids["admin"], force=False); db.commit()
    assert db.get(m.Organisation, ids["o2"]) is not None
    info = FD.delete_user(db, ids["u"][2], actor_id=ids["admin"], force=False); db.commit()
    assert [o["id"] for o in info["orgs_removed"]] == [ids["o2"]]
    assert db.get(m.Organisation, ids["o2"]) is None
    assert db.get(m.Organisation, ids["o1"]) is not None                     # the other organisation is untouched
    db.rollback(); db.close()


def test_prune_empty_removes_existing_orphans_only(world):
    from accfino_core import force_delete as FD, models as m
    from accfino_core.api import org_directory_api as OD
    from types import SimpleNamespace as NS
    SL, eng, ids = world
    with eng.begin() as c:                                                    # leftovers: organisations whose users were deleted earlier
        c.execute(text("DELETE FROM org_memberships WHERE org_id = :o"), {"o": ids["o2"]})
    db = SL()
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as e:
        OD.prune_empty(NS(state=NS(auth={"is_admin": False, "user_id": 2})), db=db)
    assert e.value.status_code == 403
    res = OD.prune_empty(NS(state=NS(auth={"is_admin": True, "user_id": ids["admin"]})), db=db)
    assert [o["id"] for o in res["removed"]] == [ids["o2"]] and res["skipped"] == []
    assert db.get(m.Organisation, ids["o2"]) is None and db.get(m.Organisation, ids["o1"]) is not None
    db.rollback(); db.close()


def test_orphan_logins_are_removed_and_licence_list_hides_them(world):
    from types import SimpleNamespace as NS
    from accfino_core.api import org_directory_api as OD
    from db_app.models.user import User
    SL, eng, ids = world
    with eng.begin() as c:                                                    # u5 belongs to no organisation (already true); also orphan u4 by deleting its membership
        c.execute(text("DELETE FROM org_memberships WHERE user_id = :u"), {"u": ids["u"][3]})
    db = SL()
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as e:
        OD.prune_orphan_users(NS(state=NS(auth={"is_admin": False, "user_id": 2})), db=db)
    assert e.value.status_code == 403
    res = OD.prune_orphan_users(NS(state=NS(auth={"is_admin": True, "user_id": ids["admin"]})), db=db)
    assert sorted(r["id"] for r in res["removed"]) == sorted([ids["u"][3], ids["u"][4]]) and res["skipped"] == []
    left = {u.id for u in db.query(User).all()}
    assert ids["admin"] in left and ids["u"][0] in left and ids["u"][3] not in left and ids["u"][4] not in left     # admin + organisation members stay
    db.rollback(); db.close()


def test_migration_removes_only_untouched_auto_created_licences(world):
    import json
    from accfino_core import migrate
    from sqlalchemy import inspect
    SL, eng, ids = world
    with eng.begin() as c:
        c.execute(text("DELETE FROM licence_records"))
        for uid, notes, mods in ((ids["u"][0], "Auto-created on organisation signup - base plan", json.dumps(["dashboard", "reconciliation"])),
                                 (ids["u"][1], "Auto-created on organisation signup - base plan", json.dumps(["dashboard", "payroll"])),     # an admin edited the modules
                                 (ids["u"][2], "Manual gold licence", json.dumps(["dashboard", "reconciliation"]))):
            c.execute(text("INSERT INTO licence_records (user_id, licence_type, notes, modules) VALUES (:u,'base',:n,:m)"), {"u": uid, "n": notes, "m": mods})
    migrate.run(eng, SL)                                                                # runs on every start
    with eng.connect() as c:
        kept = {r[0] for r in c.execute(text("SELECT user_id FROM licence_records")).fetchall()}
    assert kept == {ids["u"][1], ids["u"][2]}                                           # only the untouched auto-created record is gone
