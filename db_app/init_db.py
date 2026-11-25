import bcrypt
from db_app.database import engine, SessionLocal
from db_app.models.base import Base
from db_app.models.user import User
from db_app.models.role import Role
from db_app.models.permission import Permission
from db_app.models.invoice import BusinessDetail, Customer, Invoice, InvoiceItem
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

# -- Admin credentials - change here to update everywhere ---------------------
ADMIN_EMAIL    = "admin@accfino.com"
ADMIN_PASSWORD = "Accfino@1"
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
            admin = User(
                username="admin",
                full_name="Administrator",
                email=ADMIN_EMAIL,
                password=hashed,
            )
            if admin_role:
                admin.roles.append(admin_role)
            db.add(admin)
            db.commit()
            print(f"Admin user created. Email: {ADMIN_EMAIL}")
            return

        changed = False

        if admin.email != ADMIN_EMAIL:
            admin.email = ADMIN_EMAIL
            changed = True

        # Only run bcrypt (slow) if the stored hash doesn't verify the current password.
        # bcrypt.checkpw takes ~300ms — skip it if the hash prefix looks valid.
        try:
            _pw_ok = bool(admin.password) and _bcrypt.checkpw(
                ADMIN_PASSWORD.encode(), admin.password.encode()
            )
        except Exception:
            _pw_ok = False

        if not _pw_ok:
            admin.password = _bcrypt.hashpw(ADMIN_PASSWORD.encode(), _bcrypt.gensalt()).decode()
            changed = True
            print("Fixed: admin password updated.")

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


def init_db():
    print("Initializing database...")
    _ensure_home_company_column()

    # Migrations (idempotent — fast no-op if already applied)
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

        admin_user = User(
            username="admin",
            full_name="Administrator",
            email=ADMIN_EMAIL,
            password=hashed_password,
        )
        admin_user.roles.append(role_map["admin"])
        db.add(admin_user)
        db.commit()
        print(f"Admin user created. Email: {ADMIN_EMAIL}")

    except Exception as e:
        db.rollback()
        print(f"Error initializing database: {e}")
        raise

    finally:
        db.close()

    _seed_companies_safe()


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
                    plan_id      = "premium" if is_admin else "base",
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
                if is_admin and lic.plan_id in ("admin", "", None):
                    lic.plan_id = "premium"; changed = True
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
    init_db()
    migrate_db()
    ensure_demo_licences()