# Bulk Operations API Implementation Guide

**Date:** March 6, 2026  
**Backend:** FastAPI (Python)  
**Status:** ✅ Fully Implemented

---

## Overview

Bulk Operations API enables efficient multi-month challan management, allowing members to create multiple monthly payments in a single transaction and admins to approve/reject them all at once.

---

## API Endpoints

### 1. **Create Bulk Challans** (Member/Admin)

**POST** `/challans/bulk-create`

Create multiple challans for different months linked to a single proof file.

**Authentication:** Required (JWT Token)

**Request Body:**
```json
{
  "months": ["2026-03", "2026-04", "2026-05"],
  "amount_per_month": 500.0,
  "proof_file_id": "proof-uuid-123",
  "member_id": 123,  // Admin only - target member
  "notes": "Q1 advance payment"
}
```

**Response (201 Created):**
```json
{
  "bulk_group_id": "bulk-20260306-a1b2c3d4",
  "member_id": 123,
  "created_challans": 3,
  "challan_ids": [401, 402, 403],
  "months": ["2026-03", "2026-04", "2026-05"],
  "total_amount": 1500.0,
  "proof_file_id": "proof-uuid-123",
  "status": "pending_approval",
  "created_at": "2026-03-06T10:30:00",
  "notes": "Q1 advance payment"
}
```

**Permissions:**
- **Members:** Can create for self only
- **Admins/Superadmins:** Can create for any active member

---

### 2. **Get Pending Bulk Operations** (Admin Only)

**GET** `/admin/bulk-pending-review`

Retrieve all pending bulk operations for admin review.

**Authentication:** Required (JWT - Admin/Superadmin only)

**Query Parameters:**
```
days=7              # Filter operations created in last N days (optional, default: 7)
sort_by=created_at  # Sort by: created_at, member_name, total_amount (optional, default: created_at)
order=desc          # Sort order: asc or desc (optional, default: desc)
```

**Response (200 OK):**
```json
{
  "pending": 2,
  "bulk_operations": [
    {
      "bulk_group_id": "bulk-20260306-a1b2c3d4",
      "member_id": 123,
      "member_name": "Ahmed Khan",
      "member_email": "ahmed@example.com",
      "months": ["2026-03", "2026-04", "2026-05"],
      "months_count": 3,
      "total_amount": 1500.0,
      "amount_per_month": 500.0,
      "proof_file_id": "proof-uuid-123",
      "proof_url": "http://localhost:8000/uploads/proofs/proof-uuid-123.jpg",
      "status": "pending_approval",
      "created_at": "2026-03-06T10:30:00",
      "created_by_email": "admin@example.com",
      "notes": "Q1 advance payment"
    },
    {
      "bulk_group_id": "bulk-20260306-e5f6g7h8",
      "member_id": 124,
      "member_name": "Sara Ahmed",
      "member_email": "sara@example.com",
      "months": ["2026-03", "2026-04"],
      "months_count": 2,
      "total_amount": 1000.0,
      "amount_per_month": 500.0,
      "proof_file_id": "proof-uuid-456",
      "proof_url": "http://localhost:8000/uploads/proofs/proof-uuid-456.jpg",
      "status": "pending_approval",
      "created_at": "2026-03-05T15:20:00",
      "created_by_email": "admin@example.com",
      "notes": null
    }
  ]
}
```

---

### 3. **Get Bulk Operation Details** (Admin Only)

**GET** `/admin/bulk/{bulk_group_id}`

Retrieve detailed information about a specific bulk operation including linked challans.

**Authentication:** Required (JWT - Admin/Superadmin only)

**Path Parameters:**
```
bulk_group_id=bulk-20260306-a1b2c3d4
```

**Response (200 OK):**
```json
{
  "bulk_group_id": "bulk-20260306-a1b2c3d4",
  "member_id": 123,
  "member_name": "Ahmed Khan",
  "member_email": "ahmed@example.com",
  "months": ["2026-03", "2026-04", "2026-05"],
  "total_amount": 1500.0,
  "amount_per_month": 500.0,
  "proof_file_id": "proof-uuid-123",
  "proof_url": "http://localhost:8000/uploads/proofs/proof-uuid-123.jpg",
  "status": "pending_approval",
  "created_at": "2026-03-06T10:30:00",
  "created_by_email": "admin@example.com",
  "approved_at": null,
  "approved_by": null,
  "admin_notes": null,
  "notes": "Q1 advance payment",
  "linked_challans": [
    {
      "challan_id": 401,
      "month": "2026-03",
      "amount": 500.0,
      "status": "pending",
      "created_at": "2026-03-06T10:30:00"
    },
    {
      "challan_id": 402,
      "month": "2026-04",
      "amount": 500.0,
      "status": "pending",
      "created_at": "2026-03-06T10:30:00"
    },
    {
      "challan_id": 403,
      "month": "2026-05",
      "amount": 500.0,
      "status": "pending",
      "created_at": "2026-03-06T10:30:00"
    }
  ]
}
```

