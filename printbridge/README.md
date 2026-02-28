# Mozzart Print Bridge

Internal Docker service that accepts print jobs from backend (`/v1/jobs`) and forwards them to Windows print receiver hosts over Tailscale.

## Receiver contract (Windows)

`POST /print`

Headers:
- `Content-Type: application/json`
- optional `X-Bridge-Token: <PRINT_BRIDGE_RECEIVER_TOKEN>`

Body:
```json
{
  "job_id": "uuid",
  "kind": "receipt_pdf",
  "printer_name": "Star TSP100",
  "payload": {
    "filename": "pos-receipt-123.pdf",
    "pdf_base64": "..."
  },
  "meta": {
    "source": "mozzart"
  }
}
```

`kind=bar_ticket` šalje payload oblika:
```json
{
  "ticket": {
    "check_id": 123,
    "round_number": 4,
    "items": []
  }
}
```
