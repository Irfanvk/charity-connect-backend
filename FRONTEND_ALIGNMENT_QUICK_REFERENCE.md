# Frontend-Backend Alignment Confirmations - Quick Reference

**Date:** March 3, 2026  
**Status:** All 5 Frontend Questions → Backend Confirmations ✅

---

## Alignment Matrix

| # | Frontend Question | Backend Confirmation | Status | Documentation | Frontend Action |
|---|---|---|---|---|---|
| **1** | Member write contract scope - can we edit `full_name`, `phone`, `email`, `city`, `notes`? | Only `monthly_amount`, `address`, `status` are writable. Others are read-only. | ✅ Confirmed | [FRONTEND_API_REFERENCE.md § 1](FRONTEND_API_REFERENCE.md#1-member-write-contract-confirmation) | Update edit form to restrict fields to canonical writable set |
| **2** | Notification list responses - should they include audience metadata for filtering? | No. Responses are user-scoped (one record per user). Audience metadata applies only at creation time. | ✅ Confirmed | [FRONTEND_API_REFERENCE.md § 2](FRONTEND_API_REFERENCE.md#2-notification-audience-model-for-list-responses) | Treat notifications as inherently user-scoped. Apply audience filtering at send time only. |
| **3** | Audit log payload - can we send additional unknown keys or must we be strict? | Additional keys are safely ignored. Send canonical keys (`action`, `entity_type`, `entity_id`) + optional keys. | ✅ Confirmed | [FRONTEND_API_REFERENCE.md § 3](FRONTEND_API_REFERENCE.md#3-audit-log-accepted-payload-keys) | Use canonical key mapping. Pre-stringify JSON value fields. |
| **4** | Challan multi-month - can we submit multiple months in one request? | No. Single month per challan (YYYY-MM). Create separate requests for multiple months or aggregate in frontend. | ✅ Confirmed | [FRONTEND_API_REFERENCE.md § 4](FRONTEND_API_REFERENCE.md#4-challan-monthly-multi-month-behavior) | Choose Option A (per-month) or B (aggregate). Implement accordingly. |
| **5** | Member detail endpoint - is it reliable for admin edit form population? | Yes. Returns complete record for all readable fields. Clear error responses (404/403/500). | ✅ Confirmed | [FRONTEND_API_REFERENCE.md § 5](FRONTEND_API_REFERENCE.md#5-member-detail-endpoint-for-admin-edit-flows) | Fetch member detail before opening edit form. Surface errors as admin toast. |

---

## Canonical Contracts (Locked)

### 1. Member Write Contract ✅ LOCKED
```json
PUT /members/{id}
{
  "monthly_amount": 600.0,      // ✅ Writable
  "address": "456 New St",      // ✅ Writable
  "status": "active"            // ✅ Writable
  // ❌ NOT writable: full_name, phone, email, member_code, city, notes
}
```

### 2. Notification Responses ✅ LOCKED
```json
GET /notifications/
[
  {
    "id": 25,
    "user_id": 5,               // ✅ User-scoped
    "title": "...",
    "message": "...",
    "is_read": false,
    "created_at": "...",
    "read_at": null
    // ❌ No audience metadata in response
  }
]
```

### 3. Audit Log Payload ✅ LOCKED
```json
POST /audit-logs/
{
  "action": "create",           // ✅ Canonical (required)
  "entity_type": "Challan",     // ✅ Canonical (required)
  "entity_id": 10,              // ✅ Canonical (required)
  "user_id": 2,                 // ✅ Optional
  "new_values": "{...}",        // ✅ Optional (pre-stringify)
  "old_values": "{...}",        // ✅ Optional (pre-stringify)
  "ip_address": "1.2.3.4",      // ✅ Optional
  "extra_key": "ignored"        // ✅ Safely ignored
}
```

### 4. Challan Monthly ✅ LOCKED
```json
POST /challans/
{
  "type": "monthly",
  "month": "2026-03",           // ✅ Single month (YYYY-MM)
  "amount": 500.0,
  "payment_method": "..."
  // ❌ No multi-month support - create separate requests
}

// Option A: Per-month (recommended)
POST /challans/ { type: "monthly", month: "2026-03", amount: 500.0 }
POST /challans/ { type: "monthly", month: "2026-04", amount: 500.0 }

// Option B: Frontend aggregation
POST /challans/ { type: "monthly", month: "2026-03", amount: 1000.0 }
```

### 5. Member Detail ✅ LOCKED
```json
GET /members/{id}
{
  "id": 1,
  "user_id": 5,
  "full_name": "john_doe",
  "member_code": "MEM-2026-001",
  "monthly_amount": 500.0,
  "address": "123 Main St",
  "join_date": "2026-01-15T10:00:00",
  "status": "active",
  "created_at": "2026-01-15T10:00:00",
  "updated_at": "2026-03-01T12:00:00"
  // ✅ Complete record for admin edit forms
}
```

---

## Implementation Checklist for Frontend

- [ ] **Member Edit Form**
  - [ ] Restrict editable fields to `monthly_amount`, `address`, `status` only
  - [ ] Make other fields read-only or hide them
  - [ ] Display clear note: "Admin can edit monthly amount, address, and status"

- [ ] **Challan Multi-Month**
  - [ ] Decide: Option A (per-month requests) or Option B (frontend aggregation)
  - [ ] If Option A: Loop through months, create separate challans
  - [ ] If Option B: Sum amounts, submit single challan with aggregated value

- [ ] **Audit Log Creation**
  - [ ] Use canonical keys: `action`, `entity_type`, `entity_id`
  - [ ] Map frontend event schema to canonical names
  - [ ] Pre-stringify JSON for `new_values` and `old_values`
  - [ ] Extra keys can be included (safely ignored)

- [ ] **Notification Handling**
  - [ ] Treat notification list as user-scoped by design
  - [ ] Don't expect audience metadata in responses
  - [ ] Apply audience filtering at send time only

- [ ] **Member Detail for Edit**
  - [ ] Fetch complete member record before opening edit form
  - [ ] Populate all form fields from response
  - [ ] Surface read failures as admin toast notifications

---

## Common Mistakes to Avoid

| Mistake | Why Wrong | Correct Approach |
|---------|-----------|---|
| Sending `full_name` in member update | Not writable (read-only) | Use canonical fields only: `monthly_amount`, `address`, `status` |
| Expecting audience metadata in notification list | Responses are user-scoped (metadata not persisted) | Apply audience filtering before sending notifications |
| Sending unknown keys in audit log | Assumption they'll error | Extra keys are safely ignored; backend accepts them |
| Submitting multiple months in single challan request | Backend doesn't support multi-month | Create separate challan per month or aggregate in frontend UI |
| Assuming old member data | Form opened without fetching latest | Fetch `GET /members/{id}` before opening edit dialog |

---

## Documentation References

- **Full Details:** [FRONTEND_API_REFERENCE.md § Frontend-Backend Contract Alignment](FRONTEND_API_REFERENCE.md#frontend-backend-contract-alignment-2026-03-03)
- **Quick Reference:** [API_QUICK_REFERENCE.md](API_QUICK_REFERENCE.md)
- **Type Definitions:** [API_TYPESCRIPT_SCHEMAS.md](API_TYPESCRIPT_SCHEMAS.md)
- **Communication History:** [COMMUNICATION_LOG.md](COMMUNICATION_LOG.md)
- **Alignment Summary:** [FRONTEND_ALIGNMENT_COMPLETE.md](FRONTEND_ALIGNMENT_COMPLETE.md)

---

## Status

✅ **All alignment questions resolved and documented**  
✅ **Canonical contracts locked**  
✅ **Frontend ready to implement with confidence**

**Last Updated:** March 3, 2026

---

**Need clarification?** Check [COMMUNICATION_LOG.md](COMMUNICATION_LOG.md) for decision history and context.
