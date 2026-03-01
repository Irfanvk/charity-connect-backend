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
