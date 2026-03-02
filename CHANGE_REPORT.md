# Change Report

**Scope:** From 2026-02-24 forward  
**Owner:** Release Manager

---

## 2026-02-24

### Backend
- [Added] POST /files/upload endpoint (3MB, jpg/png/pdf).
- [Changed] Login accepts email or username.
- [Changed] Auth service login flow queries by username or email.

### Frontend
- [Changed] Integration flow aligned to resource-specific routes (per frontend status).
- [Changed] Proof upload uses /files/upload (per frontend status).

### Docs
- [Added] COMMUNICATION_LOG.md template populated.
- [Changed] INTEGRATION_TESTING_GUIDE.md populated for Phase 1 testing.
- [Changed] CHANGE_REPORT.md populated and scoped.
- [Removed] Redundant integration docs moved to archive/.

### Notes
- Risks: Integration testing results pending.
- Follow-ups: Schedule joint testing session and record findings.
- Added frontend status report and backend confirmation checklist to integration guide.

---

## 2026-02-26

### Backend
- [Changed] `POST /auth/register` now returns token payload (`access_token`, `token_type`, `user`) with HTTP `201`.
- [Changed] Register schema now accepts optional `full_name` for frontend payload compatibility.
- [Changed] Registration duplicate checks now return HTTP `409` for username/email conflicts.
- [Fixed] JWT `sub` claim now stored as string; token parsing converts `sub` to integer safely.
- [Fixed] `/auth/me` authentication flow now validates tokens correctly after login (resolved `401 Invalid token` caused by JWT subject type mismatch).
- [Changed] Missing/invalid bearer token handling returns HTTP `401` consistently in auth dependency.

### Validation (Smoke Test)
- [Passed] `GET /health` → `200` with healthy payload.
- [Passed] `GET /` → `200` with app metadata payload.
- [Passed] `POST /auth/login` (admin credentials) → `200` and token returned.
- [Passed] `GET /auth/me` with bearer token → `200` and correct user response.
- [Passed] `POST /invites/` (admin token) → `201` and invite code generated.
- [Passed] `POST /auth/register` with valid invite → `201` and token + user returned.

### Frontend Coordination
- [Inform] Treat `access_token` as canonical key in auth responses.
- [Inform] Handle registration conflict responses using HTTP `409` for duplicate username/email.
- [Inform] Frontend can use token returned from register success directly (no forced separate login step required).

---

## 2026-03-01

### Backend
- [Fixed] Authorization checks in member/challan routes now rely on JWT `role` (`admin`/`superadmin`) instead of non-existent `is_admin` field.
- [Fixed] Added missing `HTTPException` import in member routes to prevent runtime errors in access-control branches.
- [Changed] Added null-member guards in challan ownership checks for safer protected endpoint behavior.

### Impact
- Prevents incorrect access failures on protected routes after valid login.
- Clarifies role-based behavior: admin-only endpoints still return authorization errors for member tokens by design.

### Frontend Coordination
- [Inform] `401` indicates missing/invalid/expired token; `403` indicates valid token but insufficient role/permission.
- [Inform] Member clients should use self routes (e.g., `GET /members/me`) and should not expect `GET /members/` access.
- [Inform] Frontend should run startup health check (`GET /health`) before authenticated request flow.

### Validation Notes
- [Observed] Frontend-reported `Unauthorized` can also occur when backend service is unreachable.
- [Action] Triage guidance and endpoint-role expectations were added to `COMMUNICATION_LOG.md` for frontend handoff.

### Docs
- [Changed] `COMMUNICATION_LOG.md` updated with `2026-03-01 - Backend to Frontend Communication (Unauthorized Triage)` section.

---

## 2026-03-01 (Contract Freeze + Admin API Expansion)

### Backend
- [Added] Versioned OpenAPI contract endpoint: `GET /openapi/v1.json`.
- [Changed] Standardized error responses for 4xx/5xx to `detail[]` shape (`type`, `loc`, `msg`, `input`).
- [Changed] Invite create contract now accepts canonical `expiry_date` plus backward-compatible alias `expires_at` (transition window).
- [Added] Admin invite management endpoints:
	- `GET /invites/` (filters/sort/pagination)
	- `GET /invites/{invite_id}`
	- `PUT /invites/{invite_id}`
