"""
accfino_core.force_delete
-------------------------
Deleting users and organisations from the Admin Console.

  delete_user(db, user_id)            remove one user and everything that belongs to them
  delete_organisation(db, org_id)     remove one organisation, ALL of its data, and every user who belongs ONLY to that organisation
                                      ("if an organisation is deleted, all of its users are deleted automatically")

Two strengths:
  normal  refuses (409) when removing would destroy accounting records (an organisation that has posted journals)
  force   removes everything, including the ledger. Posted journals and their lines are protected by database triggers
          ("immutable record"); a force delete lifts those two triggers INSIDE ONE TRANSACTION and puts them back before it commits,
          so the protection is never off for anyone else. The audit log is never touched (it is append-only) and records who did it.

Never deleted, in either strength: the platform administrator (admin role / ADMIN_EMAIL) and the person doing the deleting.
"""
import logging
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from accfino_core import models as m
from accfino_core.security import contact as C

log = logging.getLogger("accfino.force_delete")
FORCE_DELETE_KEY = "platform.force_delete"
_PROTECTED_TRIGGER_TABLES = ("journal_lines", "journals")        # immutable-record triggers (see migrate.TRIGGERS_SQL)
_NEVER_PURGE = {"organisations", "audit_log"}                      # audit history is append-only and outlives the organisation


# ------------------------------------------------------------------------------------------------ the switch --
def force_delete_enabled(db: Session) -> bool:
    """Admin > Modules Management > 'Force delete'. OFF until an administrator ticks it."""
    row = db.get(m.SystemSetting, FORCE_DELETE_KEY)
    return bool(row and (row.value or "").strip().lower() == "on")


def set_force_delete(db: Session, enabled: bool) -> None:
    row = db.get(m.SystemSetting, FORCE_DELETE_KEY)
    if row is None:
        db.add(m.SystemSetting(key=FORCE_DELETE_KEY, value="on" if enabled else "off"))
    else:
        row.value = "on" if enabled else "off"
    db.flush()


def require_force_enabled(db: Session) -> None:
    if not force_delete_enabled(db):
        raise HTTPException(403, "Force delete is switched off. Tick 'Force delete' under Admin > Modules Management > Platform features first.")


# ------------------------------------------------------------------------------------------------ helpers --
def is_protected_user(user) -> bool:
    return user.has_role("admin") or C.is_platform_admin_email(user.email) or (user.username or "").lower() == "admin"


def _is_pg(db: Session) -> bool:
    return db.get_bind().dialect.name == "postgresql"


def _org_tables(db: Session) -> list:
    insp = inspect(db.get_bind())
    out = []
    for t in insp.get_table_names():
        if t in _NEVER_PURGE:
            continue
        if any(c["name"] == "org_id" for c in insp.get_columns(t)):
            out.append(t)
    return out


def _detach_user_references(db: Session, user_id: int) -> None:
    """FORCE only: any table that points at users.id WITHOUT 'ON DELETE CASCADE / SET NULL' would block the delete. Clear those links first
    (set the column to NULL when it allows it, otherwise delete the row)."""
    insp = inspect(db.get_bind())
    for t in insp.get_table_names():
        cols = {c["name"]: c for c in insp.get_columns(t)}
        for fk in insp.get_foreign_keys(t):
            if fk.get("referred_table") != "users":
                continue
            ond = ((fk.get("options") or {}).get("ondelete") or "").upper()
            if ond in ("CASCADE", "SET NULL"):
                continue
            for col in fk.get("constrained_columns", []):
                with db.begin_nested():
                    if cols[col].get("nullable", True):
                        db.execute(text(f'UPDATE "{t}" SET "{col}" = NULL WHERE "{col}" = :u'), {"u": user_id})
                    else:
                        db.execute(text(f'DELETE FROM "{t}" WHERE "{col}" = :u'), {"u": user_id})


