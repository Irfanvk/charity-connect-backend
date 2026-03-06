# CharityConnect API Quick Reference

**Base URL:** `http://localhost:8000`

---

## Authentication Header
```
Authorization: Bearer <access_token>
```

---

## Quick Endpoint Index

### 🔐 Authentication (Public)
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/auth/login` | Login with email/username + password |
| POST | `/auth/register` | Register with invite code |
| GET | `/auth/me` | Get current user info |
| POST | `/auth/logout` | Logout |

### 👥 Users (Admin Only)
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/users/` | List all users (filters: role, is_active, search) |

### ✉️ Invites (Admin Only)
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/invites/` | Create invite code |
| GET | `/invites/` | List invites (filters: is_used, email, phone) |
| GET | `/invites/pending` | Get unused invites |
| POST | `/invites/validate` | Validate invite (Public) |
| GET | `/invites/{id}` | Get invite details |
| PUT | `/invites/{id}` | Update invite |
| DELETE | `/invites/{id}` | Delete invite |

### 👤 Members
| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET | `/members/` | Admin | List all members |
| GET | `/members/me` | User | Get own profile |
| GET | `/members/code/{code}` | Admin | Get member by code |
| GET | `/members/{id}` | Admin/Self | Get member by ID |
| PUT | `/members/{id}` | Admin | Update member |

### 🎯 Campaigns
| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| POST | `/campaigns/` | Admin | Create campaign |
| GET | `/campaigns/` | User | List campaigns (filter: active_only) |
| GET | `/campaigns/{id}` | User | Get campaign |
| PATCH | `/campaigns/{id}` | Admin | Update campaign |
| DELETE | `/campaigns/{id}` | Admin | Delete campaign |

### 💰 Challans
| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| POST | `/challans/` | User | Create challan |
| POST | `/challans/{id}/upload-proof` | User/Admin | Upload payment proof |
| GET | `/challans/` | Admin | List all challans (filter: status) |
| GET | `/challans/member/{member_id}` | Admin/Self | Get member's challans |
| GET | `/challans/{id}` | Admin/Self | Get challan details |
| PATCH | `/challans/{id}/approve` | Admin | Approve challan |
| PATCH | `/challans/{id}/reject` | Admin | Reject challan |

### 🔔 Notifications
| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| POST | `/notifications/` | Admin | Send notification |
| GET | `/notifications/` | User | Get my notifications |
| GET | `/notifications/unread/count` | User | Get unread count |
| GET | `/notifications/{id}` | User | Get notification |
| PUT | `/notifications/{id}/read` | User | Mark as read |
| POST | `/notifications/mark-all-read` | User | Mark all as read |
| PUT | `/notifications/{id}` | Admin | Update notification |
| DELETE | `/notifications/{id}` | Admin | Delete notification |

### 📁 Files
| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| POST | `/files/upload` | User | Upload file (3MB max, jpg/png/pdf) |

### 📋 Audit Logs (Admin Only)
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/audit-logs/` | List audit logs (filters: user_id, entity_type, action) |
| POST | `/audit-logs/` | Create audit log entry |

---

## Common Request Bodies

### Login
```json
{
  "email": "user@example.com",
  "password": "password123"
}
```

### Register
```json
{
  "invite_code": "INV-ABC123",
  "username": "username",
  "password": "password123",
  "email": "user@example.com",
  "phone": "+1234567890",
  "monthly_amount": 500.0
}
```

### Create Invite
```json
{
  "email": "newuser@example.com",
  "expiry_date": "2026-04-01T23:59:59"
}
```

### Create Campaign
```json
{
  "title": "Campaign Name",
  "description": "Description",
  "target_amount": 50000.0,
  "start_date": "2026-03-10T00:00:00",
  "end_date": "2026-04-10T23:59:59"
}
```

### Create Monthly Challan
```json
{
  "type": "monthly",
  "month": "2026-03",
  "amount": 500.0,
  "payment_method": "bank_transfer"
}
```

