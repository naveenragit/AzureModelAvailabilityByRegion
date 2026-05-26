"""FastAPI app: serves the static frontend and proxies ARM calls.

Run:
    uvicorn backend.main:app --reload --port 8765
or use the run.ps1 / run.sh launcher.
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .arm_client import ArmClient
from .config import settings

logging.basicConfig(
    level=getattr(logging, settings.log_level, logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("dashboard")

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.arm = ArmClient(cache_ttl=settings.cache_ttl)
    log.info("ArmClient initialized (cache_ttl=%ss, endpoint=%s)", settings.cache_ttl, settings.arm_endpoint)
    try:
        yield
    finally:
        await app.state.arm.close()


app = FastAPI(title="Azure Model Availability Dashboard", lifespan=lifespan)


def _arm(app: FastAPI) -> ArmClient:
    return app.state.arm


def _handle_arm_error(e: Exception) -> JSONResponse:
    if isinstance(e, httpx.HTTPStatusError):
        return JSONResponse(
            status_code=e.response.status_code,
            content={"error": e.response.text[:2000]},
        )
    log.exception("ARM error")
    return JSONResponse(status_code=500, content={"error": str(e)})


# ---------- API routes ----------

@app.get("/api/subscriptions")
async def get_subscriptions():
    try:
        return await _arm(app).list_subscriptions()
    except Exception as e:
        return _handle_arm_error(e)


@app.get("/api/subscriptions/{sub}/locations")
async def get_locations(sub: str):
    try:
        return await _arm(app).list_locations(sub)
    except Exception as e:
        return _handle_arm_error(e)


def _normalize_cogsvc_model(m: dict) -> dict:
    model = m.get("model") or {}
    skus = model.get("skus") or []
    capabilities = model.get("capabilities") or {}
    return {
        "source": "CognitiveServices",
        "kind": m.get("kind"),
        "skuName": m.get("skuName"),
        "name": model.get("name"),
        "format": model.get("format"),  # publisher: OpenAI, Microsoft, Meta, etc.
        "version": model.get("version"),
        "lifecycleStatus": model.get("lifecycleStatus"),
        "systemData": m.get("systemData"),
        "deprecation": model.get("deprecation"),
        "capabilities": capabilities,
        "capabilityKeys": sorted(capabilities.keys()) if isinstance(capabilities, dict) else [],
        "skus": [
            {
                "name": s.get("name"),
                "usageName": s.get("usageName"),
                "capacity": s.get("capacity"),
                "rateLimits": s.get("rateLimits"),
            }
            for s in skus
        ],
        "_raw": m,
    }


@app.get("/api/subscriptions/{sub}/locations/{loc}/models")
async def get_models(sub: str, loc: str):
    try:
        raw = await _arm(app).list_cogsvc_models(sub, loc)
        return [_normalize_cogsvc_model(m) for m in raw]
    except Exception as e:
        return _handle_arm_error(e)


@app.get("/api/subscriptions/{sub}/locations/{loc}/usages")
async def get_usages(sub: str, loc: str):
    try:
        return await _arm(app).list_cogsvc_usages(sub, loc)
    except Exception as e:
        return _handle_arm_error(e)


@app.get("/api/subscriptions/{sub}/locations/{loc}/bundle")
async def get_bundle(sub: str, loc: str):
    """One call returns models + usages for the chosen region."""
    arm = _arm(app)
    try:
        models_task = asyncio.create_task(arm.list_cogsvc_models(sub, loc))
        usages_task = asyncio.create_task(arm.list_cogsvc_usages(sub, loc))
        models_raw = await models_task
        usages = await usages_task
        return {
            "models": [_normalize_cogsvc_model(m) for m in models_raw],
            "usages": usages,
        }
    except Exception as e:
        return _handle_arm_error(e)


@app.get("/api/subscriptions/{sub}/registries")
async def get_registries(sub: str):
    try:
        regs = await _arm(app).list_aml_registries(sub)
        return [
            {
                "id": r.get("id"),
                "name": r.get("name"),
                "location": r.get("location"),
                "resourceGroup": (r.get("id") or "").split("/resourceGroups/")[-1].split("/")[0] if "/resourceGroups/" in (r.get("id") or "") else None,
                "regionDetails": (r.get("properties") or {}).get("regionDetails"),
            }
            for r in regs
        ]
    except Exception as e:
        return _handle_arm_error(e)


@app.get("/api/subscriptions/{sub}/registries/{registry}/models")
async def get_registry_models(
    sub: str,
    registry: str,
    rg: str = Query(..., description="Resource group containing the registry"),
):
    try:
        models = await _arm(app).list_registry_models(sub, rg, registry)
        return [
            {
                "source": "AmlRegistry",
                "registry": registry,
                "name": m.get("name"),
                "id": m.get("id"),
                "properties": m.get("properties"),
                "systemData": m.get("systemData"),
            }
            for m in models
        ]
    except Exception as e:
        return _handle_arm_error(e)


@app.get("/api/health")
async def health():
    return {"ok": True}


# ---------- Static frontend ----------
# Mount LAST so /api/* routes win.
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
else:
    log.warning("Frontend dir not found at %s", FRONTEND_DIR)


def main() -> None:
    """CLI entry: `python -m backend.main` honors HOST/PORT/LOG_LEVEL env vars."""
    import uvicorn

    uvicorn.run(
        "backend.main:app",
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    main()
