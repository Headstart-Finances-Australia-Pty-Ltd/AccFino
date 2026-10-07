"""
Migration: create reconciliation_sessions + session_files tables.
Called from react_api.py's startup hook -- idempotent, safe to run every boot.

Does NOT migrate existing session directories under main_app/data/ -- old
sessions on disk remain readable only by the previous file-based code. New
sessions are created directly in Postgres from this point on. See
db_app/migrate_legacy_sessions.py for an optional one-time importer if you
want to bring old sessions into the new table too.
"""
import logging

logger = logging.getLogger(__name__)


def run(engine):
    from sqlalchemy import text, inspect

    insp = inspect(engine)
    dialect = engine.dialect.name

    if dialect == "postgresql":
        id_col = "id SERIAL PRIMARY KEY"
        json_col = "JSON"
    elif dialect == "sqlite":
        id_col = "id INTEGER PRIMARY KEY AUTOINCREMENT"
        json_col = "TEXT"
    else:
        id_col = "id INT AUTO_INCREMENT PRIMARY KEY"
        json_col = "JSON"

    if not insp.has_table("reconciliation_sessions"):
        with engine.begin() as conn:
            conn.execute(text(f"""
                CREATE TABLE reconciliation_sessions (
                    {id_col},
                    session_id      VARCHAR(32) NOT NULL,
                    username        VARCHAR(100) NOT NULL,
                    accounts_meta   {json_col} NOT NULL,
                    results         {json_col},
                    pending_changes {json_col} NOT NULL,
                    updated_pages   {json_col} NOT NULL,
                    page_number     INTEGER NOT NULL DEFAULT 1,
                    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_updated    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(username, session_id)
                )
            """))
            conn.execute(text(
                "CREATE INDEX idx_recon_sessions_username ON reconciliation_sessions(username)"
            ))
        logger.info("Migration: created reconciliation_sessions table")

    if not insp.has_table("session_files"):
        with engine.begin() as conn:
            conn.execute(text(f"""
                CREATE TABLE session_files (
                    {id_col},
                    session_id  INTEGER NOT NULL REFERENCES reconciliation_sessions(id) ON DELETE CASCADE,
                    filename    VARCHAR(300) NOT NULL,
                    content     BYTEA NOT NULL,
                    uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """ if dialect == "postgresql" else f"""
                CREATE TABLE session_files (
                    {id_col},
                    session_id  INTEGER NOT NULL REFERENCES reconciliation_sessions(id) ON DELETE CASCADE,
                    filename    VARCHAR(300) NOT NULL,
                    content     BLOB NOT NULL,
                    uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """))
            conn.execute(text(
                "CREATE INDEX idx_session_files_session_id ON session_files(session_id)"
            ))
        logger.info("Migration: created session_files table")
