# ReMarket → CraftProof ownership transfer

This is the proposed API contract for the CraftProof team. The ReMarket endpoints are implemented locally; CraftProof has not yet connected its import process.

## Flow

1. The seller lists an item with its CraftProof certificate code.
2. A ReMarket purchase creates a completed sale. ReMarket saves the certificate code and buyer name at purchase time.
3. CraftProof reads the ReMarket sale API. It finds the item internally by certificate code and confirms that the sale should update that certificate.
4. CraftProof records the buyer name as the new holder and stores the ReMarket order ID as a unique import reference. Repeated requests must not create duplicate transfers.

ReMarket does **not** call a CraftProof write endpoint. CraftProof is the API client here. If the CraftProof team prefers ReMarket to push a webhook, they must provide a receiver URL, authentication method, and agreed payload.

## ReMarket API

Set `REMARKET_SALE_API_KEY` in the ReMarket server environment before starting it. Share the key privately with the CraftProof server team. CraftProof must call these endpoints from its server, not from browser JavaScript.

```http
GET https://<public-remarket-host>/api/v1/sales?after_id=0&limit=100
Authorization: Bearer <REMARKET_SALE_API_KEY>
```

Example response:

```json
{
  "sales": [
    {
      "order_id": "RM-000001",
      "certificate_code": "KOODE0LL",
      "buyer_name": "Asha Rao",
      "status": "completed",
      "completed_at": "2026-10-14T12:00:00+00:00"
    }
  ],
  "next_after_id": 1
}
```

Poll again with `after_id=1`; save `next_after_id` after processing the page. Results are ordered by sale ID, include only completed sales with a certificate code, and have a maximum `limit` of 100. Retain failed order IDs for retry or manual review.

For one order:

```http
GET https://<public-remarket-host>/api/v1/sales/RM-000001
Authorization: Bearer <REMARKET_SALE_API_KEY>
```

The single-order endpoint returns the sale object directly. It returns `404` for an unknown order, `401` for a missing or wrong key, and `503` when the ReMarket server has no key configured. A sale without a certificate can be fetched by order ID but is absent from the list, since no CraftProof ownership transfer applies.

## CraftProof side

CraftProof's current [OpenAPI specification](https://craftproof-backend.onrender.com/openapi.json) defines a transfer request with `to_name`, optional `to_user_id`, and optional `note`. It does not include an address field. Its existing protected transfer route uses a CraftProof piece ID, so CraftProof must implement the certificate-code lookup and import process on its own server. ReMarket cannot call that route using only a certificate code.

The CraftProof team should authenticate to ReMarket with the shared key, check `status=completed`, locate the certificate, validate that the sale is legitimate, and record `buyer_name` as the new holder. A name alone does not prove identity; ReMarket names are self reported. CraftProof should decide what additional validation it requires before changing ownership. ReMarket does not collect an address for this transfer because CraftProof's current transfer request does not require one.

For a live integration, host ReMarket at a public HTTPS URL. `127.0.0.1` is reachable only on the ReMarket developer's computer. Marketplace checkout is currently a simulation with no payment or physical handoff verification, so the teams should agree when a sale qualifies as final before automatically updating a real ownership record.
