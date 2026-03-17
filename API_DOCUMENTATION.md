# CharityConnect API Documentation

**Base URL:** `http://localhost:8000`  
**Production:** Update BASE_URL in environment configuration  
**Version:** 1.0  
**Last Updated:** March 7, 2026

---

## Table of Contents
1. [Quick Reference](#quick-reference)
2. [Contract Baseline](#contract-baseline)
3. [TypeScript Schemas](#typescript-schemas)
4. [Bulk Operations](#bulk-operations)
5. [Authentication](#authentication)

---

## Quick Reference

### Authentication Header
```
Authorization: Bearer <access_token>
```

### Quick Endpoint Index

#### 🔐 Authentication (Public)
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/auth/login` | Login with email/username + password |
| POST | `/auth/register` | Register with invite code |
| GET | `/auth/me` | Get current user info |
| POST | `/auth/logout` | Logout |

#### 👥 Users (Admin Only)
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/users/` | List all users (filters: role, is_active, search) |
| GET | `/users/{id}` | Get user by ID |
| PUT | `/users/{id}` | Update user |

#### ✉️ Invites (Admin Only)
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/invites/` | Create invite code |
| GET | `/invites/` | List invites (filters: is_used, email, phone) |
| GET | `/invites/pending` | Get unused invites |
| POST | `/invites/validate` | Validate invite (Public) |
| GET | `/invites/{id}` | Get invite details |
| PUT | `/invites/{id}` | Update invite |
| DELETE | `/invites/{id}` | Delete invite |

#### 👤 Members
| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET | `/members/` | Admin/Member | List members (admin: all, member: self) |
| POST | `/members/` | Admin | Create member |
| GET | `/members/me` | User | Get own profile |
| GET | `/members/code/{code}` | Admin | Get member by code |
| GET | `/members/{id}` | Admin/Self | Get member by ID |
| PUT | `/members/{id}` | Admin | Update member |
| DELETE | `/members/{id}` | Admin | Delete member |

#### 🎯 Campaigns
| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| POST | `/campaigns/` | Admin | Create campaign |
| GET | `/campaigns/` | User | List campaigns (filter: active_only) |
| GET | `/campaigns/{id}` | User | Get campaign |
| PATCH | `/campaigns/{id}` | Admin | Update campaign |
| DELETE | `/campaigns/{id}` | Admin | Delete campaign |

#### 💰 Challans
| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| POST | `/challans/` | User | Create challan |
| POST | `/challans/{id}/upload-proof` | User/Admin | Upload payment proof |
| GET | `/challans/` | Admin/Member | List challans (admin: all, member: own) |
| GET | `/challans/member/{member_id}` | Admin/Self | Get member's challans |
| GET | `/challans/{id}` | Admin/Self | Get challan details |
| PATCH | `/challans/{id}` | Admin | Update challan |
| PATCH | `/challans/{id}/approve` | Admin | Approve challan |
| PATCH | `/challans/{id}/reject` | Admin | Reject challan |

#### 📦 Bulk Operations
| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| POST | `/challans/bulk-create` | User/Admin | Create multiple challans |
| GET | `/admin/bulk-pending-review` | Admin | Get pending bulk operations |
| PATCH | `/admin/bulk-operations/{bulk_group_id}/approve` | Admin | Approve bulk operation |
| PATCH | `/admin/bulk-operations/{bulk_group_id}/reject` | Admin | Reject bulk operation |

#### 🔔 Notifications
| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| POST | `/notifications/` | Admin | Send notification |
| GET | `/notifications/` | User | Get my notifications |
| GET | `/notifications/admin/sent` | Admin | List grouped sent notifications for admin panel |
| DELETE | `/notifications/admin/sent` | Admin | Delete sent batch by scope (members/admins/all) |
| GET | `/notifications/unread/count` | User | Get unread count |
| GET | `/notifications/{id}` | User | Get notification |
| PUT | `/notifications/{id}/read` | User | Mark as read |
| POST | `/notifications/mark-all-read` | User | Mark all as read |
| PUT | `/notifications/{id}` | Admin | Update notification |
| DELETE | `/notifications/{id}` | Admin | Delete notification |

#### 📨 Requests
| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET | `/requests/` | User | List requests (admin: all, member: own) |
| POST | `/requests/` | User | Create generic request |
| POST | `/requests/profile-update` | Member | Submit profile-update approval request |
| GET | `/requests/{id}` | Admin/Self | Get request details |
| PUT | `/requests/{id}` | Admin | Update status/response (approve/reject/resolve) |

#### 📁 Files
| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| POST | `/files/upload` | User | Upload file (3MB max, jpg/png/pdf) |

#### 📋 Audit Logs (Admin Only)
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/audit-logs/` | List audit logs (filters: user_id, entity_type, action) |
| POST | `/audit-logs/` | Create audit log entry |

---

## Contract Baseline

### Source of Truth
- OpenAPI (versioned): `/openapi/v1.json`
- Interactive docs: `/docs`
- ReDoc: `/redoc`

### Canonical Contract Rules

#### Registration Flow
- 2-step process:
  1. Frontend validates invite code
  2. POST `/auth/register` with validated invite
- Register request payload supports:
  - `invite_code` (required)
  - `username`, `password`, `email` (required)
  - `full_name`, `phone`, `address`, `monthly_amount` (optional)

#### Invite Management
- Canonical field: `expiry_date`
- Backward-compatible alias: `expires_at` (deprecated)
- Invite code format: `INV-XXXXXX`
- Acceptance rules (backend-enforced):
  - Must exist and be unused
  - Must not be expired
  - Single-use only

#### Challan Actions
- Canonical methods:
  - `PATCH /challans/{id}/approve`
  - `PATCH /challans/{id}/reject`
- Admin ID extracted from JWT token automatically
- Request body can be empty `{}`

#### Notification Management
- Canonical endpoint: `POST /notifications/`
- Deprecated alias: `POST /notifications/send`
- Sender-admin visibility rule:
  - when admin sends a notification to members/admins/specific user, backend ensures sender admin also gets a copy in their own list.

### Admin Notification Panel

#### List Sent Batches
**GET** `/notifications/admin/sent`

**Query Parameters:**
- `minutes=10080` - time window in minutes (default 7 days)
- `audience_filter=all` - `all | members | admins | superadmins`
- `skip=0`, `limit=50`

**Response (200):**
```json
[
  {
    "batch_created_at": "2026-03-07T17:21:52.713476",
    "title": "Hello",
    "message": "Notification visibility test",
    "target_role": "member",
    "audience_label": "members-only",
    "total_recipients": 8,
    "member_recipients": 7,
    "admin_recipients": 1,
    "superadmin_recipients": 0,
    "unread_count": 8
  }
]
```

#### Delete Sent Batch By Scope
**DELETE** `/notifications/admin/sent`

**Request:**
```json
{
  "batch_created_at": "2026-03-07T17:21:52.713476",
  "title": "Hello",
  "message": "Notification visibility test",
  "recipient_scope": "members"
}
```

`recipient_scope` allowed values: `all`, `members`, `admins`, `superadmins`.

**Response (200):**
```json
{
  "deleted_count": 7,
  "message": "Deleted 7 notifications"
}
```

### Member Profile Update Requests

#### Submit Profile Update Request (Member)
**POST** `/requests/profile-update`

Only changed fields are captured. If all submitted fields are unchanged vs current profile, request is rejected with `400`.

**Request (example):**
```json
{
  "address": "New address line",
  "monthly_amount": 700.0,
  "phone": "017XXXXXXXX"
}
```

Critical fields (`email`, `phone`, `full_name`, `username`, `father_name`) require superadmin approval at approve-time.

#### Request Response Contract (including profile metadata)
All request endpoints now return these additional fields:

- `is_profile_update` (boolean)
- `profile_update_member_id` (number or null)
- `profile_update_changed_fields` (object or null)
- `profile_update_submitted_at` (ISO datetime string or null)

**Response (200/201 example):**
```json
{
  "id": 41,
  "created_by_user_id": 17,
  "created_by": "member@example.com",
  "request_type": "approval",
  "subject": "member_profile_update:5",
  "message": "PROFILE_UPDATE_PAYLOAD::{...}",
  "priority": "medium",
  "status": "pending",
  "admin_response": null,
  "resolved_by": null,
  "resolved_at": null,
  "is_profile_update": true,
  "profile_update_member_id": 5,
  "profile_update_changed_fields": {
    "address": "New address line",
    "monthly_amount": 700.0
  },
  "profile_update_submitted_at": "2026-03-17T08:55:10.112233",
  "created_at": "2026-03-17T08:55:10.120000",
  "updated_at": "2026-03-17T08:55:10.120000"
}
```

#### Approval Effects
When admin/superadmin updates request status to `approved`:

- Member profile changes are applied in backend DB in the same transaction.
- Request owner receives a notification.
- Audit log is written with action:
  - `profile_update_request_approved`
  - `profile_update_request_rejected`

### Error Response Standard
All 4xx/5xx responses normalized to:
```json
{
  "detail": [
    {
      "type": "validation_error",
      "loc": ["body", "field_name"],
      "msg": "Error message",
      "input": "invalid_value"
    }
  ]
}
```

### Role & Permission Matrix

| User Role | Has Active Member | Can Donate | View Own Challans | Admin Operations |
|-----------|-------------------|------------|-------------------|------------------|
| member | yes | ✅ | ✅ | ❌ |
| member | no | ❌ | ❌ | ❌ |
| admin | yes | ✅ | ✅ | ✅ |
| admin | no | ❌ | ❌ | ✅ |
| superadmin | yes | ✅ | ✅ | ✅ |
| superadmin | no | ❌ | ❌ | ✅ |

---

## Bulk Operations

### Create Bulk Challans
**POST** `/challans/bulk-create`

Create multiple challans for different months with single proof file.

**Request:**
```json
{
  "months": ["2026-03", "2026-04", "2026-05"],
  "amount_per_month": 500.0,
  "proof_file_id": "proof-uuid-123",
  "member_id": 123,
  "notes": "Q1 advance payment"
}
```

**Response (201):**
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
- Members: Can create for self only
- Admins: Can create for any active member

### Get Pending Bulk Operations
**GET** `/admin/bulk-pending-review`

**Query Parameters:**
- `days=7` - Filter operations from last N days
- `sort_by=created_at` - Sort by: created_at, member_name, total_amount
- `order=desc` - Sort order: asc or desc

**Response (200):**
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
    }
  ]
}
```

### Approve Bulk Operations
**PATCH** `/admin/bulk-operations/{bulk_group_id}/approve`

**Request Body:** (optional)
```json
{
  "notes": "Approved by finance team"
}
```

**Response (200):**
```json
{
  "bulk_group_id": "bulk-20260306-a1b2c3d4",
  "status": "approved",
  "approved_challans": 3,
  "approved_by_admin_id": 1,
  "approved_at": "2026-03-06T11:00:00"
}
```

### Reject Bulk Operations
**PATCH** `/admin/bulk-operations/{bulk_group_id}/reject`

**Request Body:**
```json
{
  "rejection_reason": "Invalid proof document"
}
```

---

## Authentication

### Login
**POST** `/auth/login`

**Note:** The `username` field accepts either a username or email address. The backend automatically detects which type is provided and authenticates accordingly.

**Request (with username):**
```json
{
  "username": "user1",
  "password": "password123"
}
```

**Request (with email):**
```json
{
  "username": "user@example.com",
  "password": "password123"
}
```

**Response (200):**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer",
  "user": {
    "id": 1,
    "username": "user1",
    "email": "user@example.com",
    "role": "member",
    "is_active": true
  }
}
```

**Error Responses:**
- `401 Unauthorized`: Invalid username/email or password
- `403 Forbidden`: User account is inactive

### Register
**POST** `/auth/register`

**Important:** 
- Usernames must be unique across all users
- Email addresses must be unique if provided
- Password must be at least 8 characters

**Request:**
```json
{
  "invite_code": "INV-ABC123",
  "username": "newuser",
  "password": "password123",
  "email": "new@example.com",
  "full_name": "New User",
  "phone": "+1234567890",
  "address": "123 Main St",
  "monthly_amount": 500.0
}
```

**Response (201):**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer",
  "user": {
    "id": 2,
    "username": "newuser",
    "email": "new@example.com",
    "role": "member",
    "is_active": true
  }
}
```

**Error Responses:**
- `400 Bad Request`: Invalid/expired invite code, password too short
- `409 Conflict`: Username or email already exists
- `403 Forbidden`: Invite code email/phone mismatch

### Get Current User
**GET** `/auth/me`

**Headers:**
```
Authorization: Bearer <access_token>
```

**Response (200):**
```json
{
  "id": 1,
  "username": "user1",
  "email": "user@example.com",
  "role": "member",
  "is_active": true,
  "created_at": "2026-01-01T00:00:00"
}
```

---

## Common Response Codes

| Code | Meaning | Usage |
|------|---------|-------|
| 200 | OK | Request succeeded |
| 201 | Created | Resource created successfully |
| 204 | No Content | Resource deleted successfully |
| 400 | Bad Request | Invalid request data |
| 401 | Unauthorized | Missing or invalid token |
| 403 | Forbidden | Valid token but insufficient permissions |
| 404 | Not Found | Resource doesn't exist |
| 409 | Conflict | Duplicate resource (username, email, etc.) |
| 422 | Unprocessable Entity | Validation error |
| 500 | Internal Server Error | Server error |

---

## Rate Limiting
Currently not implemented. Consider adding in production:
- Login: 5 attempts per minute
- File upload: 10 per minute
- General API: 100 requests per minute

---

## CORS Configuration
**Development:**
```python
allow_origins=["*"]
```

**Production:**
```python
allow_origins=[
    "https://charity-connect.example.com",
    "https://www.charity-connect.example.com"
]
```

---

## Additional Resources
- Interactive API Docs: http://localhost:8000/docs
- OpenAPI Spec: http://localhost:8000/openapi/v1.json
- ReDoc: http://localhost:8000/redoc
- See `README.md` for setup instructions
- See `COMMUNICATION_LOG.md` for integration coordination
