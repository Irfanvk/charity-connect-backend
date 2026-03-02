# API Contract Baseline (v1)

This file defines the integration source of truth for frontend/backend API behavior.

## Source of Truth
- OpenAPI (versioned): `/openapi/v1.json`
- Interactive docs: `/docs`

## Canonical Contract Rules
- Registration flow is 2-step:
  - Step 1: invite verification in UI
  - Step 2: `POST /auth/register`
- Register request payload supports:
  - `invite_code`, `username`, `password`, `email`, `full_name`, `phone`, `address`, `monthly_amount`
- Invite create canonical field: `expiry_date`
- Invite create backward-compatible alias: `expires_at` (temporary compatibility window)
- Invite code format: `INV-XXXXXX`
- Invite acceptance rules are backend-enforced:
  - invite must exist
  - invite must be pending/unused
  - invite must be unexpired
  - invite is single-use
- Invite list endpoint is available for frontend verification/admin flows:
  - `GET /invites/`
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

## Role + Donation Policy Matrix

Umbrella identity stays in `users` (`role`: `member`, `admin`, `superadmin`).
Donation eligibility is determined by linked member profile status.

- Can administer = `role in {admin, superadmin}`
- Can donate = active linked member profile exists

### Behavior Matrix

| User Role | Has Active Member Profile | Can Donate (Self) | Can View Own Challans | Can Create/Approve on Behalf |
|-----------|---------------------------|-------------------|-----------------------|------------------------------|
| member | yes | ✅ | ✅ | ❌ |
| member | no | ❌ | ❌ | ❌ |
| admin | yes | ✅ | ✅ | ✅ |
| admin | no | ❌ | ❌ | ✅ |
| superadmin | yes | ✅ | ✅ | ✅ |
| superadmin | no | ❌ | ❌ | ✅ |

### Endpoint Rules

- `GET /members/me` and self donation endpoints require linked active member profile.
- Admin-only routes remain role protected regardless of member profile.
- On-behalf actions remain restricted to `admin`/`superadmin`.

## Notes
- `GET /invites/pending` remains available.
- Contract-impacting path/method changes must be recorded in `API_CHANGELOG.md`.