def _q(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _clear_cascade_blockers(db: Session, user_id: int) -> None:
    """FORCE only (PostgreSQL). Deleting a user cascades to its dependants (licence, sessions, memberships, transactions ...). On a database built by an
    older release one of THOSE rows can itself be referenced by a table with no 'ON DELETE' rule - and that blocks the user delete even though no table
    points at users directly. Clear those references first (set NULL where allowed, otherwise delete the referencing row)."""
    if not _is_pg(db):
        return
    try:
        fks = db.execute(text("""
            SELECT k.conrelid::regclass::text AS child, ca.attname AS ccol, ca.attnotnull AS cnn, k.confrelid::regclass::text AS parent, pa.attname AS pcol, k.confdeltype::text AS del
            FROM pg_constraint k
            JOIN pg_attribute ca ON ca.attrelid = k.conrelid AND ca.attnum = k.conkey[1]
            JOIN pg_attribute pa ON pa.attrelid = k.confrelid AND pa.attnum = k.confkey[1]
            WHERE k.contype = 'f' AND array_length(k.conkey, 1) = 1""")).fetchall()
        pks = {r[0]: r[1] for r in db.execute(text("""
            SELECT i.indrelid::regclass::text, a.attname FROM pg_index i JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = i.indkey[0]
            WHERE i.indisprimary AND i.indnatts = 1""")).fetchall()}
    except SQLAlchemyError as e:
        log.warning("force delete: could not read foreign keys (%s)", e)
        return
    # every table that a delete of this user reaches through ON DELETE CASCADE, with a query that selects the primary keys of the rows that will go
    doomed = {"users": f"SELECT id FROM users WHERE id = {int(user_id)}"}
    changed = True
    while changed:
        changed = False
        for child, ccol, _nn, parent, pcol, rule in fks:
            if rule == "c" and parent in doomed and child not in doomed and child in pks and parent in pks:
                doomed[child] = (f"SELECT {_q(pks[child])} FROM {_q(child)} WHERE {_q(ccol)} IN "
                                 f"(SELECT {_q(pcol)} FROM {_q(parent)} WHERE {_q(pks[parent])} IN ({doomed[parent]}))")
                changed = True
    for child, ccol, notnull, parent, pcol, rule in fks:
        if parent not in doomed or parent == "users" or rule not in ("a", "r") or child in doomed:
            continue
        victims = f"{_q(ccol)} IN (SELECT {_q(pcol)} FROM {_q(parent)} WHERE {_q(pks[parent])} IN ({doomed[parent]}))"
        try:
            with db.begin_nested():
                if notnull:
                    db.execute(text(f"DELETE FROM {_q(child)} WHERE {victims}"))
                else:
                    db.execute(text(f"UPDATE {_q(child)} SET {_q(ccol)} = NULL WHERE {victims}"))
        except SQLAlchemyError as e:
            log.warning("force delete: could not clear %s.%s -> %s (%s)", child, ccol, parent, str(e).splitlines()[0])


def _why(e: Exception) -> str:
    orig = getattr(e, "orig", None) or e
    return (str(orig).strip().splitlines() or [type(orig).__name__])[0][:300]


def _remove_user_row(db: Session, user, force: bool) -> None:
    uid, uname = user.id, user.username
    if force:
        _detach_user_references(db, uid)
        _clear_cascade_blockers(db, uid)
    try:
        with db.begin_nested():
            db.execute(text("DELETE FROM users WHERE id = :u"), {"u": uid})     # the database cascades roles, licence, sessions, memberships, transactions ...
    except IntegrityError as e:
        log.warning("user %s (#%s) could not be deleted (force=%s): %s", uname, uid, force, _why(e))
        if force:                                  # say what is really in the way - "use Force delete" would be wrong advice here
            raise HTTPException(409, f"User '{uname}' could not be deleted: {_why(e)}")
        raise HTTPException(409, f"User '{uname}' still has linked records. Use Force delete to remove them together.")
    except SQLAlchemyError as e:
        log.exception("user %s (#%s) delete failed", uname, uid)
        raise HTTPException(500, f"User '{uname}' could not be deleted: {_why(e)}")
    db.expire_all()
    try:
        from accfino_core.security import iam
        iam.forget(("contact", uid))
    except Exception:
        pass


# ------------------------------------------------------------------------------------------------ users --
def delete_user(db: Session, user_id: int, *, actor_id: Optional[int] = None, force: bool = False) -> dict:
    from db_app.models.user import User
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(404, "User not found")
    if is_protected_user(user):
        raise HTTPException(409, "The platform administrator account cannot be deleted.")
    if actor_id is not None and user.id == actor_id:
        raise HTTPException(409, "You cannot delete the account you are signed in with.")
    info = {"id": user.id, "username": user.username, "email": user.email}
    org_ids = [r[0] for r in db.query(m.OrgMembership.org_id).filter(m.OrgMembership.user_id == user.id).all()]
    _remove_user_row(db, user, force)
    # an organisation that just lost its Organisation Admin gets a new one (an active member is promoted) so it is never left ownerless
    try:
        from accfino_core import org_admin as OA
        with db.begin_nested():                    # a failure here rolls back to this point only - the user delete itself stays valid
            OA.sync_org_admins(db)
    except Exception as e:
        log.warning("organisation admin re-sync after deleting user #%s failed: %s", info["id"], e)
    # an organisation whose LAST user was just deleted is an unreachable orphan: remove it too, so it does not linger in the lists
    if org_ids:
        info["orgs_removed"] = prune_empty_orgs(db, org_ids, force=force)["removed"]
    return info


# ------------------------------------------------------------------------------------------------ organisations --
def _purge_org_rows(db: Session, org_id: int) -> None:
    """Delete every row that carries this organisation's id, in whatever order the foreign keys allow."""
    pending = _org_tables(db)
    while pending:
        failed = []
        for t in pending:
            try:
                with db.begin_nested():
                    db.execute(text(f'DELETE FROM "{t}" WHERE org_id = :o'), {"o": org_id})
            except SQLAlchemyError:
                failed.append(t)
        if len(failed) == len(pending):          # no progress: the final DELETE of the organisation reports what is left
            break
        pending = failed


def delete_organisation(db: Session, org_id: int, *, actor_id: Optional[int] = None, force: bool = False) -> dict:
    from db_app.models.user import User
    org = db.get(m.Organisation, org_id)
    if org is None:
        raise HTTPException(404, "Organisation not found")
    name = org.name
    member_ids = [r[0] for r in db.query(m.OrgMembership.user_id).filter(m.OrgMembership.org_id == org_id).all()]
    if actor_id is not None and actor_id in member_ids:
        # deleting your own organisation would delete you: refuse rather than log the administrator out of the console
        me = db.get(User, actor_id)
        if me is not None and not is_protected_user(me):
            raise HTTPException(409, "You cannot delete the organisation you belong to.")

    journals = db.execute(text("SELECT COUNT(*) FROM journals WHERE org_id = :o"), {"o": org_id}).scalar() or 0
    if journals and not force:
        raise HTTPException(409, f"'{name}' has {journals} posted journal(s). Posted accounting records are protected; use Force delete to remove the organisation with all of its data.")

    # users who belong ONLY to this organisation go with it (people who also belong to another organisation stay)
    doomed = []
    for uid in member_ids:
        user = db.get(User, uid)
        if user is None or is_protected_user(user) or (actor_id is not None and uid == actor_id):
            continue
        other = db.query(m.OrgMembership.id).filter(m.OrgMembership.user_id == uid, m.OrgMembership.org_id != org_id).first()
        if other is None:
            doomed.append(user)

    pg = _is_pg(db)
    locked = []
    try:
        if pg and force:
            for t in _PROTECTED_TRIGGER_TABLES:
                db.execute(text(f'ALTER TABLE "{t}" DISABLE TRIGGER USER'))
                locked.append(t)
        _purge_org_rows(db, org_id)
        try:
            with db.begin_nested():
                db.execute(text("DELETE FROM organisations WHERE id = :o"), {"o": org_id})
        except IntegrityError as e:
            raise HTTPException(409, f"'{name}' could not be deleted because other records still depend on it: {str(e.orig).splitlines()[0] if getattr(e, 'orig', None) else e}")
        deleted_users = []
        for user in doomed:
            deleted_users.append({"id": user.id, "username": user.username, "email": user.email})
            _remove_user_row(db, user, force=True)
    finally:
        if pg:
            for t in locked:                                   # always put the protection back (inside the same transaction)
                try:
                    db.execute(text(f'ALTER TABLE "{t}" ENABLE TRIGGER USER'))
                except SQLAlchemyError:
                    pass                                       # the transaction is being rolled back, which restores the triggers too
    db.expire_all()
    return {"id": org_id, "name": name, "users_deleted": deleted_users, "journals_removed": journals if force else 0}


def prune_empty_orgs(db: Session, org_ids: Optional[list] = None, *, force: bool = False) -> dict:
    """Delete organisations that have NO users left (all of them, or just org_ids). Without force an organisation holding posted journals is kept
    (posted accounting records are protected) and reported under 'skipped'. -> {"removed": [{id, name}], "skipped": [{id, name, reason}]}"""
    q = db.query(m.Organisation)
    if org_ids is not None:
        q = q.filter(m.Organisation.id.in_(list(org_ids)))
    removed, skipped = [], []
    for org in q.all():
        if db.query(m.OrgMembership.id).filter(m.OrgMembership.org_id == org.id).first() is not None:
            continue                                                       # still has people: not empty
        oid, name = org.id, org.name
        try:
            with db.begin_nested():
                delete_organisation(db, oid, actor_id=None, force=force)
            removed.append({"id": oid, "name": name})
        except HTTPException as e:
            skipped.append({"id": oid, "name": name, "reason": str(e.detail)})
        except SQLAlchemyError as e:
            log.warning("could not remove empty organisation #%s: %s", oid, _why(e))
            skipped.append({"id": oid, "name": name, "reason": _why(e)})
    db.expire_all()
    return {"removed": removed, "skipped": skipped}