---

### 4. **Approve Bulk Challans** (Admin Only)

**PATCH** `/admin/bulk/{bulk_group_id}/approve`

Approve all challans in a bulk group in a single action.

**Authentication:** Required (JWT - Admin/Superadmin only)

**Path Parameters:**
```
bulk_group_id=bulk-20260306-a1b2c3d4
```

**Request Body:**
```json
{
  "approved": true,
  "admin_notes": "Proof verified, payment confirmed"
}
```

**Response (200 OK):**
```json
{
  "bulk_group_id": "bulk-20260306-a1b2c3d4",
  "status": "approved",
  "approved_challans": 3,
  "challan_ids": [401, 402, 403],
  "months_approved": ["2026-03", "2026-04", "2026-05"],
  "total_amount_approved": 1500.0,
  "approved_by": "admin@example.com",
  "approved_at": "2026-03-06T11:00:00",
  "admin_notes": "Proof verified, payment confirmed"
}
```

**Permissions:**
- Admin/Superadmin only
- Cannot approve already approved bulk groups
- Cannot approve rejected bulk groups

**Side Effects:**
- Updates all linked challans to "approved" status
- Records audit log with "bulk_approve" action
- Sets admin_notes on bulk group
- Timestamps approval

---

### 5. **Reject Bulk Challans** (Admin Only)

**PATCH** `/admin/bulk/{bulk_group_id}/reject`

Reject all challans in a bulk group and delete associated records.

**Authentication:** Required (JWT - Admin/Superadmin only)

**Path Parameters:**
```
bulk_group_id=bulk-20260306-a1b2c3d4
```

**Request Body:**
```json
{
  "reason": "Proof is unclear - cannot verify details",
  "action": "delete"
}
```

**Response (200 OK):**
```json
{
  "bulk_group_id": "bulk-20260306-a1b2c3d4",
  "status": "rejected",
  "rejected_challans": 3,
  "challan_ids": [401, 402, 403],
  "rejected_at": "2026-03-06T11:05:00",
  "reason": "Proof is unclear - cannot verify details",
  "rejected_by": "admin@example.com"
}
```

**Permissions:**
- Admin/Superadmin only
- Cannot reject already approved bulk groups
- Requires rejection reason

**Side Effects:**
- Deletes all linked challans from database
- Updates bulk group status to "rejected"
- Records rejection reason and timestamp
- Creates audit log with "bulk_reject" action
- Member should be notified (notification feature to be added)

---

## Error Responses

### Validation Errors (422)

```json
{
  "detail": [
    {
      "type": "value_error",
      "loc": ["body", "months"],
      "msg": "Months list cannot be empty",
      "input": []
    }
  ]
}
```

### Permission Errors (403)

```json
{
  "detail": "Admin access required"
}
```

```json
{
  "detail": "Members can only create bulk challans for themselves"
}
```

### Not Found (404)

```json
{
  "detail": "Bulk operation not found"
}
```

```json
{
  "detail": "Member not found"
}
```

### Conflict Errors (400)

```json
{
  "detail": "Bulk operation already approved"
}
```

```json
{
  "detail": "Cannot approve rejected bulk operation"
}
```

### Server Errors (500)

```json
{
  "detail": "Internal server error message"
}
```

---

## Database Schema

### BulkChallanGroup Table

```python
class BulkChallanGroup(Base):
    __tablename__ = "challan_bulk_groups"
    
    id: int                          # Primary key
    bulk_group_id: str              # Unique identifier (e.g., bulk-20260306-a1b2c3d4)
    member_id: int                  # FK to members table
    amount_per_month: float         # Amount per month
    total_amount: float             # Sum of all months
    proof_file_id: str              # Single proof file shared across all
    status: str                     # pending_approval, approved, rejected
    months_list: str                # JSON array of months (YYYY-MM format)
    challan_ids_list: str           # JSON array of linked challan IDs
    admin_notes: str                # Admin review notes
    approved_by_admin_id: int       # FK to users table (approver)
    rejection_reason: str           # Reason for rejection
    created_by_user_id: int         # FK to users table (creator)
    created_at: datetime            # Creation timestamp
    approved_at: datetime           # Approval timestamp
    rejected_at: datetime           # Rejection timestamp
    updated_at: datetime            # Last update timestamp
    notes: str                      # Member notes
```

---

## Usage Examples

### Example 1: Member Creates 3-Month Bulk Challan

```bash
# Member submits proof and creates 3-month challan
curl -X POST http://localhost:8000/challans/bulk-create \
  -H "Authorization: Bearer <member-token>" \
  -H "Content-Type: application/json" \
  -d '{
    "months": ["2026-03", "2026-04", "2026-05"],
    "amount_per_month": 500.0,
    "proof_file_id": "proof-20260306-abc123"
  }'

# Response: Status 201 Created
# Returns: bulk_group_id, challan_ids, total_amount, status=pending_approval
```

