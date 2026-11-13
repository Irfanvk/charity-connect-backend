# API Changelog

## 2026-11-13

### Bulk (multi-month) payments: amount, proof, review rules
- **Amount:** for a member's own monthly payment the server always uses `members.monthly_amount`. `amount_per_month` (`POST /challans/bulk-create`) and `amount` (`POST /challans/`, `POST /challans/multi`) are ignored for those; a member with no fee gets 400 "Your monthly amount is not set yet". An admin entering a payment for someone else may still send a different amount (> 0).
- **Who entered it:** a bulk payment an admin enters for another member is stored with `entry_source = "admin"`, so a different admin must approve it (403 otherwise). Approval is also refused to the admin who created the group, which covers groups saved before this change.
- **Proof:** members must send `proof_file_id` (400 otherwise). An admin may leave it out only with `notes` as the reason (minimum reason length). A missing proof never becomes a `proof_url`; list and details return `has_proof: false`.
- **Same month twice:** new payments are refused for a month that is approved or waiting (not only generated/pending). `PATCH /admin/bulk/{id}/approve` returns 409 if a month already has another payment, and `PATCH /admin/bulk/{id}/revert` of a rejected group returns 409 with `duplicate_months` if any month was submitted again.
- **Reject keeps records:** `PATCH /admin/bulk/{id}/reject` always marks the months rejected and keeps the reason; `action: "delete"` (older apps) is treated as `"reject"`, and `action` now defaults to `"reject"`. Rejecting an already rejected group returns 400. Reverting a group whose months were deleted by an older version returns 400.
- **Review list:** `GET /admin/bulk-pending-review` has no age limit by default (`days` is now optional, up to 3650) and takes `status=pending_approval|approved|rejected|all`. `pending` is always the number waiting; new `total` is the number matching `status`. Items add `member_code`, `created_by_user_id`, `created_by_name`, `entered_by_admin`, `has_proof`, `approved_at`, `approved_by_name`, `rejected_at`, `rejection_reason`, `reversal_reason`, `challans_missing`. `member_name` is the member's full name (was the username). `GET /admin/bulk/{id}` adds the same review fields plus `member_user_id`.
- **Locking:** approve, reject and revert lock the group row (`SELECT ... FOR UPDATE`), so two admins acting at once cannot both succeed.
- **Errors:** unexpected errors in bulk create and review return 500 "Something went wrong and nothing was changed. Please try again." and are logged; the raw exception is no longer sent. Error details that carry months now read as one sentence, e.g. "Challan already exists for one or more months: 2026-08, 2026-09"; the structured data stays in `detail[0].input`.

## 2026-11-12

### "Not paid yet" months and the monthly fee
- The 2026-04 import created a `pending` challan, with nothing attached, for every month a member had not paid. A challan now counts as **submitted** only if it is approved or rejected, has a proof (`proof_path` / `proof_uploaded_at`), belongs to a bulk payment (`bulk_group_id`), or was recorded by an admin (`entry_source = admin`). Otherwise it means "not paid yet". Shared rule: `app/services/challan_state.py`.
- `ChallanResponse` adds `submitted: bool`. It is `false` for "not paid yet"; clients without the field should treat it as `true`.
- `GET /challans/?submitted=true|false` filters on that. The admin review list and the nav badge use `status=pending&submitted=true`.
- Monthly fee: months not paid yet always use the member's current `monthly_amount`. They are updated when an amount-change request is approved, and when an admin edits the member. Paid, submitted or rejected challans keep the amount actually paid.
- Payment reminders treat a month as paid only if it is approved, or pending with something handed in. Before this, imported "not paid yet" months wrongly skipped the reminder.
- One-off data correction: `scripts/vps-fix-unpaid-amounts.sh` in CharityConnect. It previews first, saves the old amounts to CSV, then corrects them in one transaction.

## 2026-11-11

### App version tracking
- `POST /users/me/device-status` accepts optional `app_version` (`[0-9A-Za-z._-]`, max 40), stored as `users.app_version` + `app_version_seen_at`. Older clients that do not send it keep working.
- `GET /admin/notifications/delivery-overview` adds `latest_app_version`, `by_app_version` (`"not reported"` for devices that never sent one), `users_on_latest_version`, and per user `app_version`, `app_version_seen_at`, `on_latest_version`. Builds are named `YYYYMMDD.HHMM-<commit>` so the largest is the newest.
- Schema (additive, applied at startup; fallback `migrations/20261111_app_version.sql`): `users.app_version VARCHAR(40)`, `users.app_version_seen_at TIMESTAMP`.