### Create Campaign Challan
```json
{
  "type": "campaign",
  "campaign_id": 3,
  "amount": 1000.0,
  "payment_method": "online"
}
```

### Approve Challan
```json
{
  "approved_by_admin_id": 2
}
```

### Reject Challan
```json
{
  "rejection_reason": "Invalid payment proof"
}
```

### Send Notification (Single User)
```json
{
  "user_id": 5,
  "title": "Payment Approved",
  "message": "Your payment has been approved."
}
```

### Send Notification (Role Broadcast)
```json
{
  "target_role": "member",
  "title": "Monthly Reminder",
  "message": "Please submit your monthly donation."
}
```

---

## Common Query Parameters

### Pagination
- `skip=0` - Number of records to skip
- `limit=100` - Maximum records to return

### Users Filters
- `role=member` - Filter by role (superadmin/admin/member)
- `is_active=true` - Filter by active status
- `search=john` - Search username or email

### Invites Filters
- `is_used=false` - Filter by usage status
- `email=user@example.com` - Filter by email
- `phone=+1234567890` - Filter by phone
- `sort_by=created_at` - Sort field
- `sort_order=desc` - Sort order (asc/desc)

### Campaigns Filters
- `active_only=true` - Show only active campaigns

### Challans Filters
- `status_filter=pending` - Filter by status (generated/pending/approved/rejected)

### Audit Logs Filters
- `user_id=2` - Filter by user ID
- `entity_type=Challan` - Filter by entity type
- `action=approve` - Filter by action

---

## Enums

### UserRole
- `superadmin`
- `admin`
- `member`

### ChallanStatus
- `generated` - Created, no proof
- `pending` - Proof uploaded, awaiting approval
- `approved` - Approved by admin
- `rejected` - Rejected by admin

### ChallanType
- `monthly` - Monthly donation
- `campaign` - Campaign donation

---

## Common Response Structures

### Token Response
```json
{
  "access_token": "eyJhbGc...",
  "token_type": "bearer",
  "user": {
    "id": 1,
    "username": "john_doe",
    "email": "john@example.com",
    "role": "member",
    "is_active": true,
    "created_at": "2026-03-01T10:00:00"
  }
}
```

### User Response
```json
{
  "id": 1,
  "username": "john_doe",
  "full_name": "john_doe",
  "email": "john@example.com",
  "phone": "+1234567890",
  "role": "member",
  "is_active": true,
  "created_at": "2026-03-01T10:00:00"
}
```

### Member Response
```json
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
}
```

### Challan Response
```json
{
  "id": 10,
  "member_id": 1,
  "type": "monthly",
  "month": "2026-03",
  "campaign_id": null,
  "amount": 500.0,
  "payment_method": "bank_transfer",
  "proof_path": "/uploads/proofs/abc123.jpg",
  "status": "approved",
  "created_at": "2026-03-03T10:00:00",
  "proof_uploaded_at": "2026-03-03T11:30:00",
  "approved_at": "2026-03-04T09:00:00",
  "updated_at": "2026-03-04T09:00:00"
}
```

### Campaign Response
```json
{
  "id": 3,
  "title": "Ramadan Food Drive 2026",
  "description": "Providing food packages",
  "target_amount": 50000.0,
  "start_date": "2026-03-10T00:00:00",
  "end_date": "2026-04-10T23:59:59",
  "is_active": true,
  "created_at": "2026-03-03T10:00:00",
  "updated_at": "2026-03-03T10:00:00"
}
```

### Notification Response
```json
{
  "id": 25,
  "user_id": 5,
  "title": "Payment Approved",
  "message": "Your payment has been approved.",
  "is_read": false,
  "created_at": "2026-03-04T09:00:00",
  "read_at": null
}
```

---

## Error Response Format

```json
{
  "detail": [
    {
      "type": "validation_error",
      "loc": ["body", "field_name"],
      "msg": "Error message",
      "input": "user_input"
    }
  ]
}
```

