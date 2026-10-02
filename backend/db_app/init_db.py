import bcrypt
from db_app.database import engine, SessionLocal
from db_app.models.base import Base
from db_app.models.user import User
from db_app.models.role import Role
from db_app.models.permission import Permission
from db_app.models.invoice import BusinessDetail, Customer, Invoice, InvoiceItem
from db_app.models.platform_setting import PlatformSetting
from db_app.models import association

PERMISSIONS = [
    ("read",  "Read access"),
    ("write", "Write access"),
    ("admin", "Admin access"),
]

ROLE_PERMISSIONS = {
    "admin": ["read", "write", "admin"],
    "user":  ["read", "write"],
}

# -- Admin credentials ---------------------------------------------------------
# ADMIN_PASSWORD is only used when the admin account is first created (or when
# ADMIN_FORCE_RESET=true). Set it in the environment; the legacy default below is
# public in source control, so /api/admin/security-status flags it until changed.
import os as _os
ADMIN_EMAIL    = _os.environ.get("ADMIN_EMAIL", "admin@accfino.com")
ADMIN_PASSWORD = _os.environ.get("ADMIN_PASSWORD", "Accfino@1")
# -----------------------------------------------------------------------------

def _ensure_home_company_column():
    """Add home_company column to users table if it doesn't exist yet."""
    import sqlite3
    from db_app.database import _DATABASE_URL
    if not _DATABASE_URL.startswith("sqlite"):
        return
    db_path = _DATABASE_URL.replace("sqlite:///", "")
    try:
        conn = sqlite3.connect(db_path)
        cols = [r[1] for r in conn.execute("PRAGMA table_info(users)").fetchall()]
        if "home_company" not in cols:
            conn.execute("ALTER TABLE users ADD COLUMN home_company VARCHAR(255) DEFAULT ''")
            conn.commit()
            print("Migration: added users.home_company column")
        conn.close()
    except Exception as e:
        print(f"Warning: home_company migration skipped: {e}")


def _admin_phone():
    """ADMIN_PHONE (env) is the platform administrator's phone. Without it the account is still created (the app must be able to start on a fresh
    database) but is marked incomplete and its owner is asked to add a phone at first sign-in."""
    import os
    from accfino_core.security import contact
    raw = os.environ.get("ADMIN_PHONE", "").strip()
    try:
        return contact.normalise_phone(raw) if raw else None
    except contact.ContactError:
        print("Warning: ADMIN_PHONE is not a valid phone number - ignoring it")
        return None


def _ensure_admin_exists(db):
    """
    Ensure the admin user exists with correct password and role.
    Runs every startup — optimised to avoid bcrypt cost when nothing changed.
    """
    try:
        from db_app.models.user import User
        from db_app.models.role import Role
        import bcrypt as _bcrypt

        admin = db.query(User).filter(
            (User.email == ADMIN_EMAIL) | (User.username == "admin")
        ).first()

        if not admin:
            print("Admin user missing - creating...")
            admin_role = db.query(Role).filter(Role.name == "admin").first()
            hashed = _bcrypt.hashpw(ADMIN_PASSWORD.encode(), _bcrypt.gensalt()).decode()
            from accfino_core.security.contact import allow_incomplete_contact
            admin = User(
                username="admin",
                full_name="Administrator",
                email=ADMIN_EMAIL,
                password=hashed,
                phone=_admin_phone(),
            )
            if admin_role:
                admin.roles.append(admin_role)
            db.add(admin)
            with allow_incomplete_contact(db):          # bootstrap only: lets the platform start before a phone number is known
                db.commit()
            print(f"Admin user created. Email: {ADMIN_EMAIL}")
            return

        changed = False

        if (admin.email or "").lower() != ADMIN_EMAIL.lower():
            admin.email = ADMIN_EMAIL
            changed = True

        # Only run bcrypt (slow) if the stored hash doesn't verify the current password.
        # bcrypt.checkpw takes ~300ms — skip it if the hash prefix looks valid.
        from accfino_core import config as _cfg0
        _pw_ok = True
        if _cfg0.ADMIN_FORCE_RESET:
            try:
                _pw_ok = bool(admin.password) and _bcrypt.checkpw(
                    ADMIN_PASSWORD.encode(), admin.password.encode()
                )
            except Exception:
                _pw_ok = False

        # Phase 0 security fix: never silently reset a changed admin password on
        # startup. Only re-apply ADMIN_PASSWORD when explicitly requested.
        from accfino_core import config as _cfg
        if not _pw_ok and _cfg.ADMIN_FORCE_RESET:
            admin.password = _bcrypt.hashpw(ADMIN_PASSWORD.encode(), _bcrypt.gensalt()).decode()
            changed = True
            print("ADMIN_FORCE_RESET: admin password re-applied from ADMIN_PASSWORD.")

        role_names = [r.name for r in admin.roles]
        if "admin" not in role_names:
            admin_role = db.query(Role).filter(Role.name == "admin").first()
            if admin_role:
                admin.roles.append(admin_role)
                changed = True

        if changed:
            db.commit()

    except Exception as e:
        print(f"Warning: _ensure_admin_exists failed (non-fatal): {e}")


