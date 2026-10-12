"""
Application start-up hook.

Marks the app ready immediately so health checks pass, starts every module's start-up hook (e.g. Billing's renewal loop), then runs
database housekeeping in a background thread so slow Neon cold-starts don't block uvicorn from finishing start-up.
Module-owned raw-SQL migrations are discovered through accfino.shared.contracts.registry - Core never imports a module.
"""
import logging
import threading

from accfino.core.web import state
from accfino.shared.contracts import registry

logger = logging.getLogger("accfino")


def _bg_init():
    # Never create or alter tables in a database that belongs to another application
    try:
        from accfino.core.init_db import ForeignDatabaseError, _check_database_is_accfino
        _check_database_is_accfino()
    except ForeignDatabaseError as _fe:
        logger.error("startup: %s", _fe)
        return
    except Exception as _ce:
        logger.warning("startup: database ownership check skipped: %s", _ce)
    registry.load_all()
    registry.import_all_models()
    try:
        from accfino.shared.db.database import engine as _db_engine
        from accfino.core.subscription.licence import LicenceRecord as _LR
        from accfino.core.identity.password_reset_token import PasswordResetToken as _PRT
        _LR.__table__.create(bind=_db_engine, checkfirst=True)
        _PRT.__table__.create(bind=_db_engine, checkfirst=True)
    except Exception as _e:
        logger.warning(f"startup: table create skipped: {_e}")
    try:
        from accfino.core.init_db import migrate_db as _mdb
        _mdb()
    except Exception as _e:
        logger.warning(f"startup: migrate_db skipped: {_e}")
    from accfino.shared.db.database import engine as _db_engine
    # shared + core migrations
    for _label, _mod in (("groq_key_pool", "accfino.shared.llm.migrations.create_groq_key_pool"),
                         ("platform_settings", "accfino.core.migrations.create_platform_settings")):
        try:
            import importlib
            importlib.import_module(_mod).run(_db_engine)
        except Exception as _e:
            logger.warning(f"startup: {_label} migration skipped: {_e}")
    # every module's own raw-SQL migrations (accounting documents, payroll, reference data, ...)
    registry.run_startup_steps(_db_engine, lambda msg: logger.warning(msg))
    try:
        from accfino.core.subscription.migrations.restructure_pricing_plans import run as _mpp
        _mpp(_db_engine)
        from sqlalchemy.orm import Session as _AS
        from accfino.core.subscription.align import run_alignment as _align
        with _AS(_db_engine) as _adb:                      # the table may only exist now: mirror the organisation plans into it
            _align(_adb)
            _adb.commit()
    except Exception as _e:
        logger.warning(f"startup: pricing_plans restructure migration skipped: {_e}")
    logger.info("startup: background DB init complete")


async def on_startup():
    state.mark_ready()
    try:
        from accfino.shared import paths
        paths.bootstrap_data_root()            # data-root skeleton + shipped defaults (never overwrites existing files)
    except Exception as _pe:
        logger.warning("startup: data root not prepared: %s", _pe)
    registry.run_on_startup(lambda msg: logger.warning(msg))
    threading.Thread(target=_bg_init, daemon=True, name="startup-db-init").start()
