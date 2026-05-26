# Azure Model Availability Dashboard

A tiny local dashboard that queries Azure Resource Manager and shows which
**Azure AI Foundry / Azure OpenAI models** are available in each region, with
search, capability filters, region-vs-region diff, quota lookup, and CSV export.

```
+--------------+      Bearer token       +-------------------------+
|  index.html  | <---->  FastAPI  <----> |  management.azure.com   |
|  app.js      |        backend          |  ARM REST APIs          |
+--------------+    (az CLI token)       +-------------------------+
```

## What it queries

| Purpose                  | ARM endpoint                                                                                          |
| ------------------------ | ----------------------------------------------------------------------------------------------------- |
| Subscriptions            | `GET /subscriptions`                                                                                  |
| Regions                  | `GET /subscriptions/{sub}/locations`                                                                  |
| **Foundry/AOAI models**  | `GET /subscriptions/{sub}/providers/Microsoft.CognitiveServices/locations/{loc}/models`               |
| Quota / usage            | `GET /subscriptions/{sub}/providers/Microsoft.CognitiveServices/locations/{loc}/usages`               |
| AML registries (own)     | `GET /subscriptions/{sub}/providers/Microsoft.MachineLearningServices/registries`                     |
| Registry models          | `GET .../registries/{registry}/models`                                                                |

> The Cognitive Services `models` API returns the full Foundry catalog
> (OpenAI, Microsoft, Meta, Mistral, DeepSeek, …) per region, including
> SKU/capacity defaults, capabilities, deprecation dates, and lifecycle.
>
> AML registry models live in registries (global), not regions. They are
> exposed as a separate endpoint and not shown in the region table.

## Prerequisites

- Python 3.10+
- Azure CLI installed and signed in: `az login`
- Reader access (or higher) on at least one subscription

## Run

### Windows (PowerShell)

```pwsh
cd tools/model-availability-dashboard
pwsh -File .\run.ps1
```

### macOS / Linux

```bash
cd tools/model-availability-dashboard
./run.sh
```

The script creates `.venv`, installs deps, and starts uvicorn on
<http://localhost:8765>. Your browser opens automatically.

### Manual run

```pwsh
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r backend/requirements.txt
az login
uvicorn backend.main:app --port 8765
```

## How to use the UI

1. Pick a **subscription** (auto-loaded after sign-in).
2. Pick **Region A** and click **Load models**.
3. (Optional) Switch **Mode** to **Compare two regions** to see two side-by-side
   tables plus an "Only in A / Common / Only in B" diff panel.
4. Type in the search box to filter by model name / publisher / version.
5. Click capability chips (chat, embeddings, audio, …) to narrow further.
6. Click any row to open a detail drawer with the raw normalized JSON and the
   matching `usages` entries (quota).
7. **Export CSV** dumps the currently filtered rows.

## Auth

The backend shells out to `az account get-access-token --resource https://management.azure.com`
to get a bearer token. This avoids the `azure-identity` + `cryptography` native
build chain (cryptography has no prebuilt wheels for Windows ARM64).

Requirement: Azure CLI installed and `az login` completed.

If you get 401s, run `az account get-access-token --resource https://management.azure.com` to confirm.

## Caching

Server-side responses are cached in-memory for 5 minutes
(`CACHE_TTL` env var to tweak). Restart the process to bust the cache.

## Configuration

All settings are optional environment variables (loaded from `.env` if present).
Copy `.env.example` to `.env` and edit as needed.

| Variable              | Default                          | Purpose                                  |
| --------------------- | -------------------------------- | ---------------------------------------- |
| `HOST`                | `127.0.0.1`                      | Bind address                             |
| `PORT`                | `8765`                           | HTTP port                                |
| `LOG_LEVEL`           | `INFO`                           | DEBUG/INFO/WARNING/ERROR                 |
| `CACHE_TTL`           | `300`                            | Cache lifetime, seconds                  |
| `HTTP_TIMEOUT`        | `60`                             | httpx timeout, seconds                   |
| `ARM_ENDPOINT`        | `https://management.azure.com`   | Sovereign cloud override                 |
| `ARM_RESOURCE`        | `https://management.azure.com`   | Token audience for sovereign cloud       |
| `API_COGSVC`          | `2024-10-01`                     | CognitiveServices `models`/`usages` api-version |
| `API_COGSVC_FALLBACK` | `2023-05-01`                     | Used when a region rejects the primary version |
| `API_AML`             | `2024-10-01-preview`             | MachineLearningServices `registries` api-version |
| `API_SUBSCRIPTIONS`   | `2022-12-01`                     |                                          |
| `API_LOCATIONS`       | `2022-12-01`                     |                                          |

## API surface (proxied through the backend)

| Method | Path                                                          |
| ------ | ------------------------------------------------------------- |
| GET    | `/api/subscriptions`                                          |
| GET    | `/api/subscriptions/{sub}/locations`                          |
| GET    | `/api/subscriptions/{sub}/locations/{loc}/models`             |
| GET    | `/api/subscriptions/{sub}/locations/{loc}/usages`             |
| GET    | `/api/subscriptions/{sub}/locations/{loc}/bundle`             |
| GET    | `/api/subscriptions/{sub}/registries`                         |
| GET    | `/api/subscriptions/{sub}/registries/{registry}/models?rg=…`  |
| GET    | `/api/health`                                                 |

## Troubleshooting

- **No subscriptions**: run `az login` and `az account list` to confirm.
- **401/403 on a region**: subscription may not be registered for
  `Microsoft.CognitiveServices`. Register it with
  `az provider register -n Microsoft.CognitiveServices`.
- **Empty model list**: the region may not support Foundry models. Try
  `eastus`, `swedencentral`, `westus3`, `northcentralus`.
- **CORS errors**: don't open `index.html` directly via `file://`; always go
  through the backend at `http://localhost:8765`.

## Files

```
tools/model-availability-dashboard/
├── backend/
│   ├── __init__.py
│   ├── arm_client.py        # async ARM REST client w/ caching + paging
│   ├── config.py            # env-driven settings
│   ├── main.py              # FastAPI app, serves frontend + /api/*
│   └── requirements.txt
├── frontend/
│   ├── index.html
│   ├── app.js
│   └── styles.css
├── .env.example
├── run.ps1
├── run.sh
├── .gitignore
└── README.md
```
