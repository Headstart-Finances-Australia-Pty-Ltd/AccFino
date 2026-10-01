"""Load companies from companies.json and seed the database."""
import json, os

def seed_companies(db) -> int:
    from db_app.models.company import Company, CompanyAlias
    json_path = os.path.join(os.path.dirname(__file__), "companies.json")
    if not os.path.exists(json_path):
        return 0
    data = json.load(open(json_path, encoding="utf-8"))
    inserted = 0
    for row in data:
        name = row.get("name","").strip()
        if not name:
            continue
        existing = db.query(Company).filter(Company.name == name).first()
        if existing:
            # Add any missing aliases
            existing_aliases = {a.alias for a in existing.aliases}
            for alias in (row.get("aliases") or []):
                al = alias.strip().lower()
                if al and al not in existing_aliases:
                    existing_aliases.add(al)
                    try:
                        db.add(CompanyAlias(company_id=existing.id, alias=al))
                        db.flush()
                    except Exception:
                        db.rollback()
            continue
        try:
            company = Company(
                name=name,
                short_name=row.get("short_name",""),
                category=row.get("category",""),
                subcategory=row.get("subcategory",""),
                country=row.get("country","AU"),
                abn=row.get("abn",""),
                is_government=bool(row.get("is_government",False)),
                approved=True,
            )
            db.add(company)
            db.flush()
            seen: set = set()
            for alias in (row.get("aliases") or []):
                al = alias.strip().lower()
                if al and al not in seen and len(al) >= 2:
                    seen.add(al)
                    db.add(CompanyAlias(company_id=company.id, alias=al))
            db.flush()
            db.commit()
            inserted += 1
        except Exception:
            db.rollback()
    return inserted
