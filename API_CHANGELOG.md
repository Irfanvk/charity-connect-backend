# API Changelog

## 2026-03-08

### Changed
- **Authentication Enhancement**: Login now accepts either username OR email in the `username` field
  - Backend automatically detects whether the provided value is a username or email
  - Improved error messages: "Invalid username/email or password" instead of generic "Invalid credentials"
  - Frontend updated: Single "Username or Email" field replaces separate email field
  - File: `app/services/auth_service.py` - Updated login() method to accept single identifier field and try username first, then email
  - File: `src/pages/Login.jsx` - Changed credentials state from email to username; updated label to "Username or Email"

### Fixed
- **Admin Bulk Operations**: Fixed 500 error on `GET /admin/bulk-pending-review`
  - Root cause: Admin routes using `current_user.role` (attribute access) while auth middleware returns dict
  - Solution: Added `_is_admin_role()` helper function to safely access dict-based role
  - Applied consistent fix to all 4 admin endpoints: `get_pending_bulk_operations`, `get_bulk_challan_details`, `approve_bulk_challans`, `reject_bulk_challans`
  - File: `app/routes/admin_router.py` - Refactored role checking to use helper function
  - Status: GET /admin/bulk-pending-review now returns 200 with bulk operation data

- **Audit Logs**: Fixed 422 validation error when frontend sends empty `user_id` query parameter
  - Root cause: Frontend sends `user_id=` (empty string), FastAPI validation rejected with int_parsing error
  - Solution: Changed `user_id` from `Optional[int]` to `Optional[str]`, added normalization logic
  - Backend now skips empty/"all"/"null"/"undefined" values, returns 400 for non-numeric values
  - Frontend query builder now filters out empty/null/undefined query parameters before URL building
  - Audit log normalizer maps backend fields (`action`, `user_id`, `entity_type`) to frontend names (`action_type`, `performed_by_name`, `target_name`)
  - File: `app/routes/audit_log_routes.py` - Updated user_id parameter handling
  - File: `src/api/charityClient.js` - Enhanced buildUrl() and normalizeAuditLog() functions
  - File: `src/pages/AuditLogs.jsx` - Hardened filter logic with null-safe access
  - Status: GET /audit-logs now returns 200 with properly formatted audit records

### Security
- **Username Uniqueness**: Enforced unique username constraint across all users
  - Backend: Database UNIQUE constraint on users.username column; registration returns `409 Conflict` if duplicate
  - Validation: Lines 86-89 in `app/services/auth_service.py` check for existing username before creating user
  - Frontend: Enhanced `src/pages/Register.jsx` with real-time username validation
  - Features: 3-30 character limit, alphanumeric + underscore/hyphen only, real-time green/red feedback
  - File: `src/pages/Register.jsx` - Added validateUsername() function and inline validation display
  - Testing: Comprehensive end-to-end testing verified duplicate rejection returns 409 CONFLICT with "Username already taken" message
  - Status: All 5 test scenarios passed; username uniqueness fully enforced

## 2026-03-07

### Changed
- Database maintenance tooling was consolidated to reduce repo artifacts:
  - `optimize_database.py` now contains embedded index optimization SQL (no external SQL dependency).
  - `fix_missing_members.ps1` now contains embedded migration SQL and runs without `fix_missing_members.sql`.
- `fix_missing_members.ps1` role matching is now case-safe using `LOWER(role::text) = 'member'` for broader enum compatibility.
- Notification delivery now guarantees sender-admin visibility:
  - when admin sends a notification, a copy is also stored for the sending admin if they were not already a recipient.

### Added
- `GET /notifications/admin/sent`
  - Admin panel endpoint for grouped sent-notification batches with audience diagnostics.
  - Supports filters: `minutes`, `audience_filter` (`all|members|admins|superadmins`), `skip`, `limit`.
- `DELETE /notifications/admin/sent`
  - Admin panel endpoint to remove a sent batch by `batch_created_at + title + message`.
  - Supports scoped deletion via `recipient_scope` (`all|members|admins|superadmins`).

### Removed
- `fix_missing_members.sql` (replaced by self-contained PowerShell script logic).
- `db_optimize_indexes.sql` (replaced by self-contained Python optimization script logic).

### Notes
- No external API route or payload contract changes were introduced in this entry.

## 2026-03-02

### Changed
- Notification create is treated as canonical on `POST /notifications/` (admin-only).
- Notification ownership scope is enforced for:
  - `GET /notifications/{notification_id}`
  - `PUT /notifications/{notification_id}/read`
- Non-owned notification access returns `404` by design.
- `POST /notifications/mark-all-read` returns `{ marked_read, message }`.
- `GET /notifications/unread/count` uses SQL count-based lookup.
- Auth/member profile responses now include `full_name` (`GET /auth/me`, `GET /members/me`) for dashboard welcome-name rendering.

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
