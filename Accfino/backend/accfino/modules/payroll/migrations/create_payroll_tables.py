"""Migration: create payroll tables. Idempotent."""
import logging
logger = logging.getLogger(__name__)


def run(engine):
    from sqlalchemy import text, inspect
    from sqlalchemy.exc import SQLAlchemyError
    insp = inspect(engine)
    existing = insp.get_table_names()
    # Check each table individually — some may exist from a previous partial run
    tables_needed = ["payroll_employees","payroll_timesheets","payroll_runs","payslips","stp_submissions"]
    missing = [t for t in tables_needed if t not in existing]
    if not missing:
        logger.info("Migration: all payroll tables already exist — skipping")
        return
    logger.info(f"Migration: creating missing payroll tables: {missing}")

    d = engine.dialect.name
    serial  = "SERIAL PRIMARY KEY"      if d == "postgresql" else "INTEGER PRIMARY KEY AUTOINCREMENT"
    bool_f  = "DEFAULT FALSE"           if d == "postgresql" else "DEFAULT 0"

    with engine.begin() as c:
        c.execute(text(f"""
            CREATE TABLE IF NOT EXISTS payroll_employees (
                id                  VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::text,
                user_id             INTEGER,
                employee_number     VARCHAR(50) UNIQUE NOT NULL,
                first_name          VARCHAR(100) NOT NULL,
                last_name           VARCHAR(100) NOT NULL,
                email               VARCHAR(255) NOT NULL,
                phone               VARCHAR(30),
                tfn                 VARCHAR(20),
                employment_type     VARCHAR(30) NOT NULL DEFAULT 'full_time',
                pay_frequency       VARCHAR(20) DEFAULT 'fortnightly',
                annual_salary       NUMERIC(18,2) NOT NULL,
                hourly_rate         NUMERIC(18,4),
                super_fund_name     VARCHAR(100) DEFAULT 'AustralianSuper',
                super_fund_usi      VARCHAR(50),
                super_member_number VARCHAR(50),
                bank_bsb            VARCHAR(10),
                bank_account_number VARCHAR(20),
                bank_account_name   VARCHAR(100),
                start_date          VARCHAR(20) NOT NULL,
                end_date            VARCHAR(20),
                is_active           BOOLEAN {bool_f},
                tax_free_threshold  BOOLEAN DEFAULT TRUE,
                residency_status    VARCHAR(20) DEFAULT 'resident',
                address_line1       VARCHAR(200),
                address_suburb      VARCHAR(100),
                address_state       VARCHAR(10),
                address_postcode    VARCHAR(10),
                created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )"""))

        c.execute(text(f"""
            CREATE TABLE IF NOT EXISTS payroll_timesheets (
                id                       VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::text,
                employee_id              VARCHAR(36) NOT NULL,
                period_start             VARCHAR(20) NOT NULL,
                period_end               VARCHAR(20) NOT NULL,
                ordinary_hours           NUMERIC(9,2) DEFAULT 0,
                overtime_hours_1_5x      NUMERIC(9,2) DEFAULT 0,
                overtime_hours_2x        NUMERIC(9,2) DEFAULT 0,
                public_holiday_hours     NUMERIC(9,2) DEFAULT 0,
                annual_leave_hours       NUMERIC(9,2) DEFAULT 0,
                sick_leave_hours         NUMERIC(9,2) DEFAULT 0,
                long_service_leave_hours NUMERIC(9,2) DEFAULT 0,
                unpaid_leave_hours       NUMERIC(9,2) DEFAULT 0,
                notes                    TEXT,
                status                   VARCHAR(20) DEFAULT 'draft',
                submitted_at             TIMESTAMP,
                approved_at              TIMESTAMP,
                approved_by              VARCHAR(100),
                created_at               TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at               TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )"""))

        c.execute(text(f"""
            CREATE TABLE IF NOT EXISTS payroll_runs (
                id             VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::text,
                user_id        INTEGER,
                run_name       VARCHAR(200) NOT NULL,
                pay_frequency  VARCHAR(20),
                period_start   VARCHAR(20) NOT NULL,
                period_end     VARCHAR(20) NOT NULL,
                pay_date       VARCHAR(20),
                status         VARCHAR(20) DEFAULT 'pending',
                total_gross    NUMERIC(18,2) DEFAULT 0,
                total_tax      NUMERIC(18,2) DEFAULT 0,
                total_net      NUMERIC(18,2) DEFAULT 0,
                total_super    NUMERIC(18,2) DEFAULT 0,
                employee_count INTEGER DEFAULT 0,
                notes          TEXT,
                created_by     VARCHAR(100),
                created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                completed_at   TIMESTAMP
            )"""))

        c.execute(text(f"""
            CREATE TABLE IF NOT EXISTS payslips (
                id                       VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::text,
                payroll_run_id           VARCHAR(36) NOT NULL,
                employee_id              VARCHAR(36) NOT NULL,
                employee_number          VARCHAR(50),
                full_name                VARCHAR(200),
                period_start             VARCHAR(20),
                period_end               VARCHAR(20),
                pay_date                 VARCHAR(20),
                pay_frequency            VARCHAR(20),
                ordinary_hours           NUMERIC(9,2) DEFAULT 0,
                overtime_hours_1_5x      NUMERIC(9,2) DEFAULT 0,
                overtime_hours_2x        NUMERIC(9,2) DEFAULT 0,
                annual_leave_hours       NUMERIC(9,2) DEFAULT 0,
                sick_leave_hours         NUMERIC(9,2) DEFAULT 0,
                ordinary_pay             NUMERIC(18,2) DEFAULT 0,
                overtime_pay_1_5x        NUMERIC(18,2) DEFAULT 0,
                overtime_pay_2x          NUMERIC(18,2) DEFAULT 0,
                annual_leave_pay         NUMERIC(18,2) DEFAULT 0,
                sick_leave_pay           NUMERIC(18,2) DEFAULT 0,
                gross_earnings           NUMERIC(18,2) DEFAULT 0,
                payg_tax                 NUMERIC(18,2) DEFAULT 0,
                medicare_levy            NUMERIC(18,2) DEFAULT 0,
                total_tax                NUMERIC(18,2) DEFAULT 0,
                net_pay                  NUMERIC(18,2) DEFAULT 0,
                super_guarantee          NUMERIC(18,2) DEFAULT 0,
                super_fund_name          VARCHAR(100),
                super_member_number      VARCHAR(50),
                ytd_gross                NUMERIC(18,2) DEFAULT 0,
                ytd_tax                  NUMERIC(18,2) DEFAULT 0,
                ytd_super                NUMERIC(18,2) DEFAULT 0,
                hourly_rate              NUMERIC(18,4),
                annual_salary            NUMERIC(18,2),
                created_at               TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )"""))

        c.execute(text(f"""
            CREATE TABLE IF NOT EXISTS stp_submissions (
                id               VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::text,
                payroll_run_id   VARCHAR(36),
                abn              VARCHAR(20),
                submission_date  VARCHAR(20),
                period_start     VARCHAR(20),
                period_end       VARCHAR(20),
                employee_count   INTEGER DEFAULT 0,
                total_gross      NUMERIC(18,2) DEFAULT 0,
                total_tax        NUMERIC(18,2) DEFAULT 0,
                total_super      NUMERIC(18,2) DEFAULT 0,
                payload_json     TEXT,
                status           VARCHAR(20) DEFAULT 'draft',
                ato_reference    VARCHAR(50),
                submitted_by     VARCHAR(100),
                submitted_at     TIMESTAMP,
                created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )"""))

        # Indexes (IF NOT EXISTS)
        for sql in [
            "CREATE INDEX IF NOT EXISTS idx_pr_emp    ON payroll_timesheets(employee_id)",
            "CREATE INDEX IF NOT EXISTS idx_ps_run    ON payslips(payroll_run_id)",
            "CREATE INDEX IF NOT EXISTS idx_ps_emp    ON payslips(employee_id)",
            "CREATE INDEX IF NOT EXISTS idx_stp_run   ON stp_submissions(payroll_run_id)",
        ]:
            try:
                with c.begin_nested():
                    c.execute(text(sql))
            except SQLAlchemyError as e:                 # an index that cannot be created is logged, never ignored silently
                logger.warning("Migration: payroll index skipped (%s): %s", sql, e)

    logger.info("Migration: created payroll tables (employees, timesheets, runs, payslips, stp_submissions)")
