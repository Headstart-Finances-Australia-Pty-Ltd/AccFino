"""
accfino.shared.paths
--------------------
The ONE place that knows where files live. No other module may build a data path from __file__ or a literal folder name.

  ACCFINO_DATA_ROOT   persistent business data + documents, OUTSIDE the application package (volume in production).
                      Layout:
                        reference/            chart of accounts, knowledge base, RDR rules, pricing, companies, lending rules (editable at runtime)
                        config/               runtime integration settings (integrations.json)
                        legal/                legal documents served by the website (PDF)
                        shared/ml_models/     trained classifier models (.pkl)
                        shared/llm_cache/     LLM answer caches
                        modules/<module>/...  per-module files (e.g. modules/trading/inputs, modules/cashflow/outputs, modules/open_banking/exports)
  ACCFINO_SEED_DIR    read-only defaults shipped WITH the application (deploy/data-seed). Copied into the data root the first time a
                      file is needed (bootstrap_data_root()); never written to at runtime.
  ACCFINO_TEST_DATA_ROOT   test datasets (mock CSVs, fixtures) - separate from production data.
"""
from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path

log = logging.getLogger("accfino.paths")

_PKG_ROOT = Path(__file__).resolve().parents[3]            # .../AccFino  (the application package root)


def data_root() -> Path:
    env = os.environ.get("ACCFINO_DATA_ROOT", "").strip()
    root = Path(env).expanduser() if env else _PKG_ROOT.parent / "AccFino_Data"
    return root.resolve()


def seed_root() -> Path:
    env = os.environ.get("ACCFINO_SEED_DIR", "").strip()
    return (Path(env).expanduser() if env else _PKG_ROOT / "deploy" / "data-seed").resolve()


def test_data_root() -> Path:
    env = os.environ.get("ACCFINO_TEST_DATA_ROOT", "").strip()
    return (Path(env).expanduser() if env else _PKG_ROOT.parent / "AccFino_Testing" / "testdata").resolve()


def ensure(p: Path) -> Path:
    p.mkdir(parents=True, exist_ok=True)
    return p


def _seeded(rel: str) -> Path:
    """data_root()/rel, first copied from the seed folder if it is missing there."""
    dst = data_root() / rel
    if not dst.exists():
        src = seed_root() / rel
        if src.exists():
            ensure(dst.parent)
            if src.is_dir():
                shutil.copytree(src, dst)
            else:
                shutil.copy2(src, dst)
            log.info("data root: seeded %s", rel)
    return dst


def reference_dir() -> Path:
    return ensure(data_root() / "reference")


def reference_file(name: str) -> Path:
    return _seeded(f"reference/{name}")


def config_file(name: str) -> Path:
    return _seeded(f"config/{name}")


def legal_dir() -> Path:
    return _seeded("legal")


def module_dir(module: str, *parts: str) -> Path:
    """data_root()/modules/<module>/<parts...> (created on first use)."""
    return ensure(data_root().joinpath("modules", module, *parts))


def module_file(module: str, *parts: str) -> Path:
    """Like module_dir but for a FILE: the parent folder is created, the file is seeded from the seed folder if a default ships."""
    return _seeded("/".join(("modules", module) + parts))


def org_dir(module: str, org_id, *parts: str) -> Path:
    return module_dir(module, f"org_{org_id}", *parts)


def ml_models_dir() -> Path:
    return ensure(data_root() / "shared" / "ml_models")


def llm_cache_dir() -> Path:
    return ensure(data_root() / "shared" / "llm_cache")


def filemanager_root() -> Path:
    return ensure(data_root())


def bootstrap_data_root() -> None:
    """Create the folder skeleton and copy every shipped default that is not there yet. Idempotent; called at start-up."""
    for rel in ("reference", "config", "legal", "shared/ml_models", "shared/llm_cache", "modules"):
        ensure(data_root() / rel)
    sr = seed_root()
    if sr.exists():
        for src in sorted(sr.rglob("*")):
            if src.is_file():
                rel = src.relative_to(sr)
                dst = data_root() / rel
                if not dst.exists():
                    ensure(dst.parent)
                    shutil.copy2(src, dst)
    log.info("data root: %s (seed: %s)", data_root(), sr)


def package_root() -> Path:
    """The application package root (contains backend/, frontend/, deploy/). Code and built UI only - never data."""
    env = os.environ.get("ACCFINO_ROOT", "").strip()
    return Path(env).resolve() if env else _PKG_ROOT
