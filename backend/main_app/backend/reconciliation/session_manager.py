# backend/reconciliation/session_manager.py
"""
Postgres-backed session manager -- replaces the old per-user, per-session
directory structure (accounts.json, results.pkl, session_state.json, and
raw uploaded files on disk) with the reconciliation_sessions and
session_files tables (db_app/models/reconciliation_session.py).

Every public method keeps the EXACT same name and signature as the old
filesystem-based version, so no caller in react_api.py needs to change --
this is a drop-in replacement of the internals only.
"""
import json
from datetime import datetime
from typing import Dict, List, Optional

import pandas as pd

from db_app.database import SessionLocal
from db_app.models.reconciliation_session import ReconciliationSession, SessionFile


def _df_to_json_records(df: pd.DataFrame) -> list:
    """Safely converts a DataFrame to a list of JSON-plain dicts, handling
    NaN -> null and numpy dtypes correctly (a plain .to_dict("records")
    leaves NaN/numpy types in place, which are not valid JSON)."""
    if df is None or df.empty:
        return []
    return json.loads(df.to_json(orient="records"))


class SessionManager:
    """Manages reconciliation sessions -- now Postgres-backed."""

    def _find_session_row(self, db, username: str, session_id: str) -> Optional[ReconciliationSession]:
        return (
            db.query(ReconciliationSession)
            .filter(ReconciliationSession.username == username, ReconciliationSession.session_id == session_id)
            .first()
        )

    def create_session(self, username: str) -> str:
        """Creates a new session row. Returns session_id (timestamp string),
        same format as before ("%Y%m%d_%H%M%S")."""
        session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        db = SessionLocal()
        try:
            row = ReconciliationSession(
                session_id=session_id,
                username=username,
                accounts_meta=[],
                results=None,
                pending_changes={},
                updated_pages=[],
                page_number=1,
            )
            db.add(row)
            db.commit()
        finally:
            db.close()
        return session_id

    def get_session_dir(self, username: str, session_id: str):
        """Legacy no-op kept only so any stray external caller doesn't hard
        crash on import -- sessions no longer live on disk. Returns None.
        Callers should use save_input_meta_and_files / get_session_summary
        instead of touching a directory directly."""
        return None

    def save_input_data(self, username: str, session_id: str, accounts: List[Dict], uploaded_files_data: Dict):
        """Saves input data (accounts + uploaded files) for a session.
        `accounts` items are expected to have "bank_name", "account_number",
        and "files" (list of objects with a .name attribute), matching the
        original filesystem version's contract."""
        accounts_meta = []
        for acc in accounts:
            accounts_meta.append({
                "bank_name": acc["bank_name"],
                "account_number": acc["account_number"],
                "files": [f.name for f in acc["files"]],
            })
        self.save_input_meta_and_files(username, session_id, accounts_meta, uploaded_files_data)

    def save_input_meta_and_files(self, username: str, session_id: str, accounts_meta: List[Dict], uploaded_files_data: Dict):
        """Saves already-built accounts_meta plus raw uploaded file bytes.
        Used directly by react_api.py's classify/reconcile endpoints (which
        previously wrote straight to session_dir/input/, bypassing this
        class entirely -- now routed through here instead)."""
        db = SessionLocal()
        try:
            row = self._find_session_row(db, username, session_id)
            if not row:
                return
            row.accounts_meta = accounts_meta
            row.last_updated = datetime.utcnow()

            # Replace any existing files with the same name for this session
            # (mirrors the old behaviour of overwriting a file at the same path).
            if uploaded_files_data:
                existing = {f.filename: f for f in row.files}
                for fname, raw in uploaded_files_data.items():
                    if fname in existing:
                        existing[fname].content = raw
                        existing[fname].uploaded_at = datetime.utcnow()
                    else:
                        db.add(SessionFile(session_id=row.id, filename=fname, content=raw))
            db.commit()
        finally:
            db.close()

    def save_output_data(self, username: str, session_id: str,
                          df_results: pd.DataFrame,
                          pending_changes: Dict,
                          updated_pages: set,
                          page_number: int):
        """Saves the results table + session state. Replaces results.pkl +
        session_state.json with JSON columns on the session row."""
        df_to_save = df_results.copy() if df_results is not None else pd.DataFrame()
        if "DB ID" in df_to_save.columns:
            df_to_save = df_to_save.drop(columns=["DB ID"])

        db = SessionLocal()
        try:
            row = self._find_session_row(db, username, session_id)
            if not row:
                return
            row.results = _df_to_json_records(df_to_save)
            row.pending_changes = {str(k): v for k, v in pending_changes.items()}
            row.updated_pages = list(updated_pages)
            row.page_number = page_number
            row.last_updated = datetime.utcnow()
            db.commit()
        finally:
            db.close()

    def save_pending_changes_only(self, username: str, session_id: str,
                                   pending_changes: Dict, updated_pages: set,
                                   page_number: int):
        """Quick save of just pending changes without touching results --
        same as before, just against the DB row instead of session_state.json."""
        db = SessionLocal()
        try:
            row = self._find_session_row(db, username, session_id)
            if not row:
                return
            row.pending_changes = {str(k): v for k, v in pending_changes.items()}
            row.updated_pages = list(updated_pages)
            row.page_number = page_number
            row.last_updated = datetime.utcnow()
            db.commit()
        finally:
            db.close()

    def load_session_data(self, username: str, session_id: str) -> Optional[Dict]:
        """Loads complete session data (input + output). Returns the same
        dict shape as the old filesystem version."""
        db = SessionLocal()
        try:
            row = self._find_session_row(db, username, session_id)
            if not row:
                return None

            files_data = {f.filename: f.content for f in row.files}
            results_df = pd.DataFrame(row.results) if row.results else None
            if results_df is not None and "DB ID" in results_df.columns:
                results_df = results_df.drop(columns=["DB ID"])

            return {
                "session_id": session_id,
                "accounts": row.accounts_meta or [],
                "files_data": files_data,
                "results": results_df,
                "pending_changes": {int(k): v for k, v in (row.pending_changes or {}).items()},
                "updated_pages": set(row.updated_pages or []),
                "page_number": row.page_number or 1,
            }
        finally:
            db.close()

    def get_session_summary(self, username: str, session_id: str) -> Dict:
        """Returns accounts_meta/account_count/file_count for a session --
        used by the /sessions list endpoint. Replaces the old disk-repair
        logic that re-derived this from accounts.json + files_dir.iterdir(),
        since accounts_meta and the file list are now always kept in sync
        in the same DB row/relationship -- there's nothing to repair."""
        db = SessionLocal()
        try:
            row = self._find_session_row(db, username, session_id)
            if not row:
                return {"accounts_meta": [], "account_count": 0, "file_count": 0}
            accounts_meta = row.accounts_meta or []
            file_count = db.query(SessionFile).filter(SessionFile.session_id == row.id).count()
            return {
                "accounts_meta": accounts_meta,
                "account_count": len(accounts_meta),
                "file_count": file_count,
            }
        finally:
            db.close()

    def get_all_sessions(self, username: str) -> List[Dict]:
        """List of all sessions for a user, newest first."""
        db = SessionLocal()
        try:
            rows = (
                db.query(ReconciliationSession)
                .filter(ReconciliationSession.username == username)
                .order_by(ReconciliationSession.created_at.desc())
                .all()
            )
            sessions = []
            for row in rows:
                try:
                    dt = datetime.strptime(row.session_id, "%Y%m%d_%H%M%S")
                except Exception:
                    dt = row.created_at or datetime.utcnow()
                sessions.append({
                    "session_id": row.session_id,
                    "datetime": dt,
                    "display_name": dt.strftime("%Y-%m-%d %H:%M:%S"),
                    "has_results": bool(row.results),
                    "last_updated": row.last_updated.isoformat() if row.last_updated else None,
                })
            return sessions
        finally:
            db.close()

    def get_latest_session(self, username: str) -> Optional[str]:
        sessions = self.get_all_sessions(username)
        return sessions[0]["session_id"] if sessions else None

    def delete_session(self, username: str, session_id: str) -> bool:
        db = SessionLocal()
        try:
            row = self._find_session_row(db, username, session_id)
            if not row:
                return False
            db.delete(row)  # cascades to session_files via the relationship
            db.commit()
            return True
        except Exception as e:
            print(f"Error deleting session: {e}")
            return False
        finally:
            db.close()


# Global instance -- same name as before so `from ...session_manager import session_manager` still works.
session_manager = SessionManager()
