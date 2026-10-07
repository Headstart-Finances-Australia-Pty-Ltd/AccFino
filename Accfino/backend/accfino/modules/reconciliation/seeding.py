"""One-time seeding for Reconciliation (moved out of the platform init_db)."""


def seed_companies_safe(SessionLocal):
    """Seed the company directory - skips if already seeded."""
    try:
        from accfino.modules.reconciliation.models.company import Company
        db2 = SessionLocal()
        count = db2.query(Company).count()
        if count > 0:
            print(f"Company DB: {count} companies already in DB, skipping seed.")
            db2.close()
            return
        from accfino.modules.reconciliation.services.company_seed import seed_companies
        n = seed_companies(db2)
        print(f"Company DB: {n} new companies seeded.")
        db2.close()
    except Exception as e:
        print(f"Warning: company seed failed (non-fatal): {e}")
