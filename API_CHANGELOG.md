# API Changelog

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
- Challan action routes canonicalized to:
  - `PATCH /challans/{id}/approve`
  - `PATCH /challans/{id}/reject`

### Deprecated
- `POST /notifications/send` is deprecated. Use `POST /notifications/`.

### Contract Behavior
- Error responses for 4xx/5xx are normalized to `detail[]` shape with `type`, `loc`, `msg`, `input`.
