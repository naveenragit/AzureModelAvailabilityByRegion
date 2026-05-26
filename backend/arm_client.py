"""Thin async wrapper around Azure Resource Manager REST APIs.

Auth: shells out to `az account get-access-token` (uses your existing `az login`).
This avoids pulling in azure-identity + cryptography, which lacks prebuilt wheels
on Windows ARM64.

Endpoints used:
  - Subscriptions:        GET /subscriptions
  - Locations:            GET /subscriptions/{sub}/locations
  - Cognitive models:     GET /subscriptions/{sub}/providers/Microsoft.CognitiveServices/locations/{loc}/models
  - Cognitive usages:     GET /subscriptions/{sub}/providers/Microsoft.CognitiveServices/locations/{loc}/usages
  - AML registries:       GET /subscriptions/{sub}/providers/Microsoft.MachineLearningServices/registries
  - Registry models:      GET .../registries/{registry}/models
"""
from __future__ import annotations

import asyncio
import json
import shutil
import time
from datetime import datetime, timezone
from typing import Any

import httpx

from .config import settings

ARM = settings.arm_endpoint
ARM_RESOURCE = settings.arm_resource

API_SUBSCRIPTIONS = settings.api_subscriptions
API_LOCATIONS = settings.api_locations
API_COGSVC = settings.api_cogsvc
# Some regions don't yet expose the stable api-version for models; we'll retry with this preview.
API_COGSVC_FALLBACK = settings.api_cogsvc_fallback
API_AML = settings.api_aml


class AzCliAuthError(RuntimeError):
    pass