### Celery workers (optional)
- New env `CELERY_WORKERS_ENABLED` (default `false`). Push delivery, deferred quiet-hours pushes and queued notifications go to Celery only when it is `true` **and** the broker answers. Before, a reachable Redis alone was enough, so with Redis but no worker the tasks sat in the queue and pushes were never sent. With it `false` everything is sent directly from the API, as before.
- Production (applied 2026-11-10): Redis and the worker are running, `CELERY_WORKERS_ENABLED=true` is set, and web push keys were created (push was not configured before).
- VPS worker: `charity-celery.service` (`celery -A app.workers.celery_app:celery worker -Q notifications,default --concurrency=2`), `PartOf=charity.service` so every deploy restart also restarts the worker. No Celery beat: monthly reminders run inside the API.

### Monthly payment reminders (per member)
- Each member picks their reminder day (1-28). Default: on, on the organisation's `monthly_reminder_day`. A reminder is skipped when that month already has an approved or pending (submitted) monthly challan; one follow-up is sent 7 days later (capped at month end) if still unpaid. At most two per member per month; logged in the new `payment_reminder_logs` table (unique member + month + kind), so reruns, restarts and multiple workers never duplicate. Sent up to 2 days late if the server was down.
- Runs inside the API process (checks every 30 min from 09:00 IST; env `PAYMENT_REMINDER_SCHEDULER=false` turns it off). Celery is no longer needed for reminders; the Celery task `send_monthly_membership_reminders` now calls the same code.
- Notifications use `category: reminders`, `type: payment`, `link_url: /Challans`. New template setting `msg_monthly_reminder_followup`; `{amount}` is now formatted like `₹1,000`.
- `GET /notifications/preferences` adds `payment_reminder: {enabled, day, uses_default_day, default_day, applies, organisation_enabled}`. `PUT /notifications/preferences` accepts `payment_reminder_enabled` and `payment_reminder_day` (1-28).
- `POST /auth/me/onboarding {address?, payment_reminder_enabled?, payment_reminder_day?}` saves the first-login setup on the server and sets `onboarding_completed_at`. The address is saved directly only if the member has none; otherwise the response says `address_needs_approval: true` and the app sends a profile request.
- `UserResponse` adds `payment_reminder_enabled`, `payment_reminder_day`, `onboarding_completed_at`.
- Schema (additive, applied at startup; fallback `migrations/20261111_payment_reminders.sql`): table `payment_reminder_logs`; `users.payment_reminder_enabled BOOLEAN`, `users.payment_reminder_day INTEGER`, `users.onboarding_completed_at TIMESTAMP`.

### Member self-activation (existing members, admin approval)
Existing (imported) members activate their own account with their Member ID instead of an admin sending each one an invite link. Invite registration is unchanged.
- `GET /member-activations/availability` (public): `{enabled}` from the new superadmin setting `self_activation_enabled` (bool, default `true`, Security).
- `POST /member-activations` (public): `{member_code, full_name, phone, email?, no_email, whatsapp_phone?, username, password, last_paid_month?}`. `member_code` accepts `12`, `0012`, `#12`, `MEM-0012`. Email is required unless `no_email` is true, in which case `whatsapp_phone` is required. `last_paid_month` is optional `YYYY-MM`. Returns `201 {id, status: "pending", member_code, updated, message}`.
  - `404` unknown Member ID; `409` Member ID already active, username/phone/email used by another account, username held by another pending request, or 3 pending requests for that ID; `400` invalid fields; `403` turned off; `429` more than 5 attempts per IP per hour.
  - A resubmission by the same person (same phone or username) for the same Member ID updates the pending request in place. Admins are notified (`category: admin_requests`, `entity_type: member_activation`, `link_url: /admin/requests?tab=activations&request={id}`).
  - Nothing on the member's account changes until approval. The password is stored hashed on the request.
