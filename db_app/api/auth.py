from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from sqlalchemy import or_
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

    return UserResponse(
        id=user.id,
        username=user.username,
        name=user.full_name or user.username,
        email=user.email,
        roles=roles,
        permissions=permissions,
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
def authenticate_user(email: str, password: str, db: Session) -> UserResponse:
    ensure_users_full_name_column(db)

    # Keep request schema stable but allow email or username in this field.
    login_value = email.strip()
    user = (
        db.query(User)
        .filter(or_(User.email == login_value, User.username == login_value))
        .first()
    )

    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")
    
    if not bcrypt.checkpw(password.encode(), user.password.encode()):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")
    
    return build_user_response(user)


@router.post("/login", response_model=UserResponse)
def login_post(
    request: LoginRequest = Body(...),
    db: Session = Depends(get_db),
):
    if request is not None:
        return authenticate_user(request.email, request.password, db)

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
    return authenticate_user(email, password, db)

@router.post("/register", response_model=UserResponse)
def register(
    request: RegisterRequest = Body(...),
    db: Session = Depends(get_db),
):
    ensure_users_full_name_column(db)

    if db.query(User).filter(User.email == request.email).first():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email already registered")
    if db.query(User).filter(User.username == request.username).first():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Username already taken")

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
        pass  # Don't fail registration if licence creation fails

    return build_user_response(new_user)