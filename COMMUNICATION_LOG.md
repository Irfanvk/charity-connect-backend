# Communication Log (Frontend + Backend)

**Project:** CharityConnect  
**Purpose:** Decisions, meeting minutes, and action items  
**Owner:** Integration Lead  
**Last Updated:** 2026-03-01

---

## Decision Log

| Date | Decision | Owner | Status | Notes |
|------|----------|-------|--------|-------|
| 2026-02-26 | Frontend auth redirect handled by context state (not global 401 hard redirect) | Frontend | ✅ | Prevents login loop and session bounce |
| 2026-02-26 | Login success flow updates context session immediately | Frontend | ✅ | Removes race between login and auth guard |
| 2026-02-26 | Logout action must be visible in app shell for authenticated users | Frontend | ✅ | Added header-level logout button |
| 2026-02-26 | Public app settings call is optional when app_id missing | Frontend | ✅ | Skip endpoint to avoid 404 noise |
| 2026-02-24 | Use resource-specific API routes (no generic /entities) | Backend | ✅ | Avoid abstraction mismatch |
| 2026-02-24 | Login accepts email and username | Backend | ✅ | Aligns with frontend Login.jsx |
| 2026-02-24 | Add /files/upload endpoint | Backend | ✅ | Matches frontend proof upload flow |
| 2026-02-24 | Registration collects username + password | Frontend | ✅ | Required for auth flow |
| 2026-02-24 | Disable RecurringDonation and Request in Phase 1 | Both | ✅ | Phase 2 feature set |

---

## Meeting Minutes

### 2026-02-24 - Phase 1 Integration Readiness
**Attendees:** Backend team, Frontend team  
**Agenda:** Align API contracts, confirm Phase 1 readiness, schedule integration testing  
**Notes:**  
- Frontend completed API client refactor, Login/Register updates, and proof upload integration.
- Backend implemented email/username login and /files/upload endpoint.
- Integration testing can start once services are running locally.

**Action Items:**
- [ ] Frontend to start integration testing using INTEGRATION_TESTING_GUIDE.md. (Owner: Frontend, Due: 2026-02-25)
- [ ] Backend to monitor auth and upload logs during testing. (Owner: Backend, Due: 2026-02-25)
- [ ] Both teams to schedule a 2-hour joint testing session. (Owner: Both, Due: 2026-02-25)

---

## Frontend Status Report (2026-02-24)

**Completed:**
- API client refactored (resource-specific routes)
- Login accepts email or username
- Registration with username + password
- ProofUpload integrated with /files/upload endpoint
- Build system working (dist/ directory produced)

**Ready for Backend Coordination:**
- Waiting on backend confirmations below

---

## Backend Confirmation Checklist

**Port Configuration:**
- Backend running on http://localhost:8000
- CORS enabled for http://localhost:5173

**Critical Endpoints:**
- POST /auth/login - Accept email or username + password
- POST /auth/register - Username + password with invite code
- POST /files/upload - File upload (3MB max, JPG/PNG/PDF)
- GET/POST /members - CRUD operations
- GET/POST /challans - CRUD operations
- GET/POST /campaigns - CRUD operations
- GET /notifications - Notification polling

**Authentication:**
- Token format confirmed (JWT bearer)
- Token expiration behavior documented
- Token location in response confirmed (access_token)

**Blockers to Flag:**
- Standardized error response format across endpoints
- Validation error format (field-level vs message-only)
- File upload response format for /files/upload

**Testing Requirements:**
- Mock/test data seeded in database
- Test user credentials shared for login testing
- Sample files available for upload testing (optional)

---

## Backend Readiness Checklist

- [ ] Backend server running on http://localhost:8000
- [ ] Swagger UI accessible at http://localhost:8000/docs
- [ ] Database reachable and tables created
- [ ] Admin test user available
- [ ] Member test user available
- [ ] Valid invite code available
- [ ] /auth/login accepts email or username
- [ ] /auth/register creates user + member with invite
- [ ] /files/upload accepts JPG/PNG/PDF under 3MB
- [ ] CORS allows http://localhost:5173
- [ ] Logs monitored during integration tests

---

## 📨 Message to Frontend Team (2026-02-24)

**Status:** Backend is ready for Phase 1 integration testing

**Backend Environment:**
- Base URL: `http://localhost:8000`
- Swagger UI: `http://localhost:8000/docs`
- CORS: Enabled for `http://localhost:5173`

**Test Credentials:**
```
Admin User:
  Email: admin@charityconnect.com
  Username: admin
  Password: [TO BE SEEDED - Backend will provide]

Member User:
  Email: member@charityconnect.com
  Username: testmember
  Password: [TO BE SEEDED - Backend will provide]

Valid Invite Code: [TO BE SEEDED - Backend will provide]
```

**Endpoint Contracts:**

1. **POST /auth/login**
   - Request: `{ "email": "...", "password": "..." }` OR `{ "username": "...", "password": "..." }`
   - Success: `200 { "access_token": "eyJ...", "token_type": "bearer" }`
   - Error: `401 { "detail": "Invalid credentials" }`

2. **POST /auth/register**
   - Request: `{ "username": "...", "email": "...", "password": "...", "full_name": "...", "invite_code": "..." }`
   - Success: `201 { "access_token": "...", "token_type": "bearer" }`
   - Error: `400 { "detail": "Invalid invite code" }` or `409 { "detail": "Email/username already exists" }`