- `POST /auth/login` with the credentials of a pending or rejected activation (no account yet) returns `403` with `detail[0].type` = `activation_pending` | `activation_rejected` and `detail[0].input` = `{member_code, full_name, submitted_at}` or `{member_code, full_name, reason, reviewed_at}`. Wrong passwords stay `401`.
- Admin: `GET /member-activations?status=pending|approved|rejected|all&skip&limit` returns `{items, total, pending_total}`; `GET /member-activations/{id}`; `POST /member-activations/{id}/approve {admin_notes?}`; `POST /member-activations/{id}/reject {rejection_reason, admin_notes?}` (reason at least `min_reason_length`). Items include `record` (what is on file: member code, name, phone, email, status, monthly amount, months paid, last paid month) and `checks` (`name`: match | close | different, `last_paid_month`: match | different | not_given | no_records, `already_active`, `other_pending`, `conflicts`).
- Approve sets the existing member user's username, password, phone, email, WhatsApp and `is_active = true`, keeps the member record and payment history, auto-rejects other pending requests for the same Member ID, writes an audit log, and sends the member a welcome notification. `409` if the account became active meanwhile or a username/phone/email conflict appeared.
- `GET /auth/check-username` also reports usernames held by pending activations as unavailable.
- `UserResponse` adds `whatsapp_phone` and `welcome_pending`. `GET /auth/me/welcome` returns `{show, full_name, member_code, months_paid, total_paid, first_month, last_month}` while `welcome_pending` is true; `POST /auth/me/welcome/seen` clears it.
- Schema (additive, applied at startup; manual fallback `migrations/20261111_member_activation.sql`): new table `member_activations`; `users.whatsapp_phone VARCHAR(20)`, `users.welcome_pending BOOLEAN NOT NULL DEFAULT false`.

## 2026-11-10

### Member requests: email changes
- Approving a `profile_update` request with `requested_changes.email` now updates the user's email (lower-cased); previously it was silently ignored. If the email belongs to another account, approval returns `409` and the request stays pending.

### Auth: remember me
- `POST /auth/login` accepts `remember_me: bool` (default `false`). When true the token lasts `remember_me_days` (new platform setting, default 30, range 1-90, public) instead of `session_timeout_minutes`.
- `TokenResponse` adds `expires_in` (seconds) and `remember_me`.
- Remember-me tokens return `401` once the account is deactivated or its password changes, and authorize with the user's current role. Applies to the SSE stream too.
- `POST /auth/register` still returns a token; the web app no longer signs in with it and redirects to the login page instead.

### Member requests: profile photo
- Fixed: request `status` in responses is lower-case again (`pending` | `approved` | `rejected`). It had become `PENDING` etc., which hid the admin Review/Approve/Reject actions and broke the member's "request already pending" guard. Filters accept either case.
- `POST /requests/` with `requested_changes.avatar_url`: a member has at most one pending profile-photo request. A new submission updates the existing pending request in place (same `id`, no new admin notification) and deletes the superseded upload.
- `requested_changes.avatar_url` must be `null` (removal) or a URL returned by `POST /files/upload/avatar`; other URLs return `400`.
- `POST /files/upload/avatar` now stores the image temporarily (Cloudinary `<folder>/avatars_pending/`, tag `pending_avatar`). Approval moves it to `<folder>/avatars/` and rewrites `requested_changes.avatar_url`; rejection or cancellation deletes it. If the move fails, approval returns `502` and the request stays pending.

## 2026-10-31

### Notifications UX
- `Notification` rows and responses gain `category`, `link_url`, `entity_type`, `entity_id`, `is_urgent`.
- `GET/PUT /notifications/preferences` (category toggles, IST quiet hours); `POST /notifications/test-push` (superadmin may target `user_id`, audited).
- `GET /notifications/push/public-key` now returns `{enabled, public_key, key_id}`.
- `GET /admin/notifications/delivery-overview` (superadmin: all users; admin: own devices).
- Env: `VAPID_PUBLIC_KEY`/`VAPID_PRIVATE_KEY`/`VAPID_SUBJECT` (`WEB_PUSH_*` still accepted). Rotate keys with `scripts/generate_vapid_keys.py`.
- Fixed: `GET /notifications/stream` was shadowed by `/{notification_id}`; SSE frames used literal `\n`.

