# API Contract Baseline (v1)

This file defines the integration source of truth for frontend/backend API behavior.

## Source of Truth
- OpenAPI (versioned): `/openapi/v1.json`
- Interactive docs: `/docs`

## Canonical Contract Rules
- Invite create canonical field: `expiry_date`
- Invite create backward-compatible alias: `expires_at` (temporary compatibility window)
- Challan actions canonical methods:
  - `PATCH /challans/{id}/approve`
  - `PATCH /challans/{id}/reject`
- Notification create canonical endpoint:
  - `POST /notifications/`
- Deprecated notification create alias:
  - `POST /notifications/send` (deprecated)

## Error Shape Standard
All 4xx/5xx responses are normalized to:

```json
{
  "detail": [
    {
      "type": "...",
      "loc": ["..."],
      "msg": "...",
      "input": "..."
    }
  ]
}
```

## Admin API Baseline
- `GET /users/`
- `GET /audit-logs/`
- `POST /audit-logs/`
- `GET /invites/`
- `GET /invites/{invite_id}`
- `PUT /invites/{invite_id}`
- `PUT /notifications/{notification_id}`
- `DELETE /notifications/{notification_id}`

## Notes
- `GET /invites/pending` remains available.
- Contract-impacting path/method changes must be recorded in `API_CHANGELOG.md`.