### HTTP Status Codes
- **200** - Success (GET, PATCH, PUT)
- **201** - Created (POST)
- **204** - No Content (DELETE)
- **400** - Bad Request
- **401** - Unauthorized
- **403** - Forbidden
- **404** - Not Found
- **422** - Validation Error
- **500** - Server Error

---

## File Upload Requirements

### File Types
- `image/jpeg` (.jpg, .jpeg)
- `image/png` (.png)
- `application/pdf` (.pdf)

### Size Limits
- `/files/upload` - **3 MB max**
- `/challans/{id}/upload-proof` - **5 MB max**

### Response
```json
{
  "file_url": "/uploads/proofs/uuid.jpg",
  "filename": "uuid.jpg"
}
```

---

## Frontend Implementation Examples

### Set Authorization Header (Axios)
```javascript
import axios from 'axios';

const api = axios.create({
  baseURL: 'http://localhost:8000',
});

api.interceptors.request.use(config => {
  const token = localStorage.getItem('access_token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

export default api;
```

### Set Authorization Header (Fetch)
```javascript
const fetchWithAuth = async (url, options = {}) => {
  const token = localStorage.getItem('access_token');
  
  return fetch(`http://localhost:8000${url}`, {
    ...options,
    headers: {
      ...options.headers,
      'Authorization': `Bearer ${token}`,
      'Content-Type': 'application/json',
    },
  });
};
```

### Handle Login
```javascript
const login = async (email, password) => {
  const response = await fetch('http://localhost:8000/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  });
  
  const data = await response.json();
  
  if (response.ok) {
    localStorage.setItem('access_token', data.access_token);
    localStorage.setItem('user', JSON.stringify(data.user));
    return data;
  } else {
    throw new Error(data.detail[0].msg);
  }
};
```

### Upload File
```javascript
const uploadFile = async (file, challanId) => {
  const formData = new FormData();
  formData.append('file', file);
  
  const token = localStorage.getItem('access_token');
  
  const response = await fetch(
    `http://localhost:8000/challans/${challanId}/upload-proof`,
    {
      method: 'POST',
      headers: { 'Authorization': `Bearer ${token}` },
      body: formData,
    }
  );
  
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail[0].msg);
  }
  
  return await response.json();
};
```

### Pagination Helper
```javascript
const fetchPage = async (endpoint, page = 1, limit = 20) => {
  const skip = (page - 1) * limit;
  const url = `${endpoint}?skip=${skip}&limit=${limit}`;
  
  return await fetchWithAuth(url);
};

// Usage
const campaigns = await fetchPage('/campaigns/', 1, 20);
```

### Handle Errors
```javascript
const handleApiError = (error) => {
  if (error.response) {
    const detail = error.response.data.detail;
    
    if (Array.isArray(detail)) {
      return detail.map(err => err.msg).join(', ');
    }
    
    return detail;
  }
  
  return 'Network error. Please try again.';
};
```

---

## Testing with cURL

### Login
```bash
curl -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@example.com","password":"admin123"}'
```

### Get with Auth
```bash
curl -X GET http://localhost:8000/members/me \
  -H "Authorization: Bearer YOUR_TOKEN_HERE"
```

### Upload File
```bash
curl -X POST http://localhost:8000/challans/10/upload-proof \
  -H "Authorization: Bearer YOUR_TOKEN_HERE" \
  -F "file=@payment_proof.jpg"
```

---

## Key Workflows

### Member Registration Flow
1. Validate invite code: `POST /invites/validate`
2. Register: `POST /auth/register`
3. Store token and navigate to dashboard

### Monthly Payment Flow
1. Get member profile: `GET /members/me`
2. Create challan: `POST /challans/`
3. Upload proof: `POST /challans/{id}/upload-proof`
4. Check status: `GET /challans/{id}`

### Admin Approval Flow
1. List pending: `GET /challans/?status_filter=pending`
2. Review challan: `GET /challans/{id}`
3. Approve/Reject: `PATCH /challans/{id}/approve` or `/reject`

---

**See [FRONTEND_API_REFERENCE.md](FRONTEND_API_REFERENCE.md) for complete documentation**
