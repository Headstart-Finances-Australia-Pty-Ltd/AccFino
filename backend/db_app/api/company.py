"""
db_app/api/company.py
-----------------------------------------------------------------------------
REST API endpoints for the Company database.

Routes (all prefixed /company in react_api.py):
  GET  /company/search?q=...          Search companies by name/alias
  GET  /company/list                  List all companies (admin)
  POST /company                       Add a new company (admin)
  PUT  /company/{id}                  Update a company (admin)
  DELETE /company/{id}                Delete a company (admin)
  POST /company/{id}/alias            Add alias to a company
  DELETE /company/{id}/alias/{alias}  Remove alias
  POST /company/approve/{id}          Approve a pending company
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import List, Optional
from db_app.database import SessionLocal
from db_app.models.company import Company, CompanyAlias

router = APIRouter()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# -- Pydantic schemas -------------------------------------------------------

from pydantic import field_validator

class AliasOut(BaseModel):
    id:       int
    alias:    str
    priority: int = 0
    @field_validator('priority', mode='before')
    @classmethod
    def coerce_priority(cls, v):
        return v if v is not None else 0

    class Config:
        from_attributes = True


class CompanyOut(BaseModel):
    id:           int
    name:         str
    short_name:   Optional[str]
    category:     str
    subcategory:  Optional[str]
    country:      str
    abn:          Optional[str]
    is_government:bool
    approved:     bool
    aliases:      List[AliasOut] = []
    class Config: from_attributes = True


class CompanyIn(BaseModel):
    name:          str
    short_name:    Optional[str]  = None
    category:      str            = "Other"
    subcategory:   Optional[str]  = None
    country:       str            = "AU"
    abn:           Optional[str]  = None
    is_government: bool           = False
    aliases:       List[str]      = []


class AliasIn(BaseModel):
    alias:    str
    priority: int = 0


# -- Endpoints -------------------------------------------------------------

@router.get("/search", response_model=List[CompanyOut])
def search_companies(
    q: str = Query(..., min_length=1),
    limit: int = Query(1000, le=1000),
    db: Session = Depends(get_db),
):
    """Search companies by name or alias (substring, case-insensitive)."""
    q_lower = q.strip().lower()
    # First: name matches
    name_matches = (
        db.query(Company)
        .filter(Company.name.ilike(f"%{q}%"), Company.approved == True)
        .limit(limit)
        .all()
    )
    # Also: alias matches
    alias_matches = (
        db.query(Company)
        .join(CompanyAlias, Company.id == CompanyAlias.company_id)
        .filter(CompanyAlias.alias.ilike(f"%{q_lower}%"), Company.approved == True)
        .limit(limit)
        .all()
    )
    seen = {c.id for c in name_matches}
    combined = list(name_matches) + [c for c in alias_matches if c.id not in seen]
    return combined[:limit]


@router.get("/list", response_model=List[CompanyOut])
def list_companies(
    approved: Optional[bool] = None,
    category: Optional[str]  = None,
    country:  Optional[str]  = None,
    skip:     int             = 0,
    limit:    int             = Query(1000, le=1000),
    db:       Session         = Depends(get_db),
):
    """List companies with optional filters. Admin use."""
    from sqlalchemy.orm import joinedload
    q = db.query(Company).options(joinedload(Company.aliases))
    if approved is not None:
        q = q.filter(Company.approved == approved)
    if category:
        q = q.filter(Company.category.ilike(f"%{category}%"))
    if country:
        q = q.filter(Company.country == country.upper())
    try:
        return q.order_by(Company.name).offset(skip).limit(limit).all()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)[:200]}")


@router.post("", response_model=CompanyOut, status_code=201)
def create_company(body: CompanyIn, db: Session = Depends(get_db)):
    existing = db.query(Company).filter(Company.name == body.name).first()
    if existing:
        raise HTTPException(400, f"Company '{body.name}' already exists (id={existing.id})")
    company = Company(
        name=body.name, short_name=body.short_name, category=body.category,
        subcategory=body.subcategory, country=body.country,
        abn=body.abn or "", is_government=body.is_government, approved=True,
    )
    db.add(company)
    db.flush()
    for alias in body.aliases:
        al = alias.strip().lower()
        if al:
            db.add(CompanyAlias(company_id=company.id, alias=al))
    db.commit()
    db.refresh(company)
    return company


@router.put("/{company_id}", response_model=CompanyOut)
def update_company(
    company_id: int, body: CompanyIn, db: Session = Depends(get_db)
):
    company = db.query(Company).filter(Company.id == company_id).first()
    if not company:
        raise HTTPException(404, "Company not found")
    company.name         = body.name
    company.short_name   = body.short_name
    company.category     = body.category
    company.subcategory  = body.subcategory
    company.country      = body.country
    company.abn          = body.abn or ""
    company.is_government= body.is_government
    db.commit()
    db.refresh(company)
    return company


@router.delete("/{company_id}", status_code=204)
def delete_company(company_id: int, db: Session = Depends(get_db)):
    company = db.query(Company).filter(Company.id == company_id).first()
    if not company:
        raise HTTPException(404, "Company not found")
    db.delete(company)
    db.commit()


@router.post("/{company_id}/alias", response_model=AliasOut, status_code=201)
def add_alias(
    company_id: int, body: AliasIn, db: Session = Depends(get_db)
):
    company = db.query(Company).filter(Company.id == company_id).first()
    if not company:
        raise HTTPException(404, "Company not found")
    al = body.alias.strip().lower()
    existing = db.query(CompanyAlias).filter(
        CompanyAlias.company_id == company_id,
        CompanyAlias.alias == al,
    ).first()
    if existing:
        raise HTTPException(400, f"Alias '{al}' already exists for this company")
    alias = CompanyAlias(company_id=company_id, alias=al, priority=body.priority)
    db.add(alias)
    db.commit()
    db.refresh(alias)
    return alias


@router.delete("/{company_id}/alias/{alias}", status_code=204)
def remove_alias(company_id: int, alias: str, db: Session = Depends(get_db)):
    al = db.query(CompanyAlias).filter(
        CompanyAlias.company_id == company_id,
        CompanyAlias.alias == alias.lower(),
    ).first()
    if not al:
        raise HTTPException(404, "Alias not found")
    db.delete(al)
    db.commit()


@router.post("/approve/{company_id}", response_model=CompanyOut)
def approve_company(company_id: int, db: Session = Depends(get_db)):
    """Approve a pending auto-captured company."""
    company = db.query(Company).filter(Company.id == company_id).first()
    if not company:
        raise HTTPException(404, "Company not found")
    company.approved = True
    db.commit()
    db.refresh(company)
    return company


@router.get("/categories")
def list_categories(db: Session = Depends(get_db)):
    """Return all distinct categories in the company DB."""
    rows = db.query(Company.category).distinct().order_by(Company.category).all()
    return [r[0] for r in rows if r[0]]
