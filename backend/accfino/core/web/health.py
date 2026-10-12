"""Health and readiness probes, dev shutdown (paths unchanged: /health, /ready, /shutdown)."""
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from accfino.core.web import state

router = APIRouter()


@router.get("/ready", include_in_schema=False)
def readiness_probe():
    """
    Northflank / Kubernetes readiness probe.
    Returns 200 once the app is fully initialised, 503 during startup.
    Configure Northflank to use this as the health check path.
    """
    if state.is_ready():
        return JSONResponse({"status": "ready"}, status_code=200)
    return JSONResponse({"status": "starting"}, status_code=503)


@router.post("/shutdown", include_in_schema=False)
async def shutdown():
    """Graceful shutdown - closes DB connections then exits."""
    import os
    import signal
    import threading

    def _stop():
        import time
        time.sleep(0.5)
        os.kill(os.getpid(), signal.SIGTERM)
    threading.Thread(target=_stop, daemon=True).start()
    return {"ok": True}


@router.get("/health", include_in_schema=False)
def health_check():
    """Simple liveness probe - returns 200 if the API process is running."""
    return {"status": "ok", "service": "accfino-api"}