### Added
- **Admin-recorded payments (maker-checker)**
  - `POST /challans/admin-record` (admin/superadmin, multipart form): `member_id`, `type` (`monthly`|`campaign`), `months` (repeated or comma-separated `YYYY-MM`) or `campaign_id`, `amount_per_month`/`amount`, `payment_method` (`cash`|`bank_transfer`|`upi`|`cheque`|`other`), `transaction_ref`, `received_on` (IST date, not in the future), `collected_by_user_id`, `entry_notes`, optional `proof_file` or `proof_file_id`. Returns the created PENDING challans (one per month). Errors: `400` validation, `403` own record, `409` duplicate `transaction_ref`, `422` unavailable months.
  - `GET /admin/reports/cash-collected?month=YYYY-MM` (admin/superadmin): per collecting admin `count`, `pending_amount`, `approved_amount`, plus totals; month is the IST month of `received_on`.
  - `ChallanResponse` adds `created_by_user_id`, `created_by_name`, `entry_source`, `transaction_ref`, `received_on`, `collected_by_user_id`, `collected_by_name`, `entry_notes`.
  - `GET /settings/branding` (no auth) and `GET /settings/public`; superadmin-only platform settings endpoints with audit trail.
  - `GET /challans/payable-months` now includes `business_timezone` and an IST `current_month`.
- **Fund utilization two-person rule**: `PATCH /fund-utilizations/{id}/approve|reject|revert`; summary counts approved entries only and adds `pending_utilized_total` and `pending_count`.

### Changed
- `POST /members` now allows admin and superadmin (offline members supported). Imports remain superadmin-only.
- `POST /challans/{id}/approve` and `POST /admin/bulk/{id}/approve` return `403` when the approver created the admin-entered challan, or collected the cash (imports exempt). Reject/revert require a reason of at least 10 characters, and an approval can only be reversed by a different admin. All challan/request/reset actions on your own record return `403`.
- Password reset: admin/superadmin account resets need a superadmin; the reset link with token is returned only once in the approve response and never in list responses.
- Proof-upload notifications go to all active admins/superadmins except the uploader.

### Database
- `challans`: `created_by_user_id`, `entry_source`, `transaction_ref`, `received_on`, `collected_by_user_id`, `entry_notes`, plus reversal columns. Existing approved rows with no approver and no proof are backfilled as `import`, all others as `self`.
- `fund_utilizations`: status and approval/reversal columns (existing rows set to `approved`).
- Applied by `ensure_runtime_schema`; SQL in `migrations/20261031_separation_of_duties.sql` and `migrations/20261031_admin_recorded_payments.sql`. Alembic is not configured.
## 2026-08-31

### Fixed
- **Outstanding receivables now includes missing monthly dues**
  - `GET /challans/outstanding` now combines existing `pending`/`generated` challans with monthly dues inferred from active members' payable-month histories when a monthly challan row was never created.
  - Inferred records use `is_inferred_due=true`, retain the standard challan response shape, and do not alter or create database records. Existing pending/generated campaign and monthly challans remain included.

### Changed
- **Notification delivery moved off API request threads when Celery is available**
  - Persisted Web Push notifications now enqueue `send_web_push_notification` on the `notifications` queue. The API retains its direct-delivery fallback if the broker is unavailable.
  - Celery now uses late acknowledgements, rejects work lost with a worker, records ignored-task errors, and applies 45/60-second soft/hard task time limits.
  - Worker process commands now consume both `default` and `notifications` queues.
  - New member requests create notifications for active admins and superadmins, so request moderation does not depend on manual page refresh.

### Added
- **Superadmin user activity and notification monitoring**
  - Added `GET /admin/user-monitoring` (superadmin only) to return each user's last authenticated activity, reported browser notification permission, PWA/browser display mode, and active push-device count.
  - Added `POST /users/me/device-status` for authenticated clients to report their current browser permission (`default`, `granted`, `denied`, or `unsupported`) and display mode.
  - Added additive `users` fields for `last_seen_at`, notification-permission status/timestamp, display mode, and last activity user agent. The endpoint excludes Web Push endpoints and encryption keys.

### Operations
- **Production PostgreSQL backup and recovery tooling added**
  - Added `Backup & Restore/backup_production.ps1` to create a remote custom-format PostgreSQL dump, package it with a manifest and optional globals dump, download it locally, and verify the SHA-256 checksum.
  - Added `Backup & Restore/verify_backup.ps1` for offline checksum validation, archive inspection, PostgreSQL custom-dump signature checks, manifest display, and optional globals reporting.
  - Added `Backup & Restore/restore_production_backup.ps1` to upload and restore a selected archive, optionally restore globals, restart `charity.service`, and confirm the local `/health` endpoint.
  - Added `.cmd` wrappers and `Backup & Restore/README.md` operator guidance for backup, validation, dry-run, restore, retention, and recovery.
  - No HTTP endpoints, request/response schemas, authorization rules, or database migrations changed.

