from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy import func, or_
from sqlalchemy import text
from sqlalchemy.orm import Session
from db_app.models import Role, User
from db_app.models.licence import LicenceRecord
import bcrypt
import json as _json
from pydantic import BaseModel
from db_app.database import get_db

router = APIRouter()

class LoginRequest(BaseModel):
    email: str
    password: str

class RegisterRequest(BaseModel):
    username: str
    home_company: str | None = None   # registered company for internal transfer detection
    full_name: str | None = None
    email: str
    password: str
    phone: str | None = None
    address: str | None = None
    role: str | None = None  # Optional, only honored for first user or by admin
    plan_id: str | None = "base"  # Selected subscription plan

class UserResponse(BaseModel):
    id: int
    username: str | None
    name: str
    email: str
    roles: list[str]
    permissions: list[str]
    # Included so the frontend can auto-fill forms (e.g. the Business
    # Account setup form) from the logged-in user's own profile data,
    # without a separate round-trip.
    phone: str | None = None
    address: str | None = None
    home_company: str | None = None
    # Phase 0: session token and organisation context (optional, additive)
    token: str | None = None
    token_expires_at: str | None = None
    org_id: int | None = None
    organisations: list[dict] | None = None
    mfa_enabled: bool | None = None
    mfa_methods: list[str] | None = None
    password_change_required: bool | None = None
    # Accounts created before email + phone were mandatory: true while either is missing/invalid, so the app can ask for them at sign-in
    profile_incomplete: bool | None = None
    missing_contact: list[str] | None = None
    session_id: str | None = None
    mfa_required_to_enrol: bool | None = None


def build_user_response(user: User) -> UserResponse:
    roles = [role.name.strip() for role in user.roles]

    # Flatten role permissions and remove duplicates.
    permissions = sorted(
        {
            perm.name.strip()
            for role in user.roles
            for perm in role.permissions
            if perm.name
        }
    )

    from accfino_core.security.contact import missing_contact
    missing = missing_contact(user.email, user.phone)
    return UserResponse(
        id=user.id,
        username=user.username,
        name=user.full_name or user.username,
        email=user.email,
        roles=roles,
        permissions=permissions,
        phone=user.phone,
        address=user.address,
        home_company=user.home_company,
        profile_incomplete=bool(missing),
        missing_contact=missing,
    )


def ensure_users_full_name_column(db: Session):
    # Lightweight schema backfill for existing SQLite DBs created before full_name existed.
    engine_name = db.bind.dialect.name if db.bind else ""
    if engine_name != "sqlite":
        return

    users_table = db.execute(
        text("SELECT name FROM sqlite_master WHERE type='table' AND name='users'")
    ).fetchone()
    if not users_table:
        return

    columns = db.execute(text("PRAGMA table_info(users)")).fetchall()
    column_names = {row[1] for row in columns}
    if "full_name" not in column_names:
        db.execute(text("ALTER TABLE users ADD COLUMN full_name VARCHAR(200)"))
        db.commit()


# login endpoint
def authenticate_user(email: str, password: str, db: Session, request: Request | None = None):
    """Password check with lockout, IP throttling and audit. Returns the user
    response with an access token, or {mfa_required, mfa_token} when MFA is on."""
    from accfino_core.security import login as L
    from accfino_core.security import tokens as T
    ensure_users_full_name_column(db)
    ip = L.client_ip(request)
    L.throttle_ip(ip)

    # Keep request schema stable but allow email or username in this field.
    login_value = email.strip()
    user = (
        db.query(User)
        .filter(or_(User.email == login_value, func.lower(User.email) == login_value.lower(), User.username == login_value))
        .first()
    )

    if not login_value or not password:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Please enter your email (or user id) and password.")

    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="No account exists for this email / user id. Check it, or create an account.")

    sec = L.check_locked(db, user)

    try:
        pw_ok = bcrypt.checkpw(password.encode(), user.password.encode())
    except Exception:
        pw_ok = False
    if not pw_ok:
        L.record_failure(db, user, ip)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="The email / user id and password do not match. Check your password and try again.")
    L.check_disabled(db, user)

    # On an organisation's own address (https://<org>.<domain>) only that organisation's members may sign in
    from accfino_core.tenancy.service import request_tenant, org_id_for_slug
    _slug = request_tenant(request.headers) if request is not None else None
    if _slug and not user.has_role("admin"):
        _oid = org_id_for_slug(db, _slug)
        from accfino_core import models as _m
        _mem = db.query(_m.OrgMembership).filter_by(user_id=user.id, org_id=_oid).first() if _oid else None
        if _mem is None or _mem.suspended_at:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                                detail="You do not have access to this organisation. Sign in at your own organisation's web address.")

    from accfino_core.security import mfa_service as S
    methods = S.available_methods(db, sec)
    if methods:
        db.commit()
        return JSONResponse({"mfa_required": True, "mfa_token": T.issue_mfa_token(user.id),
                             "methods": methods + (["recovery"] if sec.mfa_recovery_hashes else []),
                             "phone_hint": S.mask_phone(sec.phone_e164) if "sms" in methods else None,
                             "email_hint": S.mask_email(user.email) if "email" in methods else None,
                             "id": user.id, "email": user.email})

    L.record_success(db, user, ip)
    resp = build_user_response(user)
    for k, v in L.token_fields(db, user, mfa_verified=False, request=request, amr=["pwd"]).items():
        setattr(resp, k, v)
    db.commit()
    return resp


