"""
Legacy pricing-plan endpoints (/pricing/plans, /payments/plans).
"""
import os
import sys
from pathlib import Path
from fastapi import APIRouter
from accfino.shared import paths as _paths

router = APIRouter()

import logging
logger = logging.getLogger("accfino")


from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile, Body

def _load_pricing() -> dict:
    """Load pricing -- Postgres is authoritative."""
    try:
        from accfino.shared.db.database import SessionLocal
        from accfino.core.subscription.pricing_model import PricingPlan
        db = SessionLocal()
        try:
            rows = db.query(PricingPlan).order_by(PricingPlan.sort_order).all()
            if rows:
                return {r.slug: r.to_dict() for r in rows}
        finally:
            db.close()
    except Exception:
        pass
    # Fallback to payments.py PLANS (JSON file / hardcoded, in that order)
    try:
        from accfino.core.subscription.legacy_plans import PLANS
        return PLANS
    except Exception:
        return {}

def _save_pricing(data: dict):
    """Admin - replace the full pricing config. Upserts every plan slug
    in `data` into the pricing_plans table's real columns; slugs no
    longer present in `data` are left alone (matches the old file's
    "whole document" replace semantics closely enough without deleting
    plans an admin didn't intend to touch in an unrelated partial
    payload)."""
    from accfino.shared.db.database import SessionLocal
    from accfino.core.subscription.pricing_model import PricingPlan
    db = SessionLocal()
    try:
        for i, (slug, plan) in enumerate(data.items()):
            row = db.get(PricingPlan, slug)
            if not row:
                row = PricingPlan(slug=slug, sort_order=i)
                db.add(row)
            row.name = plan.get("name")
            row.description = plan.get("description")
            row.price_monthly = plan.get("price_monthly", 0)
            row.price_yearly = plan.get("price_yearly", 0)
            row.badge = plan.get("badge")
            row.highlight = bool(plan.get("highlight", False))
            row.category = plan.get("category")
            row.features = plan.get("features", [])
            row.modules = plan.get("modules", [])
            row.price_effective_from = plan.get("price_effective_from")
        db.commit()
    finally:
        db.close()

@router.get("/payments/plans")
def payments_get_plans():
    """Alias of /pricing/plans - kept for backward compatibility."""
    return _load_pricing()

@router.get("/pricing/plans")
def pricing_get():
    """Public - return all plan definitions."""
    return _load_pricing()

@router.post("/pricing/plans")
def pricing_save(body: dict = Body(...)):
    """Admin - save full pricing config."""
    _save_pricing(body)
    return {"ok": True}

@router.patch("/pricing/plans/{plan_id}")
def pricing_update_plan(plan_id: str, body: dict = Body(...)):
    """Admin - update a single plan's pricing fields (partial update --
    only fields present in body are changed)."""
    from accfino.shared.db.database import SessionLocal
    from accfino.core.subscription.pricing_model import PricingPlan
    db = SessionLocal()
    try:
        row = db.get(PricingPlan, plan_id)
        if not row:
            raise HTTPException(404, f"Plan {plan_id!r} not found")
        for field in ("name", "description", "price_monthly", "price_yearly", "badge",
                      "highlight", "category", "features", "modules", "price_effective_from"):
            if field in body:
                setattr(row, field, body[field])
        db.commit()
        return {"ok": True, "plan": row.to_dict()}
    finally:
        db.close()

