# CharityConnect Frontend Integration Guide

**Last Updated:** March 7, 2026  
**Version:** 2.0  
**Target:** React/Vite Frontend Developers

---

## Table of Contents
1. [Quick Start](#quick-start)
2. [API Contract Reference](#api-contract-reference)
3. [Authentication Integration](#authentication-integration)
4. [Core Workflows](#core-workflows)
5. [Testing Guide](#testing-guide)
6. [Common Issues](#common-issues)

---

## Quick Start

### Documentation Index

| Document | Purpose | Use When |
|----------|---------|----------|
| [API_DOCUMENTATION.md](API_DOCUMENTATION.md) | Complete API reference | Need endpoint details |
| [API_CHANGELOG.md](API_CHANGELOG.md) | Version history | Checking breaking changes |
| [TROUBLESHOOTING.md](TROUBLESHOOTING.md) | Common issues & fixes | Something not working |
| [COMMUNICATION_LOG.md](COMMUNICATION_LOG.md) | Decision history | Understanding why |

### Environment Setup

**Backend:**
```bash
cd charity-connect-backend
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

**Frontend Configuration:**
```env
# .env or .env.local
VITE_CHARITY_APP_BASE_URL=http://localhost:8000
```

**Interactive API Docs:**
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc
- OpenAPI JSON: http://localhost:8000/openapi/v1.json

**CORS Configuration:**
Backend allows origins: `localhost:5173`, `127.0.0.1:5173`, `localhost:3000`, `127.0.0.1:3000`

---

## API Contract Reference

### Locked Contracts (v1.0)

These contracts are **stable and frozen** for the current release:

#### ① Member Write Contract

**Writable Fields:**
- `monthly_amount` (float)
- `address` (string, optional)
- `status` (enum: active, inactive, suspended)

**Read-Only Fields:**
- `full_name`, `phone`, `email`, `member_code`, `city`, `notes`

**⚠️ Common Mistake:**
```javascript
// ❌ Wrong - Sending read-only field
PATCH /members/123 {
  "full_name": "New Name",  // This will be ignored!
  "monthly_amount": 500
}

// ✅ Correct
PATCH /members/123 {
  "monthly_amount": 500,
  "address": "123 Main St",
  "status": "active"
}
```

#### ② Notification Responses

**Contract:** Notifications are **inherently user-scoped** in responses.

```javascript
// Backend always returns only user's notifications
GET /notifications/
// No audience metadata in response
// Each user sees only their own records
```

**Frontend Action:**
- Treat as user-scoped by design
- Don't expect `audience` or `recipient` fields in list responses
- Admin sees admin notifications, members see member notifications

#### ③ Audit Log Payload Keys

**Required Fields:**
- `action` (string): CREATE, UPDATE, DELETE, etc.
- `entity_type` (string): User, Member, Challan, etc.
- `entity_id` (integer): ID of affected entity

**Optional Fields:**
- `user_id` (integer)
- `old_values` (JSON string): Pre-stringify before sending
- `new_values` (JSON string): Pre-stringify before sending
- `ip_address` (string)

**Important:** Unknown/extra keys are **safely ignored** (no error).

```javascript
// ✅ Correct - Pre-stringify JSON values
POST /audit-logs/ {
  "action": "UPDATE",
  "entity_type": "Member",
  "entity_id": 123,
  "old_values": JSON.stringify({ status: "active" }),
  "new_values": JSON.stringify({ status: "inactive" }),
  "custom_field": "ignored"  // Won't cause error
}
```

#### ④ Challan Multi-Month

**Contract:** One month per challan. Multi-month requires multiple requests.

**Option A: Per-Month Requests (Recommended)**
```javascript
// Create separate challans for each month
const months = ["2026-03", "2026-04", "2026-05"];
for (const month of months) {
  await createChallan({
    type: "monthly",
    month: month,
    amount: 500
  });
}
```

**Option B: Aggregation (Alternative)**
```javascript
// Create single challan with aggregated amount
await createChallan({
  type: "monthly",
  month: "2026-03",  // Start month
  amount: 1500,       // 500 * 3 months
  notes: "3 months advance payment (Mar-May)"
});
```

**⚠️ Wrong:**
```javascript
// ❌ Backend does NOT support this
POST /challans/ {
  "months": ["2026-03", "2026-04", "2026-05"]  // Not supported!
}
```

**Note:** For bulk operations, use dedicated bulk endpoints:
```javascript
// ✅ Use bulk endpoint instead
POST /challans/bulk-create {
  "months": ["2026-03", "2026-04", "2026-05"],
  "amount_per_month": 500,
  "proof_file_id": "proof-uuid"
}
```

#### ⑤ Member Detail Endpoint

**Contract:** `GET /members/{id}` returns complete member record with all readable fields.

**Reliable for:**
- Admin edit form population
- Member profile display
- Data verification

**Error Responses:**
- `404`: Member not found
- `403`: Insufficient permissions
- `500`: Server error

```javascript
// ✅ Always fetch before editing
const getMemberForEdit = async (memberId) => {
  try {
    const response = await api.get(`/members/${memberId}`);
    return response.data;  // Full member object
  } catch (error) {
    if (error.response?.status === 404) {
      console.error("Member not found");
    } else if (error.response?.status === 403) {
      console.error("Access denied");
    }
  }
};
```

### Quick Reference Matrix

| Point | Status | Action Required |
|-------|--------|-----------------|
| Member write fields | ✅ Confirmed | Restrict edit form to writable fields only |
| Notification scope | ✅ Confirmed | Treat as user-scoped (no audience metadata) |
| Audit log keys | ✅ Confirmed | Use canonical keys, pre-stringify JSON |
| Challan multi-month | ✅ Confirmed | Use Option A or B, or bulk endpoint |
| Member detail fetch | ✅ Confirmed | Always fetch before editing |

---

## Authentication Integration

### Setup Axios Interceptor

```typescript
import axios from 'axios';

const api = axios.create({
  baseURL: import.meta.env.VITE_CHARITY_APP_BASE_URL,
});

// Add token to all requests
api.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem('access_token');
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  },
  (error) => Promise.reject(error)
);

// Handle token expiration
api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem('access_token');
      window.location.href = '/login';
    }
    return Promise.reject(error);
  }
);

export default api;
```

### Login Flow

```typescript
interface LoginRequest {
  username: string;  // Can be email or username
  password: string;
}

interface LoginResponse {
  access_token: string;
  token_type: string;
  user: {
    id: number;
    username: string;
    email: string;
    role: 'member' | 'admin' | 'superadmin';
    is_active: boolean;
  };
}

const login = async (credentials: LoginRequest): Promise<LoginResponse> => {
  const response = await api.post<LoginResponse>('/auth/login', credentials);
  
  // Store token
  localStorage.setItem('access_token', response.data.access_token);
  
  // Store user info
  localStorage.setItem('user', JSON.stringify(response.data.user));
  
  return response.data;
};
```

### Registration Flow

**Step 1: Validate Invite**
```typescript
const validateInvite = async (inviteCode: string): Promise<boolean> => {
  try {
    const response = await api.post('/invites/validate', {
      invite_code: inviteCode
    });
    return response.status === 200;
  } catch (error) {
    return false;
  }
};
```

**Step 2: Register User**
```typescript
interface RegisterRequest {
  invite_code: string;
  username: string;
  password: string;
  email: string;
  full_name?: string;
  phone?: string;
  address?: string;
  monthly_amount?: number;
}

const register = async (data: RegisterRequest): Promise<LoginResponse> => {
  const response = await api.post<LoginResponse>('/auth/register', data);
  
  // Token automatically returned - no separate login needed
  localStorage.setItem('access_token', response.data.access_token);
  localStorage.setItem('user', JSON.stringify(response.data.user));
  
  return response.data;
};
```

### Get Current User

```typescript
const getCurrentUser = async () => {
  const response = await api.get('/auth/me');
  return response.data;
};
```

---

## Core Workflows

### 1. Monthly Payment Flow

```typescript
// Step 1: Upload proof file
const uploadProof = async (file: File): Promise<string> => {
  const formData = new FormData();
  formData.append('file', file);
  
  const response = await api.post('/files/upload', formData, {
    headers: { 'Content-Type': 'multipart/form-data' }
  });
  
  return response.data.file_url;  // or file_id
};

// Step 2: Create challan
const createChallan = async (data: {
  type: 'monthly' | 'campaign';
  month: string;  // YYYY-MM format
  amount: number;
  proof_file_url?: string;
  campaign_id?: number;
  notes?: string;
}) => {
  const response = await api.post('/challans/', data);
  return response.data;
};

// Step 3: Upload proof to existing challan (if needed)
const uploadChallanProof = async (challanId: number, file: File) => {
  const formData = new FormData();
  formData.append('file', file);
  
  const response = await api.post(
    `/challans/${challanId}/upload-proof`,
    formData,
    { headers: { 'Content-Type': 'multipart/form-data' } }
  );
  
  return response.data;
};
```

### 2. Admin Challan Approval

```typescript
// Get pending challans
const getPendingChallans = async () => {
  const response = await api.get('/challans/', {
    params: { status: 'pending' }
  });
  return response.data;
};

// Approve challan
const approveChallan = async (challanId: number) => {
  // Empty body - admin ID extracted from JWT
  const response = await api.patch(`/challans/${challanId}/approve`, {});
  return response.data;
};

// Reject challan
const rejectChallan = async (challanId: number, reason: string) => {
  const response = await api.patch(`/challans/${challanId}/reject`, {
    rejection_reason: reason
  });
  return response.data;
};
```

### 3. Bulk Operations

```typescript
// Create bulk challans
const createBulkChallans = async (data: {
  months: string[];  // ["2026-03", "2026-04", "2026-05"]
  amount_per_month: number;
  proof_file_id: string;
  member_id?: number;  // Admin only - for other members
  notes?: string;
}) => {
  const response = await api.post('/challans/bulk-create', data);
  return response.data;
};

// Get pending bulk operations (admin)
const getPendingBulkOperations = async (days: number = 7) => {
  const response = await api.get('/admin/bulk-pending-review', {
    params: { days, sort_by: 'created_at', order: 'desc' }
  });
  return response.data;
};

// Approve bulk operation
const approveBulkOperation = async (bulkGroupId: string) => {
  const response = await api.patch(
    `/admin/bulk-operations/${bulkGroupId}/approve`,
    { notes: 'Approved' }
  );
  return response.data;
};
```

### 4. Member Management

```typescript
// Get own profile
const getMyProfile = async () => {
  const response = await api.get('/members/me');
  return response.data;
};

// Get member by ID (admin or self)
const getMember = async (memberId: number) => {
  const response = await api.get(`/members/${memberId}`);
  return response.data;
};

// Update member (admin)
const updateMember = async (memberId: number, data: {
  monthly_amount?: number;
  address?: string;
  status?: 'active' | 'inactive' | 'suspended';
}) => {
  const response = await api.put(`/members/${memberId}`, data);
  return response.data;
};

// Create member (admin)
const createMember = async (data: {
  user_id: number;
  member_code: string;
  monthly_amount: number;
  address?: string;
  status: 'active' | 'inactive' | 'suspended';
}) => {
  const response = await api.post('/members/', data);
  return response.data;
};
```

### 5. Notifications

```typescript
// Get unread count
const getUnreadCount = async (): Promise<number> => {
  const response = await api.get('/notifications/unread/count');
  return response.data.unread_count;
};

// Get user's notifications
const getNotifications = async () => {
  const response = await api.get('/notifications/');
  return response.data;
};

// Mark as read
const markAsRead = async (notificationId: number) => {
  const response = await api.put(`/notifications/${notificationId}/read`);
  return response.data;
};

// Mark all as read
const markAllAsRead = async () => {
  const response = await api.post('/notifications/mark-all-read');
  return response.data;
};

// Admin panel: list sent notification batches
type AudienceFilter = 'all' | 'members' | 'admins' | 'superadmins';

const getAdminSentNotifications = async (params?: {
  minutes?: number;
  audience_filter?: AudienceFilter;
  skip?: number;
  limit?: number;
}) => {
  const response = await api.get('/notifications/admin/sent', {
    params: {
      minutes: params?.minutes ?? 10080,
      audience_filter: params?.audience_filter ?? 'all',
      skip: params?.skip ?? 0,
      limit: params?.limit ?? 50,
    },
  });
  return response.data;
};

// Admin panel: delete sent batch by recipient scope
type RecipientScope = 'all' | 'members' | 'admins' | 'superadmins';

const deleteAdminSentNotifications = async (payload: {
  batch_created_at: string;
  title: string;
  message: string;
  recipient_scope: RecipientScope;
}) => {
  const response = await api.delete('/notifications/admin/sent', {
    data: payload,
  });
  return response.data;
};

// Admin panel helper: send + auto-visibility for sender admin
const createNotification = async (payload: {
  title: string;
  message: string;
  user_id?: number;
  target_role?: 'member' | 'admin' | 'superadmin';
}) => {
  const response = await api.post('/notifications/', payload);
  // Backend now auto-includes sender admin if not already in recipients.
  return response.data;
};

// Poll for updates (in useEffect)
useEffect(() => {
  const pollInterval = setInterval(async () => {
    const count = await getUnreadCount();
    setUnreadCount(count);
  }, 30000);  // Every 30 seconds
  
  return () => clearInterval(pollInterval);
}, []);
```

### 6. Campaign Management

```typescript
// Get active campaigns
const getActiveCampaigns = async () => {
  const response = await api.get('/campaigns/', {
    params: { active_only: true }
  });
  return response.data;
};

// Get campaign details
const getCampaign = async (campaignId: number) => {
  const response = await api.get(`/campaigns/${campaignId}`);
  return response.data;
};

// Create campaign donation
const createCampaignDonation = async (campaignId: number, amount: number) => {
  const response = await api.post('/challans/', {
    type: 'campaign',
    campaign_id: campaignId,
    amount: amount
  });
  return response.data;
};
```

---

## Testing Guide

### Test Environment

- Backend: `http://localhost:8000`
- Frontend: `http://localhost:5173`
- Browser: Chrome or Edge (latest)

### Critical Test Cases

#### T1: Login with Email
**Steps:**
1. Navigate to `/login`
2. Enter email + password
3. Click "Login"

**Expected:**
- Token stored in `localStorage`
- User object stored in `localStorage`
- Redirect to dashboard
- API requests include `Authorization: Bearer <token>`

**Verification:**
```javascript
localStorage.getItem('access_token')  // Should exist
localStorage.getItem('user')           // Should exist
```

#### T2: Registration
**Steps:**
1. Navigate to `/register`
2. Enter valid invite code
3. Fill username, password, email
4. Submit

**Expected:**
- User + Member created in database
- Token returned and stored
- Auto-login (no separate login needed)
- Redirect to dashboard

**Verification:**
```sql
SELECT u.id, u.username, m.member_code
FROM users u
JOIN members m ON m.user_id = u.id
WHERE u.username = 'testuser';
```

#### T3: File Upload
**Steps:**
1. Create challan
2. Click "Upload Proof"
3. Select JPG/PNG/PDF under 3MB
4. Submit

**Expected:**
- File uploaded to `/files/upload`
- Returns `file_url` or `file_id`
- Challan status updates to "pending"
- File accessible at returned URL

**Error Cases:**
- File > 3MB → 413 Payload Too Large
- Invalid file type → 400 Bad Request

#### T4: Admin Approval
**Steps:**
1. Login as admin
2. Navigate to pending challans
3. Click "Approve" on a challan
4. Confirm

**Expected:**
- PATCH request to `/challans/{id}/approve` with empty body
- Challan status changes to "approved"
- `approved_by_admin_id` and `approved_at` populated
- Frontend updates UI

---

## Common Issues

### Issue: 401 Unauthorized After Login

**Causes:**
1. Token not being sent in requests
2. Token expired
3. JWT subject type mismatch

**Solutions:**
1. Verify Axios interceptor is configured
2. Check `ACCESS_TOKEN_EXPIRE_MINUTES` setting
3. Ensure token is stored correctly:
```javascript
console.log(localStorage.getItem('access_token'));
```

### Issue: 403 Forbidden on Member Endpoints

**Cause:** Member trying to access admin-only endpoint

**Solution:** Use appropriate endpoints:
- Member: `GET /members/me` (own profile)
- Admin: `GET /members/` (all members)

### Issue: Challan Creation Fails with "No member record found"

**Cause:** User has no Member profile

**Solution:** Run migration script (see [TROUBLESHOOTING.md](TROUBLESHOOTING.md))

### Issue: CORS Errors

**Cause:** Frontend origin not in CORS whitelist

**Solution:** Verify backend CORS configuration includes your frontend origin:
```python
allow_origins=[
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]
```

### Issue: File Upload Returns 413

**Cause:** File exceeds 3MB limit

**Solution:**
1. Validate file size before upload:
```javascript
if (file.size > 3 * 1024 * 1024) {
  alert('File must be under 3MB');
  return;
}
```
2. Or increase limit in backend (not recommended)

---

## Implementation Checklist

### Must Have
- [ ] Axios interceptor configured with token injection
- [ ] 401 response handler redirects to login
- [ ] Member edit form restricts to writable fields only
- [ ] Audit log JSON values pre-stringified
- [ ] Challan multi-month strategy chosen (Option A/B or bulk)
- [ ] Member detail fetched before edit dialog
- [ ] File size validation before upload (3MB max)
- [ ] Notification polling every 30 seconds
- [ ] Error messages user-friendly

### Nice to Have
- [ ] Token refresh logic
- [ ] Offline fallback handling
- [ ] Loading states on all async operations
- [ ] Optimistic UI updates
- [ ] Request caching for static data
- [ ] Retry logic for failed requests

---

## Need Help?

1. **API Issues:** Check [API_DOCUMENTATION.md](API_DOCUMENTATION.md)
2. **Errors:** See [TROUBLESHOOTING.md](TROUBLESHOOTING.md)
3. **Contract Questions:** Review [COMMUNICATION_LOG.md](COMMUNICATION_LOG.md)
4. **Changes:** Check [API_CHANGELOG.md](API_CHANGELOG.md)
5. **Test APIs:** Use Swagger UI at `/docs`
