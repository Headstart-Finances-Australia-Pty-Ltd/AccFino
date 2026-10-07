"""
accfino.shared.contracts.registry
---------------------------------
The ONLY way Core and Shared learn about the domain modules.

Core must never import a domain module. Instead each module describes what it contributes in its own
`manifest.py` (database tables, schema hooks, per-organisation provisioning, ...), and Core calls the hooks collected here.
`load_all()` imports every manifest once; it is called by the composition root (accfino.app), by the CLI initialiser
(python -m accfino.core.init_db) and by tests/tools that need the full schema.
"""
from __future__ import annotations

import importlib
import logging
from dataclasses import dataclass
from typing import Callable, Iterable

log = logging.getLogger("accfino.registry")

# Order is the historical registration order (it only affects the order of schema hooks).
MODULE_NAMES = ("accounting", "reconciliation", "cashflow", "trading", "lending", "payroll", "taxation", "billing", "open_banking")


@dataclass
class ModuleSpec:
    name: str
    title: str = ""
    models: tuple = ()                       # dotted modules to import so their tables register on Base.metadata
    tables: Callable[[], list] = lambda: []  # SQLAlchemy Table objects the platform migration must create_all
    raw_sql_tables: tuple = ()               # tables created by raw-SQL migrations (shown in the admin table browser)
    pre_schema: tuple = ()                   # callables(engine)  - before create_all (e.g. drop stale tables)
    pg_schema: tuple = ()                    # callables(conn)    - PostgreSQL only: triggers / ALTER TABLE, inside one transaction
    post_schema: tuple = ()                  # callables(engine)  - after create_all (data migrations)
    org_provision: tuple = ()                # callables(db, org) - whenever an organisation is created / topped up
    plan_renamed: tuple = ()                 # callables(db, old_plan_id, new_plan_id)
    protected_trigger_tables: tuple = ()     # immutable-record tables (force-delete must lift their triggers)
    init_upgrade_steps: tuple = ()           # callables(engine) - upgrade an EXISTING database before create_all
    init_seeds: tuple = ()                   # callables(SessionLocal) - one-time seeding after the database is initialised
    on_startup: tuple = ()                   # callables() - run once when the web app starts (e.g. Billing starts its renewal loop)
    org_billing: tuple = ()                  # callables(db, org_id) -> billing record or None (shown in the admin user/plan directory)
    startup_steps: tuple = ()                # callables(engine) - idempotent raw-SQL migrations run in the background at every app start


_specs: dict = {}
_loaded = False


def register(spec: ModuleSpec) -> None:
    _specs[spec.name] = spec


def load_all() -> None:
    global _loaded
    if _loaded:
        return
    importlib.import_module("accfino.core.manifest")        # discovered by name: Shared never imports Core statically
    importlib.import_module("accfino.core.manifest")        # discovered by name: Shared never imports Core statically
    importlib.import_module("accfino.core.manifest")        # discovered by name: Shared never imports Core statically
    importlib.import_module("accfino.core.manifest")        # discovered by name: Shared never imports Core statically
    importlib.import_module("accfino.core.manifest")        # discovered by name: Shared never imports Core statically
    importlib.import_module("accfino.core.manifest")        # discovered by name: Shared never imports Core statically
    importlib.import_module("accfino.core.manifest")        # discovered by name: Shared never imports Core statically
    importlib.import_module("accfino.core.manifest")        # discovered by name: Shared never imports Core statically
    importlib.import_module("accfino.core.manifest")        # discovered by name: Shared never imports Core statically
    importlib.import_module("accfino.core.manifest")        # discovered by name: Shared never imports Core statically
    importlib.import_module("accfino.core.manifest")        # discovered by name: Shared never imports Core statically
    importlib.import_module("accfino.core.manifest")        # discovered by name: Shared never imports Core statically
    importlib.import_module("accfino.core.manifest")        # discovered by name: Shared never imports Core statically
    for name in MODULE_NAMES:
        importlib.import_module(f"accfino.modules.{name}.manifest")
    _loaded = True


def specs() -> list:
    load_all()
    return [_specs[n] for n in MODULE_NAMES if n in _specs]


_core_models: tuple = ()


def register_core(models: tuple = ()) -> None:
    """Called by accfino.core.manifest: the model modules Core owns."""
    global _core_models
    _core_models = tuple(models)


_core_models: tuple = ()


def register_core(models: tuple = ()) -> None:
    """Called by accfino.core.manifest: the model modules Core owns."""
    global _core_models
    _core_models = tuple(models)


_core_models: tuple = ()


def register_core(models: tuple = ()) -> None:
    """Called by accfino.core.manifest: the model modules Core owns."""
    global _core_models
    _core_models = tuple(models)


_core_models: tuple = ()


