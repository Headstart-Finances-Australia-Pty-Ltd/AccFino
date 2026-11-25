"""Migration: create payroll tables. Idempotent."""
import logging
logger = logging.getLogger(__name__)


def run(engine):
    from sqlalchemy import text, inspect
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
                annual_salary       FLOAT NOT NULL,
                hourly_rate         FLOAT,
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
                ordinary_hours           FLOAT DEFAULT 0,
                overtime_hours_1_5x      FLOAT DEFAULT 0,
                overtime_hours_2x        FLOAT DEFAULT 0,
                public_holiday_hours     FLOAT DEFAULT 0,
                annual_leave_hours       FLOAT DEFAULT 0,
                sick_leave_hours         FLOAT DEFAULT 0,
                long_service_leave_hours FLOAT DEFAULT 0,
                unpaid_leave_hours       FLOAT DEFAULT 0,
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
                total_gross    FLOAT DEFAULT 0,
                total_tax      FLOAT DEFAULT 0,
                total_net      FLOAT DEFAULT 0,
                total_super    FLOAT DEFAULT 0,
                employee_count FLOAT DEFAULT 0,
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
                ordinary_hours           FLOAT DEFAULT 0,
                overtime_hours_1_5x      FLOAT DEFAULT 0,
                overtime_hours_2x        FLOAT DEFAULT 0,
                annual_leave_hours       FLOAT DEFAULT 0,
                sick_leave_hours         FLOAT DEFAULT 0,
                ordinary_pay             FLOAT DEFAULT 0,
                overtime_pay_1_5x        FLOAT DEFAULT 0,
                overtime_pay_2x          FLOAT DEFAULT 0,
                annual_leave_pay         FLOAT DEFAULT 0,
                sick_leave_pay           FLOAT DEFAULT 0,
                gross_earnings           FLOAT DEFAULT 0,
                payg_tax                 FLOAT DEFAULT 0,
                medicare_levy            FLOAT DEFAULT 0,
                total_tax                FLOAT DEFAULT 0,
                net_pay                  FLOAT DEFAULT 0,
                super_guarantee          FLOAT DEFAULT 0,
                super_fund_name          VARCHAR(100),
                super_member_number      VARCHAR(50),
                ytd_gross                FLOAT DEFAULT 0,
                ytd_tax                  FLOAT DEFAULT 0,
                ytd_super                FLOAT DEFAULT 0,
                hourly_rate              FLOAT,
                annual_salary            FLOAT,
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
                employee_count   FLOAT DEFAULT 0,
                total_gross      FLOAT DEFAULT 0,
                total_tax        FLOAT DEFAULT 0,
                total_super      FLOAT DEFAULT 0,
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
                c.execute(text(sql))
            except Exception:
                pass

    logger.info("Migration: created payroll tables (employees, timesheets, runs, payslips, stp_submissions)")