async def _get_token_via_az() -> tuple[str, float]:
    """Run `az account get-access-token` and return (token, expires_on_epoch)."""
    az = shutil.which("az") or shutil.which("az.cmd")
    if not az:
        raise AzCliAuthError("Azure CLI ('az') not found on PATH. Install it and run `az login`.")
    proc = await asyncio.create_subprocess_exec(
        az, "account", "get-access-token", "--resource", ARM_RESOURCE, "--output", "json",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    out, err = await proc.communicate()
    if proc.returncode != 0:
        raise AzCliAuthError(
            f"`az account get-access-token` failed: {err.decode(errors='replace').strip()}"
        )
    data = json.loads(out)
    token = data["accessToken"]
    # expiresOn is local time like "2026-05-26 14:30:00.000000"; prefer expires_on (epoch) if present
    if "expires_on" in data:
        exp = float(data["expires_on"])
    else:
        # Best-effort parse; fall back to 30 min from now
        try:
            exp = datetime.fromisoformat(data["expiresOn"]).timestamp()
        except Exception:
            exp = time.time() + 1800
    return token, exp


class ArmClient:
    def __init__(self, cache_ttl: int | None = None):
        self._client = httpx.AsyncClient(timeout=settings.http_timeout)
        self._token: str | None = None
        self._token_exp: float = 0.0
        self._cache: dict[str, tuple[float, Any]] = {}
        self._cache_ttl = cache_ttl if cache_ttl is not None else settings.cache_ttl
        self._lock = asyncio.Lock()

    async def close(self):
        await self._client.aclose()

    async def _auth_header(self) -> dict[str, str]:
        async with self._lock:
            now = time.time()
            if not self._token or now >= self._token_exp - 60:
                self._token, self._token_exp = await _get_token_via_az()
        return {"Authorization": f"Bearer {self._token}"}

    async def _get(self, url: str, params: dict[str, str] | None = None) -> dict:
        """GET with paging (follows nextLink). Returns {'value': [...], 'raw': last_page}."""
        cache_key = f"{url}?{sorted((params or {}).items())}"
        now = time.time()
        if cache_key in self._cache:
            ts, val = self._cache[cache_key]
            if now - ts < self._cache_ttl:
                return val

        headers = await self._auth_header()
        items: list[Any] = []
        next_url: str | None = url
        next_params = params
        last: dict = {}
        while next_url:
            r = await self._client.get(next_url, headers=headers, params=next_params)
            if r.status_code >= 400:
                raise httpx.HTTPStatusError(
                    f"{r.status_code} {r.text[:500]}", request=r.request, response=r
                )
            last = r.json()
            items.extend(last.get("value", []) if isinstance(last, dict) else [])
            next_url = last.get("nextLink") if isinstance(last, dict) else None
            next_params = None  # nextLink already has its own query
        result = {"value": items, "raw": last}
        self._cache[cache_key] = (now, result)
        return result

    # ---------- Public API ----------

    async def list_subscriptions(self) -> list[dict]:
        data = await self._get(
            f"{ARM}/subscriptions", params={"api-version": API_SUBSCRIPTIONS}
        )
        return [
            {
                "subscriptionId": s["subscriptionId"],
                "displayName": s.get("displayName"),
                "state": s.get("state"),
                "tenantId": s.get("tenantId"),
            }
            for s in data["value"]
        ]

    async def list_locations(self, sub: str) -> list[dict]:
        data = await self._get(
            f"{ARM}/subscriptions/{sub}/locations",
            params={"api-version": API_LOCATIONS},
        )
        out = []
        for loc in data["value"]:
            md = loc.get("metadata") or {}
            out.append(
                {
                    "name": loc["name"],
                    "displayName": loc.get("displayName"),
                    "regionalDisplayName": loc.get("regionalDisplayName"),
                    "geography": md.get("geographyGroup"),
                    # Physical city, e.g. "Singapore" for southeastasia, "Hong Kong" for eastasia.
                    "physicalLocation": md.get("physicalLocation"),
                    "regionType": md.get("regionType"),  # Physical | Logical
                    "regionCategory": md.get("regionCategory"),  # Recommended | Other
                    "pairedRegion": [
                        p.get("name") for p in (md.get("pairedRegion") or []) if p.get("name")
                    ],
                }
            )
        return out

    async def list_cogsvc_models(self, sub: str, location: str) -> list[dict]:
        url = f"{ARM}/subscriptions/{sub}/providers/Microsoft.CognitiveServices/locations/{location}/models"
        for api in (API_COGSVC, API_COGSVC_FALLBACK):
            try:
                data = await self._get(url, params={"api-version": api})
                return data["value"]
            except httpx.HTTPStatusError as e:
                msg = (e.response.text or "").lower() if e.response is not None else ""
                if "noregisteredproviderfound" in msg or "locationnotavailable" in msg:
                    if api == API_COGSVC:
                        continue  # try fallback api-version
                    return []  # region simply doesn't host this RP
                raise
        return []

    async def list_cogsvc_usages(self, sub: str, location: str) -> list[dict]:
        url = f"{ARM}/subscriptions/{sub}/providers/Microsoft.CognitiveServices/locations/{location}/usages"
        for api in (API_COGSVC, API_COGSVC_FALLBACK):
            try:
                data = await self._get(url, params={"api-version": api})
                return data["value"]
            except httpx.HTTPStatusError as e:
                msg = (e.response.text or "").lower() if e.response is not None else ""
                if "noregisteredproviderfound" in msg or "locationnotavailable" in msg:
                    if api == API_COGSVC:
                        continue
                    return []
                # Usages is non-critical; swallow other errors too.
                return []
        return []

    async def list_aml_registries(self, sub: str) -> list[dict]:
        try:
            data = await self._get(
                f"{ARM}/subscriptions/{sub}/providers/Microsoft.MachineLearningServices/registries",
                params={"api-version": API_AML},
            )
            return data["value"]
        except httpx.HTTPStatusError:
            return []

    async def list_registry_models(
        self, sub: str, rg: str, registry: str, top: int = 100
    ) -> list[dict]:
        try:
            data = await self._get(
                f"{ARM}/subscriptions/{sub}/resourceGroups/{rg}/providers/"
                f"Microsoft.MachineLearningServices/registries/{registry}/models",
                params={"api-version": API_AML, "$top": str(top)},
            )
            return data["value"]
        except httpx.HTTPStatusError:
            return []
