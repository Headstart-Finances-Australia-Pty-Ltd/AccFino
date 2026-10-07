"""Regenerates the machine-derived Payroll reference pages from the live code, so they cannot drift:
    02-database-model.md   from the SQLAlchemy models
    03-api-reference.md    from the FastAPI router
    04-roles-and-permissions.md   from accfino.modules.payroll.access
Run from AccFino/backend:   PYTHONPATH=. DATABASE_URL=postgresql://x:y@localhost/none JWT_SECRET=<64 chars> python ../docs/payroll/generate_reference.py"""
import pathlib

HERE = pathlib.Path(__file__).resolve().parent


def database():
    from accfino.modules.payroll.models.payroll import PAYROLL_TABLES
    out = ["# Payroll database model", "", "_Generated from the models by `generate_reference.py`. Every table carries `org_id` (organisation scope) unless noted. Money is NUMERIC(18,2); hours NUMERIC(12,4)._", "",
           f"**{len(PAYROLL_TABLES)} tables.** Legacy tables (`payroll_employees`, `payroll_runs`, `payroll_timesheets`, `payslips`, `stp_submissions`) are left in place, unused, so a rollback loses nothing.", ""]
    for t in sorted(PAYROLL_TABLES, key=lambda t: t.name):
        out += [f"## `{t.name}`", "", "| Column | Type | Notes |", "|---|---|---|"]
        for c in t.columns:
            notes = []
            if c.primary_key: notes.append("PK")
            if not c.nullable and not c.primary_key: notes.append("required")
            for fk in c.foreign_keys:
                od = fk.ondelete or "NO ACTION"
                notes.append(f"FK -> {fk.target_fullname} ({od})")
            if c.name in ("tfn_enc", "account_enc"): notes.append("**sealed (encrypted) at rest**")
            out.append(f"| `{c.name}` | {str(c.type)} | {', '.join(notes)} |")
        cons = [str(x.name) for x in t.constraints if x.name and x.__class__.__name__ in ("UniqueConstraint", "CheckConstraint")]
        idx = [f"`{i.name}`{' (unique' + (', partial' if i.dialect_options['postgresql'].get('where') is not None else '') + ')' if i.unique else ''}" for i in t.indexes]
        if cons: out += ["", "Constraints: " + ", ".join(f"`{c}`" for c in cons)]
        if idx: out += ["", "Indexes: " + ", ".join(idx)]
        out.append("")
    (HERE / "02-database-model.md").write_text("\n".join(out))


def api():
    from accfino.modules.payroll.api import router
    rows = []
    for r in router.routes:
        for m in sorted(r.methods - {"HEAD", "OPTIONS"}):
            rows.append((r.path, m, (r.endpoint.__doc__ or "").strip().split("\n")[0] if r.endpoint.__doc__ else r.name))
    out = ["# Payroll API reference", "", "_Generated from the router by `generate_reference.py`. All routes are mounted under `/payroll` (the SPA proxy adds `/api`). Every call needs a bearer token and the `X-Org-Id` header; every call is re-authorised on the server._", "",
           "Conventions: errors are `{\"detail\": \"message\"}` with 401 (not signed in), 403 (role cannot do this), 404 (missing, or not in your organisation / not yours), 409 (invalid state, duplicate or already done), 422 (validation). **No field is ever called `user_id` or `username`**: the platform's AuthGuard treats those names as \"the caller\", so the employee<->login link is `login_user_id`.", "",
           f"**{len(rows)} endpoints.**", "", "| Method | Path | Notes |", "|---|---|---|"]
    for path, m, note in sorted(rows, key=lambda x: (x[0], x[1])):
        out.append(f"| {m} | `/payroll{path}` | {note} |")
    (HERE / "03-api-reference.md").write_text("\n".join(out) + "\n")


def roles():
    from accfino.modules.payroll import access as A
    caps = sorted(A.ALL)
    roles_ = [("owner", "Organisation Administrator"), ("payroll_admin", "Payroll Administrator"), ("payroll", "Payroll Manager"), ("accountant", "Accountant"), ("admin", "Legacy 'admin'")]
    out = ["# Payroll roles and permissions", "", "_Generated from `accfino/modules/payroll/access.py` by `generate_reference.py`._", "",
           "Payroll uses the platform's organisation roles - there is no second login or role store. Two roles were added to Core for Phase 2: `payroll_admin` and `employee` (no ledger access at all).", "",
           "| Capability | " + " | ".join(n for _, n in roles_) + " |", "|---|" + "---|" * len(roles_)]
    for c in caps:
        out.append(f"| {c.replace('_', ' ')} | " + " | ".join("✓" if c in A.ROLE_CAPS[r] else "" for r, _ in roles_) + " |")
    out += ["", "**Employee / Manager are not roles you assign for payroll:**", "",
            "- **Employee**: anyone whose login is linked to an employee record (`login_user_id`). They can see only their own payslips, leave, timesheets and details. The platform role `employee` gives such a person *no* access to the books.",
            "- **Manager**: derived. A user whose linked employee has direct reports can approve those reports' timesheets and leave and see their names and leave. No salary, tax or bank access.",
            "- **Nobody approves their own timesheet or leave**, including payroll administrators.",
            "- `bookkeeper` and `readonly` have no payroll access unless they are also linked to an employee (then: self-service only).", "",
            "What each sees of sensitive data:", "",
            "| Data | Org Admin / Payroll Admin | Payroll Manager | Accountant | Manager | Employee |", "|---|---|---|---|---|---|",
            "| Salary / pay rate | yes | yes | yes | no | own |", "| Tax details (masked TFN) | yes | yes | yes | no | own |", "| Full TFN | Payroll Admin / Org Admin only (audited each time) | no | no | no | no |",
            "| Bank details (account masked) | yes | yes | no | no | own |", "| Full bank account number | never returned by any API | never | never | never | never |", "| Audit trail | yes | no | yes | no | no |"]
    (HERE / "04-roles-and-permissions.md").write_text("\n".join(out) + "\n")


if __name__ == "__main__":
    database(); api(); roles()
    print("written:", sorted(p.name for p in HERE.glob("0*.md")))
