# API Changelog

## 2026-03-02

### Changed
- Notification create is treated as canonical on `POST /notifications/` (admin-only).
- Notification ownership scope is enforced for:
  - `GET /notifications/{notification_id}`
  - `PUT /notifications/{notification_id}/read`
- Non-owned notification access returns `404` by design.
- `POST /notifications/mark-all-read` returns `{ marked_read, message }`.
- `GET /notifications/unread/count` uses SQL count-based lookup.

### Removed
- `POST /notifications/send` is no longer considered available in active integration flows.

## 2026-03-01

### Added
- `GET /users/` (admin user list with filtering)
- `GET /audit-logs/` (admin audit log list)
- `POST /audit-logs/` (admin audit log create)
- `GET /invites/` (admin full invite list with filters/sort/pagination)
- `GET /invites/{invite_id}` (invite detail)
- `PUT /invites/{invite_id}` (invite update)
- `PUT /notifications/{notification_id}` (admin notification update)
- `DELETE /notifications/{notification_id}` (admin notification delete)

### Changed
- OpenAPI contract path is now versioned at `/openapi/v1.json`.
- Invite create (`POST /invites/`) supports `expiry_date` (canonical) and `expires_at` (compatibility alias).
- Invite code generation format aligned to `INV-XXXXXX`.
- Challan action routes canonicalized to:
  - `PATCH /challans/{id}/approve`
  - `PATCH /challans/{id}/reject`

### Deprecated
- `POST /notifications/send` is deprecated. Use `POST /notifications/`.

### Contract Behavior
- Error responses for 4xx/5xx are normalized to `detail[]` shape with `type`, `loc`, `msg`, `input`.