@router.post("/login", response_model=UserResponse)
def login_post(
    http_request: Request,
    request: LoginRequest = Body(...),
    db: Session = Depends(get_db),
):
    if request is not None:
        return authenticate_user(request.email, request.password, db, http_request)

    raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Provide email and password in JSON body or query params",
        )


@router.get("/login", response_model=UserResponse)
def login_get(
    email: str = Query(...),
    password: str = Query(...),
    db: Session = Depends(get_db),
):
    return authenticate_user(email, password, db, None)

@router.post("/register", response_model=UserResponse)
def register(
    request: RegisterRequest = Body(...),
    db: Session = Depends(get_db),
):
    ensure_users_full_name_column(db)

    # Organisation-first signup: no organisation + no access code = no account. This open endpoint now only serves the very first user of an
    # empty system (bootstrap) unless ACCFINO_OPEN_SIGNUP=1 is set deliberately. Everyone else signs up through /signup/* .
    from accfino_core.tenancy.service import legacy_signup_allowed
    if not legacy_signup_allowed(db):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Sign-up starts with your organisation: create a new organisation, or join one with an access code from its administrator.")

    # Email address and phone number are mandatory for EVERY account, on every route that creates one.
    from accfino_core.security import contact as _C
    try:
        _email, _phone = _C.validate_contact(request.email, request.phone)
    except _C.ContactError as e:
        raise _C.http_422(e)
    request.email, request.phone = _email, _phone

    if db.query(User).filter(func.lower(User.email) == _email).first():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email already registered")
    if db.query(User).filter(User.username == request.username).first():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Username already taken")

    from accfino_core.security.passwords import validate_new_password
    validate_new_password(request.password)

    hashed = bcrypt.hashpw(request.password.encode(), bcrypt.gensalt()).decode()
    is_first_user = db.query(User).count() == 0

    # Only allow role selection for first user or if admin is registering
    allowed_roles = {r.name for r in db.query(Role).all()}
    requested_role = (request.role or "user").strip().lower()
    if is_first_user:
        role_name = requested_role if requested_role in allowed_roles else "admin"
    else:
        # Check if current user is admin (future: use auth context)
        # For now, only allow 'user' role for non-first-user signups
        role_name = "user"

    role = db.query(Role).filter(Role.name == role_name).first()
    if not role:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Role not found in database")

    new_user = User(
        username=request.username,
        full_name=(request.full_name or request.username),
        email=request.email,
        password=hashed,
        phone=request.phone or "",
        address=request.address or "",
        home_company=(request.home_company or ""),
    )
    new_user.roles.append(role)
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    # Auto-create demo licence with 6-month trial period
    try:
        from datetime import datetime, timedelta
        today    = datetime.utcnow().date()
        end_date = today + timedelta(days=183)  # ~6 months
        # Set modules based on selected plan
        PLAN_MODULES = {
            "base":           ["dashboard", "reconciliation"],
            "vault":          ["dashboard", "reconciliation"],  # Vault = base free plan
            "reconciliation": ["dashboard", "reconciliation"],
            "trading":        ["dashboard", "trading"],         # trading only - no reconciliation
            "cashflow":       ["dashboard", "cash-flow"],
            "invoice":        ["dashboard", "invoice"],
            "basic":          ["dashboard", "reconciliation", "trading", "cash-flow", "invoice"],
            "premium":        ["dashboard", "reconciliation", "trading", "cash-flow", "invoice"],
            "ultra":          ["dashboard", "reconciliation", "trading", "cash-flow", "invoice"],
            # the current organisation plans
            "essentials":     ["dashboard", "accounting", "reconciliation", "invoice", "cash-flow"],
            "business":       ["dashboard", "accounting", "reconciliation", "invoice", "cash-flow"],
            "professional":   ["dashboard", "accounting", "reconciliation", "invoice", "cash-flow", "payroll", "trading"],
            "complete":       ["dashboard", "accounting", "reconciliation", "invoice", "cash-flow", "payroll", "trading", "lending"],
        }
        selected_plan = getattr(request, 'plan_id', 'base') or 'base'
        plan_modules  = PLAN_MODULES.get(selected_plan, PLAN_MODULES["base"])

        lic = LicenceRecord(
            user_id      = new_user.id,
            licence_type = selected_plan,
            plan_id      = selected_plan,
            payment_mode = "",
            start_date   = str(today),
            end_date     = str(end_date),
            notes        = f"Auto-created on registration - {selected_plan} plan",
            modules      = _json.dumps(plan_modules),
        )
        db.add(lic)
        db.commit()
    except Exception:
        db.rollback()  # Don't fail registration if licence creation fails

    # Phase 0: personal organisation (seeded chart of accounts) + security record
    from accfino_core.migrate import ensure_personal_org, ensure_user_security
    from accfino_core.security import audit
    ensure_user_security(db, new_user.id)
    ensure_personal_org(db, new_user)
    db.commit()
    audit.write("auth.registered", user_id=new_user.id, username=new_user.username)
    return build_user_response(new_user)


