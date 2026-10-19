# ReMarket → CraftProof ownership transfer

This is the API contract for the CraftProof team. The ReMarket endpoints and CraftProof importer work on this computer with a local API key. The CraftProof fork has not been pushed or deployed, so the online CraftProof service is not connected to this local ReMarket server.

## Flow

1. The seller lists an item with its CraftProof certificate code.
2. A ReMarket purchase creates a completed sale. ReMarket saves the certificate code and buyer name at purchase time.
3. CraftProof reads the ReMarket sale API. It finds the item internally by certificate code and checks that the sale's item title matches the certificate's item title.
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
      "item_title": "Speckled tea bowl set",
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

CraftProof's existing [OpenAPI specification](https://craftproof-backend.onrender.com/openapi.json) defines a transfer request with `to_name`, optional `to_user_id`, and optional `note`. It does not include an address field. Its protected transfer route uses a CraftProof piece ID, so the local fork adds a separate importer that looks up the piece by certificate code. ReMarket does not call the protected transfer route.

The local importer authenticates to ReMarket with the shared key, checks `status=completed`, locates the certificate, and requires `item_title` to match the certificate title, ignoring case and repeated spaces. A mismatch is skipped and retried on later syncs; it never changes the wrong certificate. A matching sale records `buyer_name` as the new holder once per `order_id`. It signs the record as a ReMarket integration service, not as the previous owner. A matching title is only a safety check, not proof of seller authority. CraftProof must decide how to validate the seller's authority and whether such sales should update real certificates. ReMarket does not collect an address for this transfer because CraftProof's current transfer request does not require one.

For a live integration, host ReMarket at a public HTTPS URL. `127.0.0.1` is reachable only on the ReMarket developer's computer. Marketplace checkout is currently a simulation with no payment or physical handoff verification, so the teams should agree when a sale qualifies as final before automatically updating a real ownership record.