- [Added] Admin utility endpoints:
	- `GET /users/`
	- `GET /audit-logs/`
	- `POST /audit-logs/`
- [Added] Notification admin management:
	- `PUT /notifications/{notification_id}`
	- `DELETE /notifications/{notification_id}`
- [Added] Deprecated transition alias: `POST /notifications/send` (canonical remains `POST /notifications/`).
- [Changed] Challan action contract finalized on `PATCH` methods:
	- `PATCH /challans/{challan_id}/approve`
	- `PATCH /challans/{challan_id}/reject`
- [Changed] Challan role flows aligned:
	- Admin can create challans on behalf of active members.
	- Admin can upload/re-upload proof on behalf of members.
	- Rejected challans now support proof re-upload and transition back to `pending`.

### Docs
- [Added] `API_CONTRACT_BASELINE.md` as frontend/backend source of truth for v1 contract.
- [Added] `API_CHANGELOG.md` for path/method and compatibility history.
- [Changed] `ALIGNMENT_REPORT.md` updated with current endpoint inventory and counts.
- [Changed] `COMMUNICATION_LOG.md` updated with:
	- frontend migration checklist
	- contract freeze guidance
	- reference links to baseline/changelog docs

### Frontend Coordination
- [Inform] Frontend should migrate to canonical fields/paths this cycle:
	- invites: prefer `expiry_date`
	- notifications: use `POST /notifications/`
	- challan actions: use `PATCH` approve/reject endpoints
- [Inform] Backward compatibility retained temporarily for one release (`expires_at`, `/notifications/send`).

---

## 2026-03-02

### Backend
- [Fixed] Resolved `POST /invites/` runtime `500` caused by timezone-aware vs timezone-naive datetime comparison.
- [Changed] Invite expiry handling now normalizes datetime values to UTC-naive before validation/storage.
- [Changed] Invite validation flow now safely compares normalized expiry timestamps (prevents aware/naive comparison crash).
- [Changed] Invite code generation aligned to frontend display/usage format: `INV-XXXXXX`.

### Impact
- Prevents invite-creation failures when frontend sends ISO datetimes with `Z` timezone suffix.
- Keeps frontend payload compatibility intact (`expiry_date` canonical with temporary `expires_at` fallback).

### Frontend Coordination
- [Inform] No immediate frontend payload change required for timezone format; backend now handles timezone-aware values safely.
- [Inform] Frontend should continue using canonical `expiry_date` field for long-term contract stability.

### Docs
- [Changed] `API_CONTRACT_BASELINE.md` updated with registration + invite contract details (2-step flow, field set, invite validity rules).
- [Changed] `API_CHANGELOG.md` updated with invite code format alignment note.
- [Changed] `COMMUNICATION_LOG.md` updated with backend acknowledgment section for registration/invite contract handoff.

---

## 2026-03-02 (Notification API Update)

### Backend
- [Changed] Notification create API is now canonical on `POST /notifications/` (admin only).
- [Changed] Notification route set includes admin update/delete endpoints: `PUT /notifications/{notification_id}` and `DELETE /notifications/{notification_id}`.
- [Changed] Notification read APIs are user-scoped and ownership-checked (`GET /notifications/{notification_id}`, `PUT /notifications/{notification_id}/read`).
- [Changed] Service-level mark-all-read now uses a bulk update and returns `{ marked_read, message }`.
- [Changed] Service-level unread count uses SQL `COUNT` for efficient polling.

### Frontend Coordination
- [Inform] Use `POST /notifications/` as the only create endpoint in active flows.
- [Inform] Keep notification detail/read requests user-scoped; non-owned IDs return `404` by design.
- [Inform] Update any remaining assumptions that `/notifications/send` is available.

### Docs
- [Changed] `CHANGE_REPORT.md` and `COMMUNICATION_LOG.md` updated to reflect current notification contract behavior.
