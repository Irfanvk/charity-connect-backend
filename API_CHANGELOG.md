# API Changelog

## 2026-11-20

### Monthly fee history (new table `member_fees`; new column `users.preferred_language`, added at startup)
- A fee change (admin member edit, or an approved fee-change request) always starts NEXT month (India time); `members.monthly_amount` stays this month's fee and switches by itself when the month begins (checked every 30 minutes with the reminders). Changing it again in the same month replaces the waiting change. The first change writes the old fee from the member's start month (join month, not before Aug 2024) and the new fee from next month; members without changes have no entries and pay `members.monthly_amount` for every month, as before.
- The fee for a month = the latest entry starting on or before it (same month twice: the later one). Used for new payments (single, separate months, one-proof bulk and admin-recorded: each month at its own fee unless an admin gives an amount), re-pricing of unpaid months (each to its own month's fee; paid months keep what was paid), the member statement, dues, year grid and the yearly paid list.
- `GET /challans/payable-months` adds `month_fees` `{month: fee}`. `GET /members/{id}/fees` (admins): `{member_id, current_fee, upcoming: {amount, effective_from}|null, history: [{amount, effective_from, source start|admin|request, changed_by (admin code), note, created_at}]}`. Paid list rows add `fee_varies`, `received_amount`, `pending_amount` (sums for a year in which the fee changed). `POST /admin-record` without `amount_per_month` charges each month its own fee.
- App language: `PUT /auth/me/language {language: en|ml|kn}`; `GET /auth/me` returns `preferred_language`.

### Statements, receipts list, admin codes, link address
- `GET /reports/my-statement?year=` (anyone with a member record, admins too): one Aug-Jul year (`year` = start year, default this year) month by month from the join month (`months`, `totals`, `member`, `current_month`), `year`, `label` "2026-2027", `years` available, and `history`: every payment newest first, one entry per payment (bulk payments and months started together count once; imported "not paid yet" rows left out) `{key, number, type, months, campaign_title, amount, state paid|waiting|not_paid|rejected, rejection_reason, started_on, sent_on, paid_on, receipt: {challan_id}|{bulk_group_id}|null}`. 404 without a member record.
- `GET /receipts` (admins): every receipt, newest first, `search` (number, member, reference, month, campaign), `date_from` / `date_to` (date received, else approved; India time), `kind` all|monthly|campaign, `method`, `checked_by` (admin code), `skip`, `limit` (max 500) -> `{total, total_amount, items: [{kind, challan_id, bulk_group_id, number, member_code, member_name, type, months, campaign_title, amount, received_amount, date, payment_method, transaction_ref, checked_by}], checked_by_codes}`.
- Admin codes: members see an admin as a short code made from the admin's member ID (MEM-0012 -> A12; no member record -> AD<user id>), never the name: receipt `approved_by`, and the "(by ...)" in rejection notifications.
- Shared links (receipts, invites, password resets) use FRONTEND_BASE_URL unless it is a hosting or local address (netlify.app, vercel.app, localhost), then the new setting `PUBLIC_SITE_URL` (default `https://poyyathabailgcc.com`).

### Bank check on approval, receipts, private proofs (new table `proof_files`; new columns on `challans` and `challan_bulk_groups`, added at startup)
- **Approve with a bank check.** `PATCH /challans/{id}/approve` and `PATCH /admin/bulk/{id}/approve` take optional `received_on` (date, not in the future), `transaction_ref` (max 100), `received_amount`, `payment_method`, `verification_note` (max 300), `bank_record_file_id` (an uploaded file) and `confirm_duplicate_ref`. A reference already used by another not-rejected payment gives 409 `{detail: [{msg, input: {duplicate_of}}]}` unless confirmed; an amount different from the amount due needs a note (400). Saved on the challans (and the bulk group: new columns `received_on`, `transaction_ref`, `payment_method`); in the audit log. Challan responses add `received_amount`, `verification_note`, `bank_record_path`.
- **Receipts.** `GET /receipts/challan/{id}` and `GET /receipts/bulk/{bulk_group_id}` (admins, or the member it belongs to; 409 until approved): `{organisation, logo_url, kind, number, valid, status, member_code, member_name, member_phone, type, months, campaign_title, amount, received_amount, received_on, payment_method, transaction_ref, approved_on, approved_by, token, verify_url}`. A month of a bulk payment returns the whole payment's receipt. Public `GET /receipts/verify/{token}` (no login): the receipt with the name shortened ("Amina K.") and no reference / approver; `valid: false` if the payment was reverted; 404 for a made-up token (tokens are signed with SECRET_KEY). `verify_url` = FRONTEND_BASE_URL + `/r/{token}`. The WhatsApp receipt adds the link.
- **Proofs.** New proofs are stored privately on Cloudinary and named after the payment number (`PG-2627-0042-xxxxxxxx`), or the member ID until the number is known (renamed when the bulk payment gets its number); profile photos are named by member ID. Responses carry a link that works for 30 minutes (`proof_path`, `bank_record_path`, bulk `proof_url`); older public proofs are unchanged. New `GET /files/proof-link?challan_id=` or `?bulk_group_id=` (admins, or the owner): a fresh link `{url, expires_in}`.
- **Reused proofs.** Each proof's SHA-256 is saved (`proof_files`, and `proof_sha256` on challans and bulk groups). When the same file was used for another not-rejected payment, `proof_duplicate_of` ("Same proof file as PG-2627-0003 (MEM-0012, Sep 2026)") is set on the challan / bulk payment (in the challan, bulk list and bulk details responses) and added to the admins' "New payment proof" notification.
- **CI.** Backend tests run on every push and pull request; deploy runs only after they pass.

### Payment numbers and paying months together (new table `number_sequences`; new column `challan_no` on `challans` and `challan_bulk_groups`, added at startup)
- Every new payment gets a real number `<prefix>-<yy><yy+1>-<nnnn>`, e.g. `PG-2627-0001`: the Aug-Jul financial year of the day it is started (India time), counting from 0001 each year; the counter row is locked so numbers never repeat. One number per payment: a single challan, each month of "separate proof" multi-month, all months of a bulk payment (also on the group), all months of one admin-recorded entry, and all months started with `same_number`. Older and imported rows have none (show `CH-<id>`). New setting `challan_number_prefix` (string, default `PG`, letters/digits only, max 6).
- `challan_no` added to challan responses, `BulkChallanResponse`, the admin bulk list and bulk details; challan search also matches it. `POST /challans/multi` takes `same_number` (bool): one number for all months whose single proof comes later; the response adds `challan_numbers` and `same_number`.
- `POST /challans/pay-together` `{challan_ids (2-36), proof_file_id, notes?}`: your own open monthly challans (generated, or pending with nothing handed in, including imported "not paid yet" rows) become one bulk payment `BCH-xxxx` with one proof, status pending, for an admin to approve in one step. Keeps their shared number if they all have the same one, otherwise gets a new one. 400 (fewer than two, no proof, not monthly), 403 (not yours), 409 (already paid or sent). Admins are notified as for any proof; audited `bulk_pay_together`.
- Approval / rejection notifications and the WhatsApp receipt show the number; `msg_payment_approved` can use `{number}`.

### Unfinished payments (new table `nudge_logs`, created at startup)
- "Unfinished" = a challan the member started themself (`entry_source` "self" with a `created_by_user_id`), still generated/pending, with nothing handed in. Imported "not paid yet" rows and admin entries never count.
- `GET /challans/unfinished?min_hours=48`: admins get everyone's open at least `min_hours` (default 48); members get their own, any age. `{items: [{id, member_id, member_code, member_name, phone, type, month, campaign_id, campaign_title, what, amount, created_at (UTC, Z), hours_open, reminders_sent: ["48h","7d"], reminded_today, already_paid}], count, min_hours}`. `already_paid` = that month was since paid or handed in with another challan (a leftover to cancel).
- `POST /challans/{id}/remind` (admins): sends the member a reminder now; once per challan per day (409), 404 if it is no longer unfinished, 400 if the member has no active login. Audited `challan_unfinished_remind`.
- `DELETE /challans/{id}?reason=` (max 300): when an admin cancels a payment the member started, the member gets a "Payment cancelled" notification with the reason; the reason is saved in the audit log.
- Scheduler (same loop as the monthly reminders, from 09:00 IST): members get one notification 48 hours after starting, and a follow-up at 7 days (at least 3 days after the first); several due together go in one notification; link `/Challans?unfinished=1`. Admins get one summary a day listing those open 48+ hours, link `/Unfinished`. Leftovers get no reminders. Every send is logged once by key in `nudge_logs`. New setting `unfinished_payment_reminders` (bool, default on).

## 2026-11-16

### Yearly paid list
- `GET /reports/paid-list?year=2025` (admins): the Aug 2025 – Jul 2026 list. `{organisation, year, label, months, current_month, campaigns: [{id, title, total}], rows: [{si, member_number, pending_months, member_code, name, place, status, monthly_amount, months: ["P"|"W"|"-"|""] x12, campaigns: {campaign_id: amount}}]}`. All members (inactive too) in member-ID order; P = approved, W = handed in and waiting, - = before joining; campaigns are those with approved donations received in that year. `member_number` is the number in a MEM-#### code (null otherwise); `pending_months` counts months up to the current one that are not paid (blank or W).

### Month limits up to 36
- Settings `upcoming_months_payable` (Advance months payable) and `max_months_per_payment` (Max months per payment) now default to 36 and accept up to 36 (were 12 and 12, max 12 and 24). `GET /challans/payable-months?upcoming_count=` accepts up to 36 (was 12). A value already saved in Settings stays until a superadmin changes it.

### Occasion banners (new table `banners`, created at startup)
- Public `GET /banners/login`; signed in `GET /banners/for-me` (members' or admins' banners by role). Both return banners showing now (active, started, not ended), newest first, at most 5: `{items: [{id, title, message, image_url, button_label, button_link, ends_at, updated_at}]}`.
- Admins: `GET /banners` (all, with `status` active / scheduled / paused / past and counts), `POST /banners`, `PUT /banners/{id}` (partial; `is_active` pauses), `DELETE /banners/{id}`, `POST /banners/image` (JPG/PNG, max 3 MB) -> `{image_url}`. Rules: title required; message <= 300; button needs text and an app path or https link; at least one place; end after start, at most a year. Changes are audited (`banner_create/update/delete`).

### Profile photos and own requests
- `POST/DELETE /auth/me/avatar` now return 403 for anyone with a member record (admins too): photo changes go through a profile update request and an admin's approval. Accounts without a member record still change it directly.
- `GET /requests/?mine=true` lists only the signed-in user's own requests, also for admins.

## 2026-11-15

### Member IDs and deleting members
- New member IDs are the highest `MEM-####` number in use plus one (was: the last-added member's number plus one). Codes outside the sequence, such as `TEST-0001` for a temporary test member, are ignored. Used by admin-created members, imports and invite registration.
- `DELETE /members/{id}` (superadmin) also removes the member's requests, relief claims (and their approvals), payment reminder log and activation requests, which used to make the delete fail, and switches off the member's login (`is_active = false`; admins keep their admin login).

### Forgot password: phone in any format
- `POST /auth/forgot-password`: when the identifier looks like a phone number and is not an exact email, username or phone, it is matched by digits against the phone and WhatsApp numbers, ignoring spaces, dashes, brackets, a leading 0, a 0 right after the country code, and a missing country code (8+ digits). Only a single match is linked; otherwise the request is saved unmatched as before. The response is unchanged (202 either way).

### Admin-recorded payments: any number of months
- `POST /challans/admin-record`: no `max_months_per_payment` limit. Months with a "not paid yet" challan (generated, or pending with nothing handed in) are filled in instead of refused; months paid or waiting for approval still return 400. Two or more months are grouped as one bulk payment (`bulk_group_id` BCH-xxxx), approved with `PATCH /admin/bulk/{id}/approve` by a different admin.
- `GET /challans/payable-months?include_unpaid_placeholders=true` (admins only; ignored for members) lists those "not paid yet" months as payable.

### Challans: notes and member ID
- `POST /challans/` takes `notes` (max 500); `POST /challans/multi` and `POST /challans/bulk-create` save their `notes` on every challan created. All are returned as `entry_notes`.
- Challan responses add `member_code` (e.g. `MEM-0042`). `member_id` is the database id.

## 2026-11-14

### Relief fund (new tables `relief_claims`, `relief_approvals`, created at startup)
- Settings (category "Relief fund"): `relief_amount_death` 50000, `relief_amount_illness` 40000, `relief_amount_retirement` 40000, `relief_required_approvals` 3, `relief_max_unpaid_months` 3, `relief_min_membership_months` 6, `relief_min_gulf_years` 10.
- `GET /relief/me` (any signed-in user): `{scheme, eligibility, claims}`; claims without receiver or bank details.
- Admins: `GET /relief/eligibility/{member_id}?reason&gulf_from_year&gulf_to_year`, `GET /relief/claims?status=pending|approved|rejected|paid|cancelled|to_decide&search`, `GET /relief/claims/{id}`, `POST /relief/claims`, `POST /relief/claims/{id}/approve {note}`, `/reject {reason}`, `/paid {paid_on, method, reference, receipt_url}`, `/cancel {reason}` (creator or superadmin, pending only).
- Eligibility checks are warnings stored on the claim (`eligibility.checks`, `warnings`): unpaid months (overdue, not this month) at most the limit, months as member (death and illness), Aug 2024 – Mar 2025 paid, lives abroad (not for retirement), Gulf service years (retirement).
- Hard rules: required documents per reason (`application` + `death_certificate` / `medical_report` / `gulf_proof`), amount not below the default, one active (pending, approved or paid) claim per member and reason (409), N approvals from admins or superadmins other than the creator, one per admin; any rejection rejects. The last approval creates an approved `FundUtilization` (category "Relief") linked by `fund_utilization_id`. Every step is in Audit Logs (`relief_claim_*`) and notifies the other admins / creator ("Fund approvals") and the member ("Payment updates").

### Paying ahead: up to 12 months
- Setting `upcoming_months_payable` ("Advance months payable") now defaults to **12** (was 3; still 0–12). A value a superadmin saved before is kept. `GET /challans/payable-months?include_upcoming=true&upcoming_count=N` returns N future months, capped by the setting.

### Reports API (admins and superadmins)
Month states everywhere: `paid` (approved), `waiting` (handed in: proof, bulk payment or recorded by an admin, not yet approved), `not_paid` (nothing handed in, a generated or imported "pending" challan, or only rejected ones). Months count from the join month (Aug 2024 when no join date) through this month.
- `GET /reports/member-statement/{member_id}?from_month&to_month`: `{organisation, generated_on, member{...}, from_month, to_month, current_month, months: [{month, state, amount, paid_on, handed_in_on, method, note, challan_id, ahead}], totals: {months_paid, amount_paid, months_waiting, amount_waiting, months_due, amount_due, months_overdue, this_month_due, paid_up_to, last_paid_month, last_payment_on, due_months}, donations, donations_total}`. Months paid ahead of `to_month` are included with `ahead: true`.
- `GET /reports/dues?country&min_months&search&status=active|inactive|all&sort=amount_desc|months_desc|name|code`: members with unpaid months plus `members_with_dues`, `total_amount_due`, `total_months_due`, `fee_missing`, `organisation`.
- `GET /reports/payments?type=monthly|campaign&state&month_from&month_to&campaign_id&country&member_id&search&method&sort&skip&limit` (limit up to 500): `{items, total, has_more, totals: {paid|waiting|not_paid|rejected: {count, amount}}, organisation}`. Monthly fees filter by the month they are for, donations by the India-time day they were given.
- `GET /reports/year-grid?year&status&country`: one row per member with 12 month states (`before_join` and `future` too), `paid` and `due` counts.

### Audit logs: feed for the Audit Logs page
- New `GET /audit-logs/feed` (admins): `{items, total, skip, limit, has_more, counts: {admin, superadmin, actors}}`, newest first, `limit` up to 100 (default 50). Filters: `user_id`, `role` (`admin|superadmin|member|system`), `area` (`members|payments|bulk|requests|campaigns|funds|notifications|reports|settings|other`; mixed entity spellings such as `Challan`/`challan` are grouped), `action`, `start_date`/`end_date` (inclusive, India-time days), `search` (action, entity, recorded values, who did it). Items carry `area`, `target_name` (member name, "Member · Oct 2026", campaign title, ...; taken from the recorded values when the item was deleted), `old_values`/`new_values` as objects, `changes: [{field, before, after}]` (unchanged fields left out) and `created_at` marked as UTC. Fields whose name contains password, token, secret or hash read "(hidden)".
- New `GET /audit-logs/filters` (admins): `{actors: [{user_id, name, role, count}], actions: [{action, count}], areas: [{area, label, count}], system_count}`.
- New `GET /audit-logs/export` (admins): CSV of every entry matching the same filters (max 5000), times in India time.
- `GET /audit-logs/` is unchanged.

### Notifications: admins get everything
- Admins (not superadmins) no longer filter pushes: category switches, quiet hours and payment-reminder choices are ignored for them (reminders go on the organisation's default day). `GET /notifications/preferences` adds `simple_settings` (true for admins); `PUT /notifications/preferences` with any field returns 403 for them. Members and superadmins are unchanged.
- Push payloads already carry `data.notification_id`; the app now marks it read when the push is tapped.

### Requests: admins may delete old ones
- `DELETE /requests/{id}` by an admin or superadmin (not their own request): allowed for **pending** or **rejected** requests at least 7 days old, except monthly amount changes and account closure requests (400 with the reason otherwise). It is audited (`request_deleted`), and for a pending request the member gets a "Request closed" notification. Members still cancel their own pending requests at any time.
- Request items add `admin_can_delete` (bool) and `admin_deletable_from` (when an admin may delete it; null if never).

## 2026-11-13

### Members: country and city
- New member fields `country` (ISO code from the phone country list: SA, AE, KW, OM, QA, BH, IN, CA, US, GB, AU, IQ, AZ, MA, ZA) and `city` (max 100). Added to `members` and `member_activations` at startup. Any other country returns 422 (400 on activation).
- `POST /auth/register` and `POST /member-activations` accept `country` and `city`; they are optional for older app versions, and an approved activation copies them to the member.
- New `PUT /members/me/location` `{country, city}` (both required, 400 otherwise): the signed-in member sets their own, no approval.
- `PUT /members/{id}` and `POST /members/` accept `country` and `city`; an admin update can change but not clear them.
- `GET /members/` (admins) takes `country` (ISO or `none` = not entered) and `phone_code` (`971`, `+971` or `AE`; `other` = no phone or a code not on the list). `search` also matches phone, WhatsApp number and city. Items and `MemberResponse` include `country` and `city`. The community directory does not.
- `GET /members/` (admins) also takes `phone` (digits of the phone or WhatsApp number; spaces, dashes, `+` and a leading 0 are ignored; 400 without digits) and `registered` (`yes` = has an account and can sign in, `no` = not registered yet). `GET /members/summary` adds `registered_members`.
- New `GET /members/stats/countries` (admins and superadmins): `{countries: [{country, name, count}], not_set, total}`.

### Push notifications: PEM private key now works
- Phone/browser pop-ups failed for every device with "Could not deserialize key data": the VAPID private key setting resolves to PEM text, which pywebpush does not read. The backend now loads PEM (raw, base64-encoded or from a file) and raw base64url keys itself before sending. No API or setting change; existing subscriptions keep working, nobody needs to re-subscribe.

### Payable months: start month without a join date
- `GET /challans/payable-months` (and the checks that use it): a member with no `join_date` now starts from the platform start, Aug 2024, instead of 12 months ago. Members with a join date are unchanged: their join month (never before Aug 2024).

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

### Bank details are locked in the web app
- The bank account, UPI ID and QR are no longer settings. They live in the web app code (`src/config/bankDetails.js` in CharityConnect) so a stolen admin login or direct database access cannot redirect payments.
- Removed settings: `payment_upi_id`, `payment_upi_qr_image_url`, `payment_bank_name`, `payment_account_name`, `payment_account_number_masked_display`, `payment_ifsc_or_iban`. `PUT /admin/settings` with any of them returns 400 (unknown setting), and `GET /settings/public` no longer returns them, even if old rows remain in `app_settings`.
- New setting `bank_details_enabled` (bool, default `true`, public, superadmin): show or hide the bank details page and card. It cannot change their content.
- `payment_instructions_text` stays; the app shows it as a separate "Note from the admins".

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