## 2026-03-18

### Git Commits (2026-03-18)

| Commit | Message | Files Changed |
|--------|---------|---------------|
| `f915b7a` | feat: add Celery worker, beat scheduler, and Redis task queue | 28 files, +586 lines |

**Commit `f915b7a` details:**
- `app/workers/celery_app.py` — Celery app factory; broker + results backend on Redis; `task_default_queue="default"` set to align worker queue with task routing
- `app/workers/tasks.py` — 4 async tasks: `send_invite_message`, `send_welcome_notification`, `send_user_notification`, `send_monthly_membership_reminders`
- `app/workers/__init__.py` — Package init
- `app/services/whatsapp_service.py` — WhatsApp dispatch stub (dev-safe, no real API key required in dev)
- `app/routes/notification_routes.py` — `GET /notifications/feed`, `PATCH /notifications/read`
- `app/routes/admin_router.py` — `GET /admin/dashboard/charts` aggregation endpoint
- `app/services/notification_service.py` — Feed query (unread-first), bulk-read logic
- `app/services/auth_service.py` — Dispatch `send_welcome_notification` on registration
- `app/services/invite_service.py` — Dispatch `send_invite_message` via Celery on invite creation
- `app/config.py` — `extra = "ignore"` added to `Settings.Config`; prevents `ValidationError` for legacy `.env` keys
- `requirements.txt` — Added `celery`, `redis`, `kombu`

### Infrastructure Fixes (found during smoke testing)

- **`app/config.py` — Pydantic extra field fix**
  - Added `extra = "ignore"` to `Settings.Config` inner class.
  - Legacy `.env` keys (`r2_endpoint_url`, `r2_bucket_name`, `r2_public_url`, `allowed_origins`, `import_default_password`) caused startup `ValidationError`; now silently ignored.

- **`app/workers/celery_app.py` — Queue routing alignment fix**
  - Added `task_default_queue="default"` to `celery.conf.update()`.
  - Without this, tasks dispatched to queue `default` were invisible to workers consuming the built-in `celery` queue, causing tasks to remain `PENDING` indefinitely.

### Added
- **Redis + Celery Infrastructure (CharityHub branding update)**
  - Added Redis/Celery settings in backend configuration.
  - Added Celery worker bootstrap and task registry under `app/workers/`.
  - Added Celery Beat monthly scheduler for membership reminders.

- **Notification Feed + Patch Read APIs**
  - `GET /notifications/feed`
    - Returns `{ items, unread_count }` for frontend notification context state.
  - `PATCH /notifications/read`
    - Supports selective read (`notification_ids`) and bulk read (`mark_all=true`).

- **Admin Dashboard Charts Endpoint**
  - `GET /admin/dashboard/charts`
  - Returns chart-ready aggregates for:
    - campaign progress
    - monthly donations
    - top donors

- **Queue-backed Notification and Messaging Tasks**
  - Added Celery tasks for:
    - invite message dispatch
    - welcome notification creation for newly registered users
    - monthly membership reminder notifications
  - Queue enqueue paths use safe synchronous fallback if worker infrastructure is unavailable.

- **New Admin Request Listing Endpoint**: `GET /admin/requests/` (admin/superadmin)
  - Returns paginated envelope with filters (`status`, `request_type`, `search`, `skip`, `limit`).
  - Designed for request moderation UI and pending badge counters.

- **Request Moderation Endpoints**
  - `PATCH /requests/{id}/approve`
  - `PATCH /requests/{id}/reject`
  - Admin actions now include optional notes/rejection reason and emit notifications + audit logs.

### Changed
- **Request Domain Migrated to v2.12 Lifecycle**
  - `POST /requests/`, `GET /requests/`, `GET /requests/{id}`, `DELETE /requests/{id}` now operate on new `member_requests` records.
  - Request types changed to:
    - `monthly_amount_change`
    - `profile_update`
    - `complaint`
    - `suggestion`
    - `general`
  - Request statuses standardized to:
    - `pending`
    - `approved`
    - `rejected`

