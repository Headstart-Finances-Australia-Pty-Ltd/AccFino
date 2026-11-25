"""
Migration: create accounting_documents, accounting_line_items, accounting_suppliers tables.
Called from react_api.py startup — idempotent (skips if tables already exist).
"""
import logging
logger = logging.getLogger(__name__)


def run(engine):
    from sqlalchemy import text, inspect

    insp = inspect(engine)
    existing = insp.get_table_names()

    if "accounting_documents" in existing:
        logger.info("Migration: accounting tables already exist — skipping")
        return

    dialect = engine.dialect.name  # postgresql | sqlite

    if dialect == "postgresql":
        serial   = "SERIAL PRIMARY KEY"
        bool_def = "DEFAULT FALSE"
        json_t   = "JSONB"
    else:
        serial   = "INTEGER PRIMARY KEY AUTOINCREMENT"
        bool_def = "DEFAULT 0"
        json_t   = "TEXT"

    with engine.begin() as conn:
        conn.execute(text(f"""
            CREATE TABLE accounting_documents (
                id               {serial},
                user_id          INTEGER REFERENCES users(id) ON DELETE SET NULL,
                document_type    VARCHAR(20)  NOT NULL,
                document_number  VARCHAR(80),
                status           VARCHAR(30)  DEFAULT 'draft',
                document_date    TIMESTAMP,
                due_date         TIMESTAMP,
                paid_date        TIMESTAMP,
                party_name       VARCHAR(255),
                party_email      VARCHAR(255),
                party_phone      VARCHAR(50),
                party_address    TEXT,
                party_abn        VARCHAR(20),
                business_name    VARCHAR(255),
                business_id      INTEGER REFERENCES business_details(id) ON DELETE SET NULL,
                subtotal         FLOAT DEFAULT 0,
                tax_percent      FLOAT DEFAULT 10,
                tax_amount       FLOAT DEFAULT 0,
                discount_amount  FLOAT DEFAULT 0,
                total_amount     FLOAT DEFAULT 0,
                currency         VARCHAR(10) DEFAULT 'AUD',
                gl_account       VARCHAR(200),
                gst_category     VARCHAR(100),
                reconciled       BOOLEAN {bool_def},
                reconcile_txn_id INTEGER,
                notes            TEXT,
                payment_terms    VARCHAR(255),
                source_file      VARCHAR(500),
                source_text      TEXT,
                extracted_data   {json_t},
                created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))

        conn.execute(text(f"""
            CREATE TABLE accounting_line_items (
                id           {serial},
                document_id  INTEGER NOT NULL REFERENCES accounting_documents(id) ON DELETE CASCADE,
                sort_order   INTEGER DEFAULT 0,
                description  VARCHAR(500) NOT NULL,
                quantity     FLOAT NOT NULL DEFAULT 1,
                unit_price   FLOAT NOT NULL DEFAULT 0,
                line_total   FLOAT NOT NULL DEFAULT 0,
                gl_account   VARCHAR(200),
                gst_category VARCHAR(100),
                created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))

        conn.execute(text(f"""
            CREATE TABLE accounting_suppliers (
                id           {serial},
                user_id      INTEGER REFERENCES users(id) ON DELETE SET NULL,
                name         VARCHAR(255) NOT NULL,
                email        VARCHAR(255),
                phone        VARCHAR(50),
                address      TEXT,
                abn          VARCHAR(20),
                website      VARCHAR(255),
                gl_account   VARCHAR(200),
                gst_category VARCHAR(100),
                is_active    BOOLEAN {bool_def},
                created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))

        # Indexes for common queries
        conn.execute(text("CREATE INDEX idx_accdoc_user    ON accounting_documents(user_id)"))
        conn.execute(text("CREATE INDEX idx_accdoc_type    ON accounting_documents(document_type)"))
        conn.execute(text("CREATE INDEX idx_accdoc_status  ON accounting_documents(status)"))
        conn.execute(text("CREATE INDEX idx_accli_doc      ON accounting_line_items(document_id)"))
        conn.execute(text("CREATE INDEX idx_accsup_user    ON accounting_suppliers(user_id)"))

    # accounting_customers (idempotent)
    if not insp.has_table("accounting_customers"):
        with engine.begin() as conn2:
            conn2.execute(text(f"""
                CREATE TABLE accounting_customers (
                    id           SERIAL PRIMARY KEY,
                    user_id      INTEGER REFERENCES users(id) ON DELETE SET NULL,
                    name         VARCHAR(255) NOT NULL,
                    email        VARCHAR(255),
                    phone        VARCHAR(50),
                    address      TEXT,
                    city         VARCHAR(100),
                    state        VARCHAR(20),
                    postcode     VARCHAR(10),
                    abn          VARCHAR(20),
                    website      VARCHAR(255),
                    contact_name VARCHAR(255),
                    notes        TEXT,
                    gl_account   VARCHAR(200),
                    gst_category VARCHAR(100),
                    is_active    BOOLEAN DEFAULT FALSE,
                    created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """))
            conn2.execute(text("CREATE INDEX idx_accust_user ON accounting_customers(user_id)"))

    logger.info("Migration: created accounting_documents, accounting_line_items, accounting_suppliers, accounting_customers")