class ForeignDatabaseError(RuntimeError):
    pass


def _wait_for_database(attempts: int = 6):
    """Neon suspends idle compute; the first connection after a pause is often dropped
    ("server closed the connection unexpectedly"). Retry with backoff so a cold start
    doesn't abort start-up."""
    import time
    from sqlalchemy import text as _t
    for i in range(1, attempts + 1):
        try:
            with engine.connect() as c:
                c.execute(_t("SELECT 1"))
            return
        except Exception as e:
            if i == attempts:
                raise
            wait = min(2 ** i, 20)
            print(f"[accfino] database not ready (attempt {i}/{attempts}): {str(e).splitlines()[0][:110]} - retrying in {wait}s")
            time.sleep(wait)


def _check_database_is_accfino():
    """Refuse to touch a database that belongs to another application.

    Rules (checked BEFORE any table is created or altered):
      * users table exists  -> it must look like AccFino's (integer id, username, email, password)
      * no users table      -> the database must be empty (a brand-new AccFino install)
    Override for the empty-check only with ACCFINO_INIT_NONEMPTY_DB=true (e.g. shared schema by design).
    """
    import os as _o
    from sqlalchemy import inspect as _inspect
    insp = _inspect(engine)
    tables = set(insp.get_table_names())
    safe_url = engine.url.render_as_string(hide_password=True)
    if "users" in tables:
        cols = {c["name"]: c for c in insp.get_columns("users")}
        missing = [c for c in ("username", "email", "password") if c not in cols]
        id_type = str(cols.get("id", {}).get("type", "")).upper()
        if missing or "INT" not in id_type:
            raise ForeignDatabaseError(
                "\n[accfino] STOPPED - this database is not an AccFino database. Nothing was changed.\n"
                f"  DATABASE_URL -> {safe_url}\n"
                f"  Its 'users' table has id type {id_type or '?'} and is missing columns {missing}.\n"
                "  It probably belongs to another application. Point DATABASE_URL in .env at an AccFino\n"
                "  database (or a new empty database / Neon branch for a fresh install).")
    elif tables and _o.environ.get("ACCFINO_INIT_NONEMPTY_DB", "").lower() not in ("1", "true", "yes"):
        sample = ", ".join(sorted(tables)[:8])
        raise ForeignDatabaseError(
            "\n[accfino] STOPPED - this database already contains tables from another application. Nothing was changed.\n"
            f"  DATABASE_URL -> {safe_url}\n  Existing tables: {sample}{' ...' if len(tables) > 8 else ''}\n"
            "  Use an empty database (or a new Neon branch) for a fresh AccFino install.")


def init_db():
    print("Initializing database...")
    _wait_for_database()                  # wake a suspended Neon database first
    _check_database_is_accfino()          # before ANY change - protects other applications' databases
    _ensure_home_company_column()

    # Upgrade steps for EXISTING databases (idempotent). On a brand-new database there is
    # nothing to upgrade - create_all below builds every table - so skip them quietly.
    from sqlalchemy import inspect as _insp
    if _insp(engine).has_table("users"):
        try:
            from db_app.migrations.add_currency_loan_columns import run as _mc1
            _mc1(engine)
        except Exception as _me:
            print(f"Warning: currency/loan migration skipped: {_me}")
        try:
            from db_app.migrations.create_account_balances import run as _mc2
            _mc2(engine)
        except Exception as _me:
            print(f"Warning: account_balances migration skipped: {_me}")
    else:
        print("New database - creating all tables.")

    # Create any missing tables (checkfirst=True is a single fast query per table)
    try:
        Base.metadata.create_all(bind=engine, checkfirst=True)
    except Exception as _e:
        print(f"Warning: create_all skipped: {_e}")

    db = SessionLocal()

    try:
        if db.query(User).count() > 0:
            print("Users already exist. Skipping user creation.")
            _ensure_admin_exists(db)
            db.close()          # release this session's read lock on "users" before the migration alters/protects that table
            _run_platform_migration()
            return

        permission_map = {}
        for name, description in PERMISSIONS:
            p = Permission(name=name, description=description)
            db.add(p)
            permission_map[name] = p

        db.flush()

        role_map = {}
        for role_name, perms in ROLE_PERMISSIONS.items():
            role = Role(
                name=role_name,
                description='Admin with full access' if role_name == 'admin' else 'Regular user'
            )
            for perm_name in perms:
                perm = permission_map.get(perm_name)
                if perm:
                    role.permissions.append(perm)
            db.add(role)
            role_map[role_name] = role

        db.flush()

        hashed_password = bcrypt.hashpw(
            ADMIN_PASSWORD.encode(),
            bcrypt.gensalt()
        ).decode()

        from accfino_core.security.contact import allow_incomplete_contact
        admin_user = User(
            username="admin",
            full_name="Administrator",
            email=ADMIN_EMAIL,
            password=hashed_password,
            phone=_admin_phone(),
        )
        admin_user.roles.append(role_map["admin"])
        db.add(admin_user)
        with allow_incomplete_contact(db):              # bootstrap only: lets the platform start before a phone number is known
            db.commit()
        print(f"Admin user created. Email: {ADMIN_EMAIL}")

    except Exception as e:
        db.rollback()
        print(f"Error initializing database: {e}")
        raise

    finally:
        db.close()

    _seed_companies_safe()
    _run_platform_migration()


