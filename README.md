# ReMarket

A small Python website based on the four supplied Stitch screens: home, product details, sell an item, and my account. It uses FastAPI, Jinja templates, and SQLite. The local app starts with four clearly marked sample listings.

## Run locally

From this folder in PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m uvicorn app:app --reload --host 127.0.0.1 --port 8000
```

Open <http://127.0.0.1:8000/>. The sample seller account is `demo@remarket.local` with password `demo12345`. Create another account to try buying a sample item. Purchases create a local completed order only; no payment or handoff is processed.

The first run creates `remarket.db` and a local `.secret_key`. Both are ignored by Git. Uploaded photos go to `static/uploads/`. Set `REMARKET_SESSION_SECRET` to a long random value when running in a hosted environment, and `REMARKET_HTTPS_ONLY=1` behind HTTPS.

## What works

- Search, category and condition filters, and sorting.
- Registration, sign in, listing creation with an optional photo, account listings, and simulated purchases.
- Product pages that request the public CraftProof `/api/verify/{code}` response when a seller adds a certificate code. The returned ownership history is displayed as CraftProof data. ReMarket does not check that a code belongs to the photographed item or that the seller is its current recorded owner.
- API-key protected `GET /api/v1/sales` and `GET /api/v1/sales/{order_id}` endpoints for CraftProof to discover and retrieve completed sales with certificates.

To enable the sale API, set an API key **before starting** the server:

```powershell
$env:REMARKET_SALE_API_KEY = "replace-with-a-long-random-secret"
python -m uvicorn app:app --host 127.0.0.1 --port 8000
```

Send `Authorization: Bearer <key>` to `/api/v1/sales?after_id=0`. This returns completed certificate sales in ascending order, up to 100 per request, plus `next_after_id` for the next poll. `/api/v1/sales/RM-000001` retrieves a single order. Each sale has `order_id`, `certificate_code`, `buyer_name`, `status`, and `completed_at`. The certificate code and buyer name are saved when the purchase happens. No CraftProof user IDs are needed. See [CRAFTPROOF_INTEGRATION.md](CRAFTPROOF_INTEGRATION.md) for the proposed contract and partner checklist.

CraftProof's current transfer request accepts a new holder name (`to_name`); it does not ask for an address. The CraftProof import action by certificate code still needs to be built by its team. Until then, these APIs expose sale data but do not change the certificate. The buyer name in ReMarket is self reported and is not an identity check.

FastAPI’s interactive API docs are at <http://127.0.0.1:8000/docs>. The sale API returns 503 until a key is configured.
The website also has a developer-facing API guide at <http://127.0.0.1:8000/api>, linked from the main navigation.

## Limits

This is a student demonstration, not a production marketplace. It has no real payment, messaging, delivery, escrow, automatic CraftProof transfer, or deployment. The sample listings and demo credentials should be removed before any public release. Images included here came from the user-supplied Stitch HTML references.