def register_core(models: tuple = ()) -> None:
    """Called by accfino.core.manifest: the model modules Core owns."""
    global _core_models
    _core_models = tuple(models)


_core_models: tuple = ()


def register_core(models: tuple = ()) -> None:
    """Called by accfino.core.manifest: the model modules Core owns."""
    global _core_models
    _core_models = tuple(models)


_core_models: tuple = ()


def register_core(models: tuple = ()) -> None:
    """Called by accfino.core.manifest: the model modules Core owns."""
    global _core_models
    _core_models = tuple(models)


_core_models: tuple = ()


def register_core(models: tuple = ()) -> None:
    """Called by accfino.core.manifest: the model modules Core owns."""
    global _core_models
    _core_models = tuple(models)


_core_models: tuple = ()


def register_core(models: tuple = ()) -> None:
    """Called by accfino.core.manifest: the model modules Core owns."""
    global _core_models
    _core_models = tuple(models)


_core_models: tuple = ()


def register_core(models: tuple = ()) -> None:
    """Called by accfino.core.manifest: the model modules Core owns."""
    global _core_models
    _core_models = tuple(models)


_core_models: tuple = ()


def register_core(models: tuple = ()) -> None:
    """Called by accfino.core.manifest: the model modules Core owns."""
    global _core_models
    _core_models = tuple(models)


_core_models: tuple = ()


def register_core(models: tuple = ()) -> None:
    """Called by accfino.core.manifest: the model modules Core owns."""
    global _core_models
    _core_models = tuple(models)


_core_models: tuple = ()


def register_core(models: tuple = ()) -> None:
    """Called by accfino.core.manifest: the model modules Core owns."""
    global _core_models
    _core_models = tuple(models)


_core_models: tuple = ()


def register_core(models: tuple = ()) -> None:
    """Called by accfino.core.manifest: the model modules Core owns."""
    global _core_models
    _core_models = tuple(models)


def import_all_models() -> None:
    """Import every model module (Core's and each module's) so Base.metadata knows every AccFino table."""
    load_all()
    for mod in _core_models:
        importlib.import_module(mod)
    for s in specs():
        for mod in s.models:
            importlib.import_module(mod)


def schema_tables() -> list:
    out = []
    for s in specs():
        out.extend(s.tables())
    return out


def raw_sql_tables() -> set:
    out = set()
    for s in specs():
        out.update(s.raw_sql_tables)
    return out


def _each(attr: str) -> Iterable[Callable]:
    for s in specs():
        for fn in getattr(s, attr):
            yield fn


def run_pre_schema(engine) -> None:
    for fn in _each("pre_schema"):
        fn(engine)


def run_pg_schema(conn) -> None:
    for fn in _each("pg_schema"):
        fn(conn)


def run_post_schema(engine) -> None:
    for fn in _each("post_schema"):
        try:
            fn(engine)
        except Exception as e:      # never stop the app from starting; the admin report shows what is pending
            log.error("post-schema step %s could not run: %s", getattr(fn, "__qualname__", fn), e)


def provision_org(db, org) -> None:
    """Give a new / existing organisation whatever each module needs (e.g. Accounting seeds its chart of accounts + tax codes)."""
    for fn in _each("org_provision"):
        fn(db, org)


def plan_renamed(db, old: str, new: str) -> None:
    for fn in _each("plan_renamed"):
        try:
            fn(db, old, new)
        except Exception:
            pass


def protected_trigger_tables() -> tuple:
    out: list = []
    for s in specs():
        out.extend(s.protected_trigger_tables)
    return tuple(out)


def run_init_upgrade_steps(engine, warn: Callable) -> None:
    for s in specs():
        for fn in s.init_upgrade_steps:
            try:
                fn(engine)
            except Exception as e:
                warn(f"{s.name}: {getattr(fn, '__qualname__', fn)} skipped: {e}")


def run_init_seeds(session_local) -> None:
    for fn in _each("init_seeds"):
        fn(session_local)


def run_startup_steps(engine, warn: Callable) -> None:
    for s in specs():
        for fn in s.startup_steps:
            try:
                fn(engine)
            except Exception as e:
                warn(f"startup: {s.name} migration {getattr(fn, '__module__', '?').rsplit('.', 1)[-1]} skipped: {e}")


def run_on_startup(warn: Callable) -> None:
    for s in specs():
        for fn in s.on_startup:
            try:
                fn()
            except Exception as e:
                warn(f"startup: {s.name} hook {getattr(fn, '__qualname__', fn)} not started: {e}")


def org_billing(db, org_id):
    """The billing record of an organisation, from whichever module provides billing (None when there is none)."""
    for fn in _each("org_billing"):
        rec = fn(db, org_id)
        if rec is not None:
            return rec
    return None