@router.get("/verify/{user_id}", response_model=UserResponse)
def verify_session(user_id: int, db: Session = Depends(get_db)):
    """Checks whether a cached/persisted user session is still valid --
    added specifically because the frontend restores its logged-in user
    straight from localStorage on page load with no server round-trip.
    If the database is ever reset/reseeded (as happened repeatedly during
    this app's migration work), a browser with an old cached session keeps
    "logging in" as a user_id that no longer exists, silently, until it
    hits a foreign-key error somewhere far from the actual cause (e.g.
    creating an invoice). The frontend calls this once on app load and
    logs out automatically if it 404s."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session no longer valid")
    return build_user_response(user)


class ChangePasswordRequest(BaseModel):
    email: str
    old_password: str
    new_password: str


@router.post("/change-password")
def change_password(
    http_request: Request,
    request: ChangePasswordRequest = Body(...),
    db: Session = Depends(get_db),
):
    """Was called by the frontend (Password tab) but never actually
    existed as a backend route -- every attempt was a silent 404.
    Mirrors authenticate_user's bcrypt verification exactly for the
    current-password check."""
    user = db.query(User).filter(User.email == request.email.strip()).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    _auth = getattr(http_request.state, "auth", None) or {}
    if _auth and not _auth.get("is_admin") and _auth.get("user_id") != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You can only change your own password")

    if not bcrypt.checkpw(request.old_password.encode(), user.password.encode()):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Current password is incorrect")

    from accfino_core.security.passwords import validate_new_password
    from accfino_core.security import audit, tokens as T
    from accfino_core.security.login import token_fields
    from accfino_core.migrate import ensure_user_security
    from datetime import datetime as _dt
    validate_new_password(request.new_password)

    user.password = bcrypt.hashpw(request.new_password.encode(), bcrypt.gensalt()).decode()
    sec = ensure_user_security(db, user.id)
    sec.token_version += 1            # sign out every other session
    sec.password_changed_at = _dt.utcnow()
    sec.must_change_password = False
    from accfino_core.security import iam as _iam
    _cur = (getattr(http_request.state, "auth", None) or {})
    _iam.revoke_sessions(db, user.id, except_sid=_cur.get("sid") if _cur.get("user_id") == user.id else None,
                         reason="password_changed")
    _iam.forget(("acct", user.id))
    db.commit()
    T.forget_token_version(user.id)
    audit.write("auth.password_changed", user_id=user.id, username=user.username)
    from accfino_core.security.mfa_service import has_mfa as _has_mfa
    fields = token_fields(db, user, mfa_verified=bool(_auth.get('mfa')) and _has_mfa(db, sec),
                          request=http_request if _auth.get('user_id') == user.id else None)
    db.commit()
    return {"ok": True, "message": "Password updated", **fields}