3. **POST /files/upload**
   - Request: `multipart/form-data` with `file` field
   - Success: `200 { "file_url": "/uploads/proofs/uuid-filename.jpg", "filename": "uuid-filename.jpg" }`
   - Error: `400 { "detail": "File too large (max 3MB)" }` or `400 { "detail": "Invalid file type. Only JPG, PNG, PDF allowed" }`

**Standard Error Response Format:**
```json
{
  "detail": "Human-readable error message"
}
```

**Authentication Header:**
```
Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
```
- Token expires in 60 minutes
- Include header in all protected endpoint requests

**Next Steps:**
1. Backend team will seed test users and invite code (ETA: within 1 hour)
2. Backend will share actual credentials via this log
3. Frontend can begin testing sequence from INTEGRATION_TESTING_GUIDE.md:
   - T1: Login with Email
   - T2: User Registration
   - T3: File Upload with Proof
4. Schedule 2-hour joint testing session for real-time issue resolution

**Questions or Blockers?**
- Add them to "Open Questions" section below

---

## Open Questions
- Backend: confirm canonical login token key (`access_token` preferred) and keep backward compatibility for existing key variants during transition.
- Backend: confirm `/auth/me` returns a full user object for valid token in all environments.
- Backend: confirm `/health` endpoint availability and expected lightweight response.

---

## 2026-02-26 - Frontend to Backend Communication (Auth Stabilization)

**Summary:** Frontend patch 1.1 resolved login-loop/logout-visibility issues and now requests contract confirmations below.

### Items to Communicate to Backend

1. **Token response contract alignment**
   - Frontend now accepts `access_token`, `accessToken`, `token`, and nested `data.*` variants.
   - Request backend to standardize on `access_token` as canonical response key.

2. **/auth/me reliability requirement**
   - If token is valid: return full user payload.
   - If invalid/expired: return `401` only.
   - Avoid returning `200` with null body for authenticated checks.

3. **Public settings by app id behavior**
   - Frontend now skips `GET /api/apps/public/prod/public-settings/by-id/{appId}` when app id is not configured.
   - Request backend to document expected response for missing/invalid app id.

4. **Health endpoint contract**
   - Frontend startup checks `GET /health`.
   - Request backend to keep this endpoint stable and unauthenticated for reachability checks.

### Frontend Validation Completed

- `npm run lint` → ✅ Pass
- `npm run build` → ✅ Pass

---

## 2026-02-26 - Backend Contract Follow-up (Post-Review)

**Status:** Backend updated for auth contract alignment.

### Backend Changes Applied

1. **`POST /auth/register` response aligned**
   - Now returns token payload shape:
     - `access_token`
     - `token_type`
     - `user`
   - Status code set to `201`.

2. **Register request backward compatibility improved**
   - `full_name` is now accepted as an optional field in register payload (ignored by backend for now).

3. **Conflict responses standardized for registration**
   - Duplicate username → `409`.
   - Duplicate email → `409`.

4. **`GET /auth/me` invalid-auth behavior tightened**
   - Missing/invalid/stale token now returns `401` (no null/200 fallback).

### What Frontend Should Do

1. Prefer `access_token` as canonical key (existing fallback handling can remain temporarily).
2. For registration flow, consume returned token directly after successful `201`.
3. Handle `409` in registration UI for duplicate username/email.

### Notes

- `/health` remains stable and unauthenticated.
- `/files/upload` contract remains aligned (`file_url`, `filename`; JPG/PNG/PDF up to 3MB).

---

## 2026-03-01 - Backend to Frontend Communication (Unauthorized Triage)

**Summary:** Frontend reported `Unauthorized`. Backend reviewed and aligned auth/authorization behavior to match frontend expectations and role-based route access.

### Backend Findings

1. **Service reachability affects auth checks**
   - If backend is down/unreachable on `http://localhost:8000`, frontend may surface auth-like failures.
   - `GET /health` remains the first startup verification endpoint.

2. **Role check mismatch fixed in backend routes**
   - Some route logic was checking `current_user.is_admin` (non-existent in JWT payload).
   - Updated to role-based checks using JWT `role` (`admin`/`superadmin`).

3. **Current token payload contract (canonical)**
   - `access_token` contains JWT with `sub` and `role` claims.
   - Frontend should continue using `Authorization: Bearer <token>` for protected endpoints.

### Frontend Contract Alignment (Actionable)

1. **Use role-appropriate endpoints**
   - Member self profile: `GET /members/me`.
   - Member attempting `GET /members/` should expect authorization denial (admin-only route).

2. **Auth error handling expectation**
   - Invalid/missing/expired token: backend returns `401` with `{ "detail": "Invalid token" }`.
   - Permission mismatch (valid token, wrong role): backend returns `403`.

3. **Startup check sequence**
   - Step 1: Confirm `GET /health` is reachable.
   - Step 2: Perform `POST /auth/login` and store `access_token`.
   - Step 3: Confirm session via `GET /auth/me`.

### Status for Frontend Team

- Backend auth contract remains: canonical token key is `access_token`.
- Register flow remains: `POST /auth/register` returns `201` with token payload.
- Unauthorized triage fix is applied on backend side for member/challan role checks.

---

## Reference Links
- INTEGRATION_TESTING_GUIDE.md
- CHANGE_REPORT.md
