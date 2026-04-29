# Multi-Challan Creation with Proof Type Selection

## Overview

This feature allows users to create multiple challans at once (e.g., 6 months) and choose whether to upload payment proof individually for each challan or use a single bulk proof for all selected months.

## Workflow

### Step 1: User Selection
When a member selects 2 or more months to create challans, the frontend shows a confirmation dialog:

**Dialog Options:**
- **Individual Proof Mode**: Each challan has its own proof file
- **Bulk Proof Mode**: All challans share a single proof file

### Step 2: Route Based on Selection

#### Option A: Individual Proof Mode
- Creates all challans immediately
- User uploads proof for each challan separately
- Each challan tracks its own payment proof

#### Option B: Bulk Proof Mode  
- Returns routing instructions to frontend
- Frontend redirects user to bulk challan upload flow
- All selected months linked to single proof in bulk challan group

## API Endpoint

### POST `/challans/multi`

Create multiple challans with intelligent routing based on proof type.

**Request Body:**
```json
{
  "months": ["2026-01", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06"],
  "amount": 500,
  "type": "monthly",
  "proof_type": "bulk",
  "campaign_id": null,
  "payment_method": "upi",
  "member_id": null,
  "notes": "Payment for Jan-Jun 2026"
}
```

**Request Parameters:**

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `months` | `array[string]` | ✅ Yes | - | List of months in YYYY-MM format |
| `amount` | `number` | ✅ Yes | - | Amount per month (₹) |
| `type` | `string` | ❌ No | `"monthly"` | Challan type: `"monthly"` or `"campaign"` |
| `proof_type` | `string` | ❌ No | `"individual"` | `"individual"` or `"bulk"` |
| `campaign_id` | `number` | ❌ No | `null` | Required if type is `"campaign"` |
| `payment_method` | `string` | ❌ No | `null` | Payment method (e.g., "upi", "bank_transfer") |
| `member_id` | `number` | ❌ * | `null` | Required for admins, auto-filled for members |
| `notes` | `string` | ❌ No | `null` | Additional notes (used for bulk proof) |

**Authentication:** Required (member or admin)

**Authorization:**
- **Members**: Can create only for themselves
- **Admins**: Can create for any active member (must provide `member_id`)

---

## Response Format

### Response A: Individual Proof Mode

When `proof_type: "individual"`:

```json
{
  "workflow": "individual",
  "message": "Successfully created 6 individual challans",
  "created_count": 6,
  "challan_ids": [101, 102, 103, 104, 105, 106],
  "member_id": 42,
  "total_amount": 3000,
  "next_step": "Upload proof files for each challan individually"
}
```

**Next Steps for Frontend:**
1. Show success message with challan IDs
2. Display upload interface for each challan
3. Allow user to upload proof file for each month
4. After upload, challan status progresses to pending approval

---

### Response B: Bulk Proof Mode

When `proof_type: "bulk"`:

```json
{
  "workflow": "bulk",
  "message": "Ready to create 6 linked challans with shared proof",
  "member_id": 42,
  "months": ["2026-01", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06"],
  "amount_per_month": 500,
  "total_amount": 3000,
  "notes": "Payment for Jan-Jun 2026",
  "next_step": "POST /challans/bulk-create with months, amount_per_month, and proof file"
}
```

**Next Steps for Frontend:**
1. Show summary of months and total amount
2. Redirect to bulk challan creation flow
3. User uploads single proof file
4. Call `POST /challans/bulk-create` with:
   - `months`: Array from response
   - `amount_per_month`: Amount per month from response
   - `proof_file_id`: ID of uploaded proof file
   - `member_id`: Member ID from response
   - `notes`: Optional notes from response

---

## Bulk Challan Creation Endpoint

### POST `/challans/bulk-create`

Called after selecting bulk proof mode and uploading proof file.

**Request Body:**
```json
{
  "months": ["2026-01", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06"],
  "amount_per_month": 500,
  "proof_file_id": "file-uuid-here",
  "member_id": 42,
  "notes": "Payment for Jan-Jun 2026"
}
```

**Response:**
```json
{
  "bulk_group_id": "bulk-uuid-here",
  "member_id": 42,
  "created_challans": 6,
  "challan_ids": [101, 102, 103, 104, 105, 106],
  "months": ["2026-01", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06"],
  "total_amount": 3000,
  "proof_file_id": "file-uuid-here",
  "status": "pending_approval",
  "created_at": "2026-04-22T10:30:00Z"
}
```

---

## Error Handling

### Common Error Scenarios

#### 1. Invalid Months
```json
{
  "detail": "The following months are not available for this member: [2026-01, 2026-02]"
}
```
**Status:** 422 Unprocessable Entity

#### 2. Challan Already Exists
```json
{
  "detail": "Challans already exist for months: [2026-01, 2026-02]"
}
```
**Status:** 400 Bad Request

#### 3. Member Not Found
```json
{
  "detail": "Member not found"
}
```
**Status:** 404 Not Found

#### 4. Invalid Proof Type
```json
{
  "detail": "proof_type must be 'individual' or 'bulk'"
}
```
**Status:** 422 Unprocessable Entity

#### 5. Admin Without Member ID
```json
{
  "detail": "member_id is required for admin"
}
```
**Status:** 400 Bad Request