- **Approval Side Effects**
  - Approving `monthly_amount_change` applies `requested_amount` to member monthly amount.
  - Approving `profile_update` applies structured `requested_changes` to member profile.

- **Wipe Endpoint Alignment**
  - `POST /admin/system/wipe` request deletion scope updated to clear `member_requests` counts.

### Infrastructure
- Added additive schema support for `members.notes`.
- Added SQL migration script: `migrations/20260318_member_requests.sql`.
- Added optional Cloudflare R2 support for file uploads with local fallback.

## 2026-03-16

### Changed
- **Campaign schema now supports unlimited goals and open-ended duration**
  - `CampaignCreate`, `CampaignUpdate`, and `CampaignResponse` now support:
    - `target_mode` (`targeted` | `unlimited`)
    - nullable `target_amount`
    - `min_amount`
    - `end_date_mode` (`fixed` | `open`)
    - nullable `end_date`
  - Campaign create/update validation now enforces goal and date rules consistently.
  - Historical campaign records auto-created from imports now default to `target_mode=unlimited` and `end_date_mode=open`.
  - Existing PostgreSQL deployments are upgraded at startup through a safe runtime schema migration.

- **Challans list endpoint now returns pagination metadata**
  - `GET /challans/` now returns `{ items, total, skip, limit }` instead of a bare list.
  - This enables the frontend challans management page to use real server-side pagination.

## 2026-03-15

### Added
- **Challan History Import Endpoint**: `POST /challans/import/history` (superadmin only)
  - Accepts CSV/XLSX historical monthly challan files.
  - Resolves members by `member_code/member_id/code`, `si_no`, or `username` (+ phone/email fallback).
  - Creates monthly challans with duplicate protection (`member_id + month + amount + type`).
  - Returns import summary: `total_rows`, `challans_created`, `members_linked_existing`, `rows_skipped`, `errors`.
  - Files: `app/routes/challan_routes.py`, `app/services/challan_service.py`, `app/schemas/schemas.py`.

- **Campaign Payments Import Endpoint**: `POST /campaigns/import/payments` (superadmin only)
  - Accepts CSV/XLSX campaign payment history files.
  - Resolves members using the same identifier strategy as above.
  - Resolves/creates campaigns from `suggested_campaign_name/campaign_name` (falls back to `General Fund / One-Time Contribution 2024-2025`).
  - Creates campaign challans (`type=campaign`) and links each donor payment to the campaign.
  - Returns import summary: `total_rows`, `campaigns_created`, `challans_created`, `members_linked_existing`, `rows_skipped`, `errors`.
  - Files: `app/routes/campaign_routes.py`, `app/services/campaign_service.py`, `app/schemas/schemas.py`.

## 2026-03-14

### Changed
- **Members Import Compatibility**: `POST /members/import` now supports historical CSV variants used in split legacy files.
  - Added identifier mapping support for `si_no -> MEM-XXXX` and `username` lookup in addition to `member_code/member_id`.
  - Added flexible join date parsing including `join_year` fallback.
  - Added donation parsing support for `period` and `type` fields from historical challan/campaign files.
  - Campaign donation rows (`type=campaign`) now create/link campaign challans (not forced to monthly type).
  - Supports campaign auto-resolution by `suggested_campaign_name`; creates an inactive historical campaign if missing.
  - File: `app/services/member_service.py` and `app/routes/member_routes.py`.

### Notes
- Endpoint remains superadmin-only and backward compatible with existing member import templates.
- Frontend-only cross-reference: Members panel pagination (20/50/100 page size + page navigation) was implemented on `2026-03-14` in `CharityConnect/src/pages/Members.jsx`. No API contract change required.

### Added
- **System Wipe Endpoint**: `POST /admin/system/wipe` (superadmin only)
  - Purpose: destructive cleanup of operational data while preserving superadmins (and optionally admins).
  - Request fields:
    - `confirm_text` (must be `WIPE`)
    - `keep_admins` (default `true`)
    - `wipe_files` (default `true`)
  - Deletes: members, challans, bulk groups, campaigns, invites, notifications, requests, audit logs, and non-preserved users.
  - Optionally deletes uploaded files from backend `app/uploads` storage.
  - Returns deletion summary counters and kept admin/superadmin counts.
  - Files: `app/routes/admin_router.py`, `app/schemas/schemas.py`, `app/schemas/__init__.py`.

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