def _run_platform_migration():
    """Phase 0: organisations, ledger, audit and security tables + integrity triggers."""
    from accfino_core.migrate import run as _platform_run
    _platform_run(engine, SessionLocal)
    print("Platform core migration complete.")


def _seed_companies_safe():
    """Seed company database - skips if already seeded."""
    try:
        from db_app.models.company import Company
        db2 = SessionLocal()
        count = db2.query(Company).count()
        if count > 0:
            print(f"Company DB: {count} companies already in DB, skipping seed.")
            db2.close()
            return
        from db_app.company_seed import seed_companies
        n = seed_companies(db2)
        print(f"Company DB: {n} new companies seeded.")
        db2.close()
    except Exception as e:
        print(f"Warning: company seed failed (non-fatal): {e}")


def ensure_demo_licences():
    """Ensure every user has a licence record. Skips quickly if already done."""
    from datetime import datetime, timedelta, timezone
    from db_app.models.licence import LicenceRecord
    from db_app.models.user import User
    import json as _json

    BASE_MODULES  = ["dashboard", "reconciliation"]
    ADMIN_MODULES = ["dashboard", "reconciliation", "trading",
                     "cash-flow", "invoice", "admin", "file-manager", "licence"]

    db = SessionLocal()
    try:
        today   = datetime.now(timezone.utc).date()
        today_s = str(today)

        # Fast path: if licence count == user count, everything is already set up
        user_count = db.query(User).count()
        lic_count  = db.query(LicenceRecord).count()
        if user_count > 0 and lic_count >= user_count:
            return   # nothing to do — skip the per-user loop entirely

        users = db.query(User).all()
        for user in users:
            is_admin = any(r.name == "admin" for r in user.roles)
            lic = db.query(LicenceRecord).filter(LicenceRecord.user_id == user.id).first()

            if not lic:
                lic = LicenceRecord(
                    user_id      = user.id,
                    licence_type = "admin" if is_admin else "base",
                    plan_id      = "complete" if is_admin else "essentials",
                    payment_mode = "",
                    start_date   = today_s,
                    end_date     = "9999-12-31" if is_admin else str(today + timedelta(days=183)),
                    notes        = "Auto-created",
                    modules      = _json.dumps(ADMIN_MODULES if is_admin else BASE_MODULES),
                )
                db.add(lic)
            else:
                changed = False
                if not lic.start_date:
                    lic.start_date = today_s; changed = True
                if not lic.end_date:
                    lic.end_date = "9999-12-31" if is_admin else str(today + timedelta(days=183)); changed = True
                if not lic.licence_type or lic.licence_type == "demo":
                    lic.licence_type = "admin" if is_admin else "base"; changed = True
                if is_admin and lic.plan_id in ("admin", "premium", "base", "", None):
                    lic.plan_id = "complete"; changed = True
                if is_admin and lic.end_date != "9999-12-31":
                    lic.end_date = "9999-12-31"; changed = True
                if not lic.modules or lic.modules == "":
                    lic.modules = _json.dumps(ADMIN_MODULES if is_admin else BASE_MODULES); changed = True

        db.commit()
        print("Licences ensured for all users.")
    except Exception as e:
        db.rollback()
        print(f"Warning: could not ensure licences: {e}")
    finally:
        db.close()


def migrate_db():
    """No-op on PostgreSQL - schema managed by SQLAlchemy Base.metadata.create_all."""
    return
    # Legacy SQLite migration below (kept for reference)
    import sqlite3
    from db_app.database import _DB_FILE
    db = sqlite3.connect(str(_DB_FILE))
    try:
        cols = [r[1] for r in db.execute("PRAGMA table_info(licence_records)").fetchall()]
        new_cols = [
            ("plan_id",            "VARCHAR(50)"),
            ("billing_period",     "VARCHAR(10)"),
            ("stripe_customer_id", "VARCHAR(100)"),
            ("stripe_sub_id",      "VARCHAR(100)"),
            ("amount_paid",        "VARCHAR(20)"),
        ]
        user_cols = [r[1] for r in db.execute("PRAGMA table_info(users)").fetchall()]
        if "home_company" not in user_cols:
            db.execute("ALTER TABLE users ADD COLUMN home_company VARCHAR(255) DEFAULT ''")
            print("Migration: added column users.home_company")
        for col, typ in new_cols:
            if col not in cols:
                db.execute(f"ALTER TABLE licence_records ADD COLUMN {col} {typ} DEFAULT ''")
                print(f"Migration: added column {col}")
        db.commit()
    except Exception as e:
        print(f"Migration warning: {e}")
    finally:
        db.close()


if __name__ == "__main__":
    try:
        init_db()
    except ForeignDatabaseError as _fe:
        print(_fe)
        raise SystemExit(2)
    migrate_db()
    ensure_demo_licences()