---

## Frontend Implementation Guide

### Step 1: Show Proof Type Confirmation Dialog

When user selects 2+ months:

```javascript
// Pseudo-code
if (selectedMonths.length >= 2) {
  showProofTypeDialog({
    monthCount: selectedMonths.length,
    totalAmount: selectedMonths.length * amountPerMonth,
    options: [
      {
        type: "individual",
        label: "Individual Proof (Upload per challan)",
        description: "Upload payment proof for each month separately"
      },
      {
        type: "bulk",
        label: "Bulk Proof (One for all months)",
        description: "Upload a single proof that covers all selected months"
      }
    ]
  });
}
```

### Step 2: Call Multi-Challan Endpoint

```javascript
// Option A: Individual Proof
const response = await charityClient.challans.createMulti({
  months: ["2026-01", "2026-02", "2026-03"],
  amount: 500,
  proof_type: "individual"
});

if (response.workflow === "individual") {
  // Show individual upload interface
  showIndividualUploadFlow(response.challan_ids);
}
```

```javascript
// Option B: Bulk Proof
const response = await charityClient.challans.createMulti({
  months: ["2026-01", "2026-02", "2026-03"],
  amount: 500,
  proof_type: "bulk",
  notes: "Jan-Mar 2026 payment"
});

if (response.workflow === "bulk") {
  // Redirect to bulk upload flow
  navigateToBulkUpload({
    member_id: response.member_id,
    months: response.months,
    total_amount: response.total_amount,
    amount_per_month: response.amount_per_month,
    notes: response.notes
  });
}
```

### Step 3: Handle Individual Proof Upload

```javascript
// For each challan in response.challan_ids
for (const challanId of response.challan_ids) {
  // User uploads proof file
  await charityClient.challans.uploadProof(challanId, proofFile);
}
```

### Step 4: Handle Bulk Proof Upload

```javascript
// Upload single proof
const proofFileId = await charityClient.files.upload(proofFile);

// Create bulk challan group
const bulkResponse = await charityClient.challans.createBulk({
  months: response.months,
  amount_per_month: response.amount_per_month,
  proof_file_id: proofFileId,
  member_id: response.member_id,
  notes: response.notes
});
```

---

## Database Schema

### Challan Table
- `id`: Primary key
- `member_id`: Foreign key to members
- `month`: YYYY-MM format
- `amount`: Challan amount
- `status`: generated | pending | approved | rejected
- `proof_path`: Path to proof file (for individual)

### BulkChallanGroup Table  
- `bulk_group_id`: UUID
- `member_id`: Foreign key to members
- `months_list`: JSON array of months
- `challan_ids_list`: JSON array of linked challan IDs
- `proof_file_id`: Single proof file for all
- `status`: pending_approval | approved | rejected
- `notes`: Optional notes

---

## Audit Logging

All multi-challan operations are logged to audit trail:

**Action:** `multi_challan_create`
**Entity Type:** `Challan`
**Entity ID:** `member_id`
**New Values:**
```json
{
  "months": ["2026-01", "2026-02", ...],
  "proof_type": "individual|bulk",
  "total_amount": 3000
}
```

---

## Validation Rules

1. **Months must be valid YYYY-MM format**
   - Example: "2026-01", "2026-02"
   - Invalid: "01-2026", "2026-1", "2026-Jan"

2. **Months must be available for member**
   - Cannot create for past months already paid
   - Cannot create for months before join date (with fallback logic)
   - Can create for current month and future months (6 months ahead)

3. **At least 1 month required**
   - Single month: Works but doesn't show proof type dialog
   - Multiple months: Shows proof type dialog

4. **Amount must be positive**
   - >= 50 (minimum monthly contribution)
   - <= 10000 (maximum monthly contribution)

5. **Member must be active**
   - Cannot create challans for inactive/suspended members

---

## Transaction Safety

All challan creation is transactional:
- If individual mode: All challans created in single transaction
- If bulk mode: No challan created yet (just response); actual creation happens in `/bulk-create` call
- Rollback on validation failure

---

## Performance Considerations

- **Individual Mode**: O(n) database operations where n = number of months
- **Bulk Mode**: O(1) database operation (just returns routing info)
- Recommended max months per request: 12 (reasonable for member view)

---

## Future Enhancements

1. **Partial Success Handling**: Resume failed month creation
2. **Proof Template Generation**: Auto-generate proof documents
3. **Payment Gateway Integration**: Pre-fill proof data from payment gateway
4. **Bulk Edit**: Modify multiple challans at once
5. **Scheduled Creation**: Auto-create monthly challans

---

## Testing Checklist

- [ ] Create 1 challan (single month) - should not show dialog
- [ ] Create 2 challans with individual proof
- [ ] Create 6 challans with individual proof
- [ ] Create 2 challans with bulk proof
- [ ] Create 6 challans with bulk proof
- [ ] Verify challan validation (invalid months)
- [ ] Verify member authorization
- [ ] Verify admin authorization
- [ ] Test member creating for another member (should fail)
- [ ] Test admin creating for inactive member (should fail)
- [ ] Verify audit logging for all scenarios

---

## Support

For questions or issues:
1. Check error response `detail` field
2. Review audit logs for operation details
3. Verify member status is "active"
4. Ensure months are in valid format and available