### Example 2: Admin Reviews Pending Bulk Operations

```bash
# Admin gets list of pending operations
curl -X GET "http://localhost:8000/admin/bulk-pending-review?days=7&sort_by=created_at&order=desc" \
  -H "Authorization: Bearer <admin-token>"

# Response: Status 200 OK
# Returns: List of 2-3 pending bulk operations
```

### Example 3: Admin Approves Bulk Operation

```bash
# Admin reviews details and approves
curl -X GET http://localhost:8000/admin/bulk/bulk-20260306-a1b2c3d4 \
  -H "Authorization: Bearer <admin-token>"

# Response: Full details including linked challans
# Decision: Approve
curl -X PATCH http://localhost:8000/admin/bulk/bulk-20260306-a1b2c3d4/approve \
  -H "Authorization: Bearer <admin-token>" \
  -H "Content-Type: application/json" \
  -d '{
    "approved": true,
    "admin_notes": "Verified payment, all 3 months approved"
  }'

# Response: Status 200 OK
# All 3 linked challans now have status=approved
```

### Example 4: Admin Rejects Bulk Operation

```bash
# Admin cannot verify proof
curl -X PATCH http://localhost:8000/admin/bulk/bulk-20260306-a1b2c3d4/reject \
  -H "Authorization: Bearer <admin-token>" \
  -H "Content-Type: application/json" \
  -d '{
    "reason": "Proof image too blurry - cannot read bank details",
    "action": "delete"
  }'

# Response: Status 200 OK
# Bulk operation marked as rejected
# All 3 linked challans deleted from database
# Member will need to resubmit
```

---

## Audit Logging

All bulk operations are logged to the `audit_logs` table:

### Bulk Create Audit Entry

```json
{
  "user_id": 123,
  "action": "bulk_create",
  "entity_type": "BulkChallanGroup",
  "entity_id": 1,
  "new_values": {
    "bulk_group_id": "bulk-20260306-a1b2c3d4",
    "months": ["2026-03", "2026-04", "2026-05"],
    "total_amount": 1500.0,
    "challan_ids": [401, 402, 403]
  },
  "created_at": "2026-03-06T10:30:00"
}
```

### Bulk Approve Audit Entry

```json
{
  "user_id": 456,
  "action": "bulk_approve",
  "entity_type": "BulkChallanGroup",
  "entity_id": 1,
  "new_values": {
    "status": "approved",
    "months": ["2026-03", "2026-04", "2026-05"],
    "total_amount": 1500.0,
    "admin_notes": "Verified payment, all 3 months approved"
  },
  "created_at": "2026-03-06T11:00:00"
}
```

---

## Performance Considerations

### Caching
- Bulk operations list is frequently accessed by admins
- Consider caching for 5-10 minutes
- Invalidate on approve/reject actions

### Batch Processing
- Current implementation updates challans individually  
- For large bulk groups (100+ months), consider batch updates

### Audit Trail
- All operations are logged automatically
- Audit logs can be used for compliance and reporting

---

## Security Notes

✅ **Implemented:**
- Role-based access control (Admin/Member)
- Members can only create for themselves
- Admins restricted to pending & rejected operations
- Token-based authentication on all endpoints
- Input validation on all request bodies

---

## Testing Checklist

- [ ] Member creates 3-month bulk challan
- [ ] Member cannot create for another member
- [ ] Admin can list pending bulk operations
- [ ] Admin can view details of specific bulk operation
- [ ] Admin approves bulk operation → all 3 challans approved
- [ ] Admin rejects bulk operation → all 3 challans deleted
- [ ] Audit logs record all actions
- [ ] 403 error when non-admin accesses `/admin/...` endpoints
- [ ] 404 error for non-existent bulk_group_id
- [ ] 422 error for invalid month format
- [ ] 400 error when approving already-approved bulk group

---

## Future Enhancements

1. **Notifications:** Send alert to member when bulk operation approved/rejected
2. **Batch Operations:** Single endpoint to approve/reject multiple bulk groups
3. **Reporting:** Dashboard showing bulk operation statistics and trends
4. **Webhooks:** Allow external systems to subscribe to bulk operation events
5. **Reversals:** Allow admins to reverse previously approved bulk operations
6. **Partial Approval:** Option to approve/reject specific months within a group

---

## Related Documentation

- [FRONTEND_INTEGRATION_GUIDE.md](../CharityConnect/Backend-Guidance/FRONTEND_INTEGRATION_GUIDE.md) - Frontend implementation details
- [API_QUICK_REFERENCE.md](API_QUICK_REFERENCE.md) - All API endpoints
- [COMMUNICATION_LOG.md](../CharityConnect/COMMUNICATION_LOG.md) - Design decisions

---

**Last Updated:** March 6, 2026
