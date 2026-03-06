# CharityConnect API Reference for Frontend

**Version:** 1.0.0  
**Base URL:** `http://localhost:8000` (Development)  
**Last Updated:** March 3, 2026

---

## Table of Contents
1. [Authentication & Authorization](#authentication--authorization)
2. [Authentication Endpoints](#authentication-endpoints)
3. [User Management](#user-management)
4. [Invite Management](#invite-management)
5. [Member Management](#member-management)
6. [Campaign Management](#campaign-management)
7. [Challan Management](#challan-management)
8. [Notification Management](#notification-management)
9. [File Management](#file-management)
10. [Audit Log Management](#audit-log-management)
11. [Error Response Format](#error-response-format)
12. [Data Types & Enums](#data-types--enums)

---

## Authentication & Authorization

### Token-Based Authentication
All authenticated endpoints require a Bearer token in the Authorization header.

**Header Format:**
```
Authorization: Bearer <access_token>
```

### User Roles
- **superadmin**: Full system access
- **admin**: Administrative access (create campaigns, manage members, approve challans)
- **member**: Basic member access (own profile, own challans)

### Token Expiration
- Access tokens expire after **60 minutes**
- No refresh token mechanism (re-login required)

---

## Authentication Endpoints

### 1. Login
**POST** `/auth/login`

**Description:** Authenticate user and receive JWT token

**Authorization:** None (Public)

**Request Body:**
```json
{
  "username": "string (optional if email provided)",
  "email": "string (optional if username provided)",
  "password": "string (required)"
}
```

**Response (200 OK):**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer",
  "user": {
    "id": 1,
    "username": "john_doe",
    "full_name": "john_doe",
    "email": "john@example.com",
    "phone": "+1234567890",
    "role": "member",
    "is_active": true,
    "created_at": "2026-03-01T10:00:00"
  }
}
```

**Error Responses:**
- **401 Unauthorized:** Invalid credentials
- **422 Validation Error:** Missing required fields

---

### 2. Register with Invite
**POST** `/auth/register`

**Description:** Register new user using valid invite code

**Authorization:** None (Public)

**Request Body:**
```json
{
  "invite_code": "string (required, e.g., 'INV-ABC123')",
  "username": "string (required)",
  "password": "string (required)",
  "full_name": "string (optional)",
  "email": "string (optional)",
  "phone": "string (optional)",
  "address": "string (optional)",
  "monthly_amount": 0.0
}
```

**Response (201 Created):**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer",
  "user": {
    "id": 2,
    "username": "jane_smith",
    "full_name": "jane_smith",
    "email": "jane@example.com",
    "phone": "+0987654321",
    "role": "member",
    "is_active": true,
    "created_at": "2026-03-02T14:30:00"
  }
}
```

**Error Responses:**
- **400 Bad Request:** Invalid or expired invite code
- **409 Conflict:** Username/email already exists
- **422 Validation Error:** Invalid data format

---

### 3. Get Current User Info
**GET** `/auth/me`

**Description:** Retrieve authenticated user's details

**Authorization:** Required (Any authenticated user)

**Request:** No body

**Response (200 OK):**
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

**Error Responses:**
- **401 Unauthorized:** Invalid or expired token
- **404 Not Found:** User not found

---

### 4. Logout
**POST** `/auth/logout`

**Description:** Logout user (token invalidation handled on frontend)

**Authorization:** Required

**Request:** No body

**Response (200 OK):**
```json
{
  "message": "Logged out successfully"
}
```

---

## User Management

### 1. Get All Users
**GET** `/users/`

**Description:** Retrieve all users with optional filtering

**Authorization:** Admin/Superadmin only

**Query Parameters:**
- `skip` (integer, default: 0): Number of records to skip (pagination)
- `limit` (integer, default: 100): Maximum records to return
- `role` (string, optional): Filter by role (`superadmin`, `admin`, `member`)
- `is_active` (boolean, optional): Filter by active status
- `search` (string, optional): Search by username or email (case-insensitive)

**Example Request:**
```
GET /users/?skip=0&limit=20&role=member&is_active=true&search=john
```

**Response (200 OK):**
```json
[
  {
    "id": 1,
    "username": "john_doe",
    "full_name": "john_doe",
    "email": "john@example.com",
    "phone": "+1234567890",
    "role": "member",
    "is_active": true,
    "created_at": "2026-03-01T10:00:00"
  },
  {
    "id": 2,
    "username": "admin_user",
    "full_name": "admin_user",
    "email": "admin@example.com",
    "phone": "+1122334455",
    "role": "admin",
    "is_active": true,
    "created_at": "2026-02-15T09:00:00"
  }
]
```

**Error Responses:**
- **401 Unauthorized:** No token or invalid token
- **403 Forbidden:** User is not admin/superadmin

---

## Invite Management

### 1. Create Invite
**POST** `/invites/`

**Description:** Generate new invite code

**Authorization:** Admin/Superadmin only

**Request Body:**
```json
{
  "email": "newuser@example.com (optional)",
  "phone": "+1234567890 (optional)",
  "expiry_date": "2026-04-01T23:59:59 (optional, ISO 8601 format)",
  "expires_at": "2026-04-01T23:59:59 (optional, alternative field)"
}
```

**Response (201 Created):**
```json
{
  "id": 5,
  "invite_code": "INV-XYZ789",
  "email": "newuser@example.com",
  "phone": "+1234567890",
  "is_used": false,
  "expiry_date": "2026-04-01T23:59:59",
  "created_at": "2026-03-03T10:00:00"
}
```

**Error Responses:**
- **403 Forbidden:** User is not admin
- **422 Validation Error:** Invalid data format

---

### 2. Get All Invites
**GET** `/invites/`

**Description:** Retrieve all invite codes with filtering and sorting

**Authorization:** Admin/Superadmin only

**Query Parameters:**
- `skip` (integer, default: 0): Pagination offset
- `limit` (integer, default: 100): Max records
- `is_used` (boolean, optional): Filter by usage status
- `email` (string, optional): Filter by email
- `phone` (string, optional): Filter by phone
- `sort_by` (string, default: "created_at"): Sort field
- `sort_order` (string, default: "desc"): Sort order (`asc` or `desc`)

**Example Request:**
```
GET /invites/?skip=0&limit=50&is_used=false&sort_by=created_at&sort_order=desc
```

**Response (200 OK):**
```json
[
  {
    "id": 5,
    "invite_code": "INV-XYZ789",
    "email": "newuser@example.com",
    "phone": "+1234567890",
    "is_used": false,
    "expiry_date": "2026-04-01T23:59:59",
    "created_at": "2026-03-03T10:00:00"
  }
]
```

---

### 3. Get Pending Invites
**GET** `/invites/pending`

**Description:** Get all unused invite codes

**Authorization:** Admin/Superadmin only

**Response (200 OK):**
```json
[
  {
    "id": 5,
    "invite_code": "INV-XYZ789",
    "email": "newuser@example.com",
    "phone": null,
    "is_used": false,
    "expiry_date": "2026-04-01T23:59:59",
    "created_at": "2026-03-03T10:00:00"
  }
]
```

---

### 4. Validate Invite
**POST** `/invites/validate`

**Description:** Check if invite code is valid for given email/phone

**Authorization:** None (Public)

**Query Parameters:**
- `email_or_phone` (string, required): Email or phone number
- `invite_code` (string, required): Invite code to validate

**Example Request:**
```
POST /invites/validate?email_or_phone=user@example.com&invite_code=INV-XYZ789
```

**Response (200 OK):**
```json
{
  "valid": true,
  "message": "Invite code is valid"
}
```

**Response (400 Bad Request):**
```json
{
  "detail": [
    {
      "type": "validation_error",
      "loc": ["body"],
      "msg": "Invalid or expired invite code",
      "input": null
    }
  ]
}
```

---

### 5. Get Invite by ID
**GET** `/invites/{invite_id}`

**Description:** Get specific invite details

**Authorization:** Admin/Superadmin only

**Path Parameters:**
- `invite_id` (integer, required): Invite ID

**Response (200 OK):**
```json
{
  "id": 5,
  "invite_code": "INV-XYZ789",
  "email": "newuser@example.com",
  "phone": "+1234567890",
  "is_used": false,
  "expiry_date": "2026-04-01T23:59:59",
  "created_at": "2026-03-03T10:00:00"
}
```

**Error Responses:**
- **404 Not Found:** Invite not found

---

### 6. Update Invite
**PUT** `/invites/{invite_id}`

**Description:** Update invite details

**Authorization:** Admin/Superadmin only

**Path Parameters:**
- `invite_id` (integer, required): Invite ID

**Request Body:**
```json
{
  "email": "updated@example.com (optional)",
  "phone": "+9876543210 (optional)",
  "expiry_date": "2026-05-01T23:59:59 (optional)",
  "expires_at": "2026-05-01T23:59:59 (optional)"
}
```

**Response (200 OK):**
```json
{
  "id": 5,
  "invite_code": "INV-XYZ789",
  "email": "updated@example.com",
  "phone": "+9876543210",
  "is_used": false,
  "expiry_date": "2026-05-01T23:59:59",
  "created_at": "2026-03-03T10:00:00"
}
```

---

### 7. Delete Invite
**DELETE** `/invites/{invite_id}`

**Description:** Delete invite code

**Authorization:** Admin/Superadmin only

**Path Parameters:**
- `invite_id` (integer, required): Invite ID

**Response (200 OK):**
```json
{
  "message": "Invite deleted successfully"
}
```

---

## Member Management

### 1. Get All Members
**GET** `/members/`

**Description:** Retrieve all members with pagination

**Authorization:** Admin/Superadmin only

**Query Parameters:**
- `skip` (integer, default: 0): Pagination offset
- `limit` (integer, default: 100): Max records

**Example Request:**
```
GET /members/?skip=0&limit=50
```

**Response (200 OK):**
```json
[
  {
    "id": 1,
    "user_id": 5,
    "full_name": "john_doe",
    "member_code": "MEM-2026-001",
    "monthly_amount": 500.0,
    "address": "123 Main St, City",
    "join_date": "2026-01-15T10:00:00",
    "status": "active",
    "created_at": "2026-01-15T10:00:00",
    "updated_at": "2026-03-01T12:00:00"
  }
]
```

---

### 2. Get My Member Profile
**GET** `/members/me`

**Description:** Get current user's member profile

**Authorization:** Required (Any authenticated user)

**Response (200 OK):**
```json
{
  "id": 1,
  "user_id": 5,
  "full_name": "john_doe",
  "member_code": "MEM-2026-001",
  "monthly_amount": 500.0,
  "address": "123 Main St, City",
  "join_date": "2026-01-15T10:00:00",
  "status": "active",
  "created_at": "2026-01-15T10:00:00",
  "updated_at": "2026-03-01T12:00:00"
}
```

**Error Responses:**
- **404 Not Found:** Member profile not found for user

---

### 3. Get Member by Code
**GET** `/members/code/{member_code}`

**Description:** Retrieve member by member code

**Authorization:** Admin/Superadmin only

**Path Parameters:**
- `member_code` (string, required): Member code (e.g., "MEM-2026-001")

**Response (200 OK):**
```json
{
  "id": 1,
  "user_id": 5,
  "full_name": "john_doe",
  "member_code": "MEM-2026-001",
  "monthly_amount": 500.0,
  "address": "123 Main St, City",
  "join_date": "2026-01-15T10:00:00",
  "status": "active",
  "created_at": "2026-01-15T10:00:00",
  "updated_at": "2026-03-01T12:00:00"
}
```

**Error Responses:**
- **404 Not Found:** Member not found

---

### 4. Get Member by ID
**GET** `/members/{member_id}`

**Description:** Get member details by ID

**Authorization:** Admin/Superadmin or own profile

**Path Parameters:**
- `member_id` (integer, required): Member ID

**Response (200 OK):**
```json
{
  "id": 1,
  "user_id": 5,
  "full_name": "john_doe",
  "member_code": "MEM-2026-001",
  "monthly_amount": 500.0,
  "address": "123 Main St, City",
  "join_date": "2026-01-15T10:00:00",
  "status": "active",
  "created_at": "2026-01-15T10:00:00",
  "updated_at": "2026-03-01T12:00:00"
}
```

**Error Responses:**
- **403 Forbidden:** Not authorized to view this profile
- **404 Not Found:** Member not found

---

### 5. Update Member
**PUT** `/members/{member_id}`

**Description:** Update member information

**Authorization:** Admin/Superadmin only

**Path Parameters:**
- `member_id` (integer, required): Member ID

**Request Body:**
```json
{
  "monthly_amount": 600.0,
  "address": "456 New Address",
  "status": "active"
}
```

**Canonical Writable Fields (confirmed 2026-03-03):**
- `monthly_amount` (float, optional): Monthly donation amount
- `address` (string, optional): Member address
- `status` (string, optional): Member status (`active`, `inactive`, `suspended`)

**Frontend Note:** If additional fields (`full_name`, `phone`, `email`, `city`, `notes`, `member_code`) need to be editable, please update this endpoint contract. Currently, these are not mapped to writable fields in the backend update schema.

*Note: All fields are optional. Send only fields to update.*

**Response (200 OK):**
```json
{
  "id": 1,
  "user_id": 5,
  "full_name": "john_doe",
  "member_code": "MEM-2026-001",
  "monthly_amount": 600.0,
  "address": "456 New Address",
  "join_date": "2026-01-15T10:00:00",
  "status": "active",
  "created_at": "2026-01-15T10:00:00",
  "updated_at": "2026-03-03T15:30:00"
}
```

---

## Campaign Management

### 1. Create Campaign
**POST** `/campaigns/`

**Description:** Create new fundraising campaign

**Authorization:** Admin/Superadmin only

**Request Body:**
```json
{
  "title": "Ramadan Food Drive 2026",
  "description": "Providing food packages for families in need during Ramadan",
  "target_amount": 50000.0,
  "start_date": "2026-03-10T00:00:00",
  "end_date": "2026-04-10T23:59:59"
}
```

**Response (201 Created):**
```json
{
  "id": 3,
  "title": "Ramadan Food Drive 2026",
  "description": "Providing food packages for families in need during Ramadan",
  "target_amount": 50000.0,
  "start_date": "2026-03-10T00:00:00",
  "end_date": "2026-04-10T23:59:59",
  "is_active": true,
  "created_at": "2026-03-03T10:00:00",
  "updated_at": "2026-03-03T10:00:00"
}
```

**Error Responses:**
- **400 Bad Request:** Invalid dates or amount
- **403 Forbidden:** Not admin
- **500 Internal Server Error:** Failed to create campaign

---

### 2. Get All Campaigns
**GET** `/campaigns/`

**Description:** Retrieve all campaigns with pagination

**Authorization:** Required (Any authenticated user)

**Query Parameters:**
- `skip` (integer, default: 0, min: 0): Pagination offset
- `limit` (integer, default: 100, min: 1, max: 500): Max records
- `active_only` (boolean, default: false): Show only active campaigns

**Example Request:**
```
GET /campaigns/?skip=0&limit=20&active_only=true
```

**Response (200 OK):**
```json
[
  {
    "id": 3,
    "title": "Ramadan Food Drive 2026",
    "description": "Providing food packages for families in need during Ramadan",
    "target_amount": 50000.0,
    "start_date": "2026-03-10T00:00:00",
    "end_date": "2026-04-10T23:59:59",
    "is_active": true,
    "created_at": "2026-03-03T10:00:00",
    "updated_at": "2026-03-03T10:00:00"
  }
]
```

---

### 3. Get Campaign by ID
**GET** `/campaigns/{campaign_id}`

**Description:** Get specific campaign details

**Authorization:** Required (Any authenticated user)

**Path Parameters:**
- `campaign_id` (integer, required): Campaign ID

**Response (200 OK):**
```json
{
  "id": 3,
  "title": "Ramadan Food Drive 2026",
  "description": "Providing food packages for families in need during Ramadan",
  "target_amount": 50000.0,
  "start_date": "2026-03-10T00:00:00",
  "end_date": "2026-04-10T23:59:59",
  "is_active": true,
  "created_at": "2026-03-03T10:00:00",
  "updated_at": "2026-03-03T10:00:00"
}
```

**Error Responses:**
- **404 Not Found:** Campaign not found

---

### 4. Update Campaign
**PATCH** `/campaigns/{campaign_id}` (Recommended)  
**PUT** `/campaigns/{campaign_id}` (Also Supported)

**Description:** Update campaign fields

**Authorization:** Admin/Superadmin only

**Path Parameters:**
- `campaign_id` (integer, required): Campaign ID

**Methods:**
- **PATCH** (Recommended): Semantically correct for partial updates. Only send fields to update.
- **PUT** (Also Supported): Accepted for compatibility. Same behavior as PATCH.

**Request Body:**
```json
{
  "title": "Updated Campaign Title (optional)",
  "description": "Updated description (optional)",
  "target_amount": 60000.0,
  "start_date": "2026-03-15T00:00:00 (optional)",
  "end_date": "2026-04-15T23:59:59 (optional)",
  "is_active": false
}
```
*Note: All fields are optional. Send only fields to update.*

**Response (200 OK):**
```json
{
  "id": 3,
  "title": "Updated Campaign Title",
  "description": "Updated description",
  "target_amount": 60000.0,
  "start_date": "2026-03-15T00:00:00",
  "end_date": "2026-04-15T23:59:59",
  "is_active": false,
  "created_at": "2026-03-03T10:00:00",
  "updated_at": "2026-03-03T16:00:00"
}
```

**Error Responses:**
- **400 Bad Request:** Invalid data
- **404 Not Found:** Campaign not found

**Note:** Both PUT and PATCH methods work identically. Use PATCH for semantic correctness.

---

### 5. Delete Campaign
**DELETE** `/campaigns/{campaign_id}`

**Description:** Delete campaign

**Authorization:** Admin/Superadmin only

**Path Parameters:**
- `campaign_id` (integer, required): Campaign ID

**Response (204 No Content):**
No response body

**Error Responses:**
- **404 Not Found:** Campaign not found
- **500 Internal Server Error:** Failed to delete

---

## Challan Management

### 1. Create Challan
**POST** `/challans/`

**Description:** Create new payment challan (single month per request)

**Authorization:** Required
- Member: Creates for self (single month only)
- Admin: Can specify member_id to create for any member (single month only)

**Request Body:**
```json
{
  "member_id": 1,
  "type": "monthly",
  "month": "2026-03",
  "campaign_id": null,
  "amount": 500.0,
  "payment_method": "bank_transfer"
}
```

**Field Details:**
- `member_id` (integer, optional): Required for admin, ignored for members
- `type` (string, required): `"monthly"` or `"campaign"`
- `month` (string, optional): YYYY-MM format (required for monthly type). **Note: Single month per challan. For multiple months, create separate challans.**
- `campaign_id` (integer, optional): Required for campaign type (cannot be combined with monthly type)
- `amount` (float, required): Payment amount
- `payment_method` (string, optional): e.g., "cash", "bank_transfer", "online"

**Frontend Note (2026-03-03):** Backend operates on single-month model. If frontend needs multi-month submission, it should create one challan per month or aggregate the amounts into a single challan. Backend confirms this behavior for consistency.

**Response (201 Created):**
```json
{
  "id": 10,
  "member_id": 1,
  "type": "monthly",
  "month": "2026-03",
  "campaign_id": null,
  "amount": 500.0,
  "payment_method": "bank_transfer",
  "proof_path": null,
  "status": "generated",
  "created_at": "2026-03-03T10:00:00",
  "proof_uploaded_at": null,
  "approved_at": null,
  "updated_at": "2026-03-03T10:00:00"
}
```

**Error Responses:**
- **400 Bad Request:** Member is inactive or invalid data
- **403 Forbidden:** Not authorized
- **404 Not Found:** Member not found

---

### 2. Upload Payment Proof
**POST** `/challans/{challan_id}/upload-proof`

**Description:** Upload payment proof image/PDF

**Authorization:** Required
- Member: Own challan only
- Admin: Any challan

**Path Parameters:**
- `challan_id` (integer, required): Challan ID

**Request Body:**
Form-data multipart/form-data
- `file` (file, required): Image or PDF file

**File Requirements:**
- **Allowed types:** image/jpeg, image/png, application/pdf
- **Max size:** 5 MB

**Response (200 OK):**
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
  "status": "pending",
  "created_at": "2026-03-03T10:00:00",
  "proof_uploaded_at": "2026-03-03T11:30:00",
  "approved_at": null,
  "updated_at": "2026-03-03T11:30:00"
}
```

**Error Responses:**
- **400 Bad Request:** Invalid file type or size
- **403 Forbidden:** Not authorized
- **404 Not Found:** Challan not found

---

### 3. Get All Challans (Admin)
**GET** `/challans/`

**Description:** Get all challans with filtering

**Authorization:** Admin/Superadmin only

**Query Parameters:**
- `skip` (integer, default: 0): Pagination offset
- `limit` (integer, default: 100): Max records
- `status_filter` (string, optional): Filter by status (`generated`, `pending`, `approved`, `rejected`)

**Example Request:**
```
GET /challans/?skip=0&limit=50&status_filter=pending
```

**Response (200 OK):**
```json
[
  {
    "id": 10,
    "member_id": 1,
    "type": "monthly",
    "month": "2026-03",
    "campaign_id": null,
    "amount": 500.0,
    "payment_method": "bank_transfer",
    "proof_path": "/uploads/proofs/abc123.jpg",
    "status": "pending",
    "created_at": "2026-03-03T10:00:00",
    "proof_uploaded_at": "2026-03-03T11:30:00",
    "approved_at": null,
    "updated_at": "2026-03-03T11:30:00"
  }
]
```

---

### 4. Get Member Challans
**GET** `/challans/member/{member_id}`

**Description:** Get all challans for specific member

**Authorization:** Required
- Admin: Any member
- Member: Own member_id only

**Path Parameters:**
- `member_id` (integer, required): Member ID

**Query Parameters:**
- `skip` (integer, default: 0): Pagination offset
- `limit` (integer, default: 100): Max records

**Response (200 OK):**
```json
[
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
]
```

**Error Responses:**
- **403 Forbidden:** Access denied

---

### 5. Get Single Challan
**GET** `/challans/{challan_id}`

**Description:** Get specific challan details

**Authorization:** Required
- Admin: Any challan
- Member: Own challan only

**Path Parameters:**
- `challan_id` (integer, required): Challan ID

**Response (200 OK):**
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
  "status": "pending",
  "created_at": "2026-03-03T10:00:00",
  "proof_uploaded_at": "2026-03-03T11:30:00",
  "approved_at": null,
  "updated_at": "2026-03-03T11:30:00"
}
```

**Error Responses:**
- **403 Forbidden:** Access denied
- **404 Not Found:** Challan not found

---

### 6. Approve Challan
**PATCH** `/challans/{challan_id}/approve`

**Description:** Approve pending challan

**Authorization:** Admin/Superadmin only

**Path Parameters:**
- `challan_id` (integer, required): Challan ID

**Request Body:**
```json
{
  "approved_by_admin_id": 2
}
```

**Response (200 OK):**
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

**Error Responses:**
- **400 Bad Request:** Challan already processed
- **404 Not Found:** Challan not found

---

### 7. Reject Challan
**PATCH** `/challans/{challan_id}/reject`

**Description:** Reject pending challan

**Authorization:** Admin/Superadmin only

**Path Parameters:**
- `challan_id` (integer, required): Challan ID

**Request Body:**
```json
{
  "rejection_reason": "Invalid payment proof or amount mismatch"
}
```

**Response (200 OK):**
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
  "status": "rejected",
  "created_at": "2026-03-03T10:00:00",
  "proof_uploaded_at": "2026-03-03T11:30:00",
  "approved_at": null,
  "updated_at": "2026-03-04T09:15:00"
}
```

**Error Responses:**
- **400 Bad Request:** Challan already processed
- **404 Not Found:** Challan not found

---

## Bulk Challan Operations (v1.1)

### Overview

**Purpose:** Enable efficient high-volume payment processing for members who pay multiple months in single transaction.

**Use Case:** Member has 100 Rs monthly amount, pays 500 Rs in one proof for 5 months → Admin approves all 5 in single action (instead of 5 times).

**Impact:** Reduces admin time per bulk payment from 5 minutes to 30 seconds. Scalable to 500+ members.

| Feature | Single-Month Flow | Bulk Flow |
|---------|-------------------|-----------|
| Create Challans | 5 separate API calls | 1 API call (POST /challans/bulk-create) |
| Upload Proof | 5 times | 1 time (shared across all) |
| Admin Review | 5 separate approvals | 1 approval (all 5 at once) |
| Time per bulk | 5 minutes | 30 seconds |

### 1. Create Bulk Challans
**POST** `/challans/bulk-create`

**Description:** Create multiple challans for different months linked to single proof

**Authorization:** Required (Members and Admins)
- Member: Creates only for self
- Admin/Superadmin: Can create for any active member

**Request Body:**
```json
{
  "months": ["2026-01", "2026-02", "2026-03", "2026-04", "2026-05"],
  "amount_per_month": 100,
  "proof_file_id": "550e8400-e29b-41d4-a716-446655440000",
  "member_id": 5,
  "notes": "Q1 2026 bulk payment"
}
```

**Request Parameters:**
- `months` (array of strings, required): List of months (YYYY-MM format). Example: ["2026-01", "2026-02"]
- `amount_per_month` (number, required): Amount for each month. Example: 100.0
- `proof_file_id` (string, required): File UUID from `/files/upload` endpoint
- `member_id` (integer, optional for member, required for admin): Target member ID
- `notes` (string, optional): Additional notes for admin review

**Response (201 Created):**
```json
{
  "bulk_group_id": "bulk-20260303-001",
  "member_id": 5,
  "created_challans": 5,
  "challan_ids": [101, 102, 103, 104, 105],
  "months": ["2026-01", "2026-02", "2026-03", "2026-04", "2026-05"],
  "total_amount": 500.0,
  "proof_file_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "pending_approval",
  "created_at": "2026-03-03T10:30:00",
  "notes": "Q1 2026 bulk payment"
}
```

**Response Fields:**
- `bulk_group_id` (string): Unique identifier for this bulk operation. Use this for approval/rejection.
- `challan_ids` (array): IDs of individual challans created
- `status` (string): Always "pending_approval" for new bulk operations
- `total_amount` (number): Sum of all monthly amounts

**Error Responses:**
- **400 Bad Request:** Invalid month format, duplicate months, or proof not found
- **403 Forbidden:** Not authorized (member creating for another member, non-admin)
- **404 Not Found:** Member not found or inactive
- **422 Unprocessable Entity:** Validation error (empty months array, amount <= 0)
- **500 Internal Server Error:** Server error

**Example cURL:**
```bash
curl -X POST http://localhost:8000/challans/bulk-create \
  -H "Authorization: Bearer <access_token>" \
  -H "Content-Type: application/json" \
  -d '{
    "months": ["2026-01", "2026-02", "2026-03"],
    "amount_per_month": 100,
    "proof_file_id": "550e8400-e29b-41d4-a716-446655440000",
    "notes": "Quarterly payment"
  }'
```

---

### 2. Get Pending Bulk Operations (Admin Only)
**GET** `/admin/bulk-pending-review`

**Description:** Get all pending bulk challan operations for admin review and approval

**Authorization:** Admin/Superadmin only

**Query Parameters (Optional):**
- `days` (integer): Filter by created in last N days. Default: 7
- `sort_by` (string): Sort field. Options: `created_at`, `member_name`, `total_amount`. Default: `created_at`
- `order` (string): Sort order. Options: `asc`, `desc`. Default: `desc`

**Response (200 OK):**
```json
{
  "pending": 3,
  "bulk_operations": [
    {
      "bulk_group_id": "bulk-20260303-001",
      "member_id": 5,
      "member_name": "Ahmed Khan",
      "member_email": "ahmed@example.com",
      "months": ["2026-01", "2026-02", "2026-03", "2026-04", "2026-05"],
      "months_count": 5,
      "total_amount": 500.0,
      "amount_per_month": 100.0,
      "proof_file_id": "550e8400-e29b-41d4-a716-446655440000",
      "proof_url": "http://localhost:8000/uploads/proofs/abc123.jpg",
      "status": "pending_approval",
      "created_at": "2026-03-03T10:30:00",
      "created_by_email": "ahmed@example.com",
      "notes": "Q1 2026 bulk payment"
    },
    {
      "bulk_group_id": "bulk-20260302-002",
      "member_id": 8,
      "member_name": "Fatima Ahmad",
      "member_email": "fatima@example.com",
      "months": ["2026-02", "2026-03"],
      "months_count": 2,
      "total_amount": 200.0,
      "amount_per_month": 100.0,
      "proof_file_id": "660e8400-e29b-41d4-a716-446655440000",
      "proof_url": "http://localhost:8000/uploads/proofs/def456.jpg",
      "status": "pending_approval",
      "created_at": "2026-03-02T14:15:00",
      "created_by_email": "fatima@example.com",
      "notes": null
    }
  ]
}
```

**Error Responses:**
- **401 Unauthorized:** No valid token
- **403 Forbidden:** User is not admin/superadmin
- **500 Internal Server Error:** Server error

**Example cURL:**
```bash
curl -X GET 'http://localhost:8000/admin/bulk-pending-review?days=7&sort_by=created_at&order=desc' \
  -H "Authorization: Bearer <admin_token>"
```

---

### 3. Approve Bulk Challans
**PATCH** `/admin/bulk/{bulk_group_id}/approve`

**Description:** Approve all challans in a bulk group in a single action

**Authorization:** Admin/Superadmin only

**Path Parameters:**
- `bulk_group_id` (string, required): Bulk group ID from `/challans/bulk-create` response

**Request Body:**
```json
{
  "admin_notes": "Proof verified. Payment confirmed to bank account.",
  "approved": true
}
```

**Request Fields:**
- `approved` (boolean, required): Must be true to approve
- `admin_notes` (string, optional): Admin review notes (visible in audit log)

**Response (200 OK):**
```json
{
  "bulk_group_id": "bulk-20260303-001",
  "status": "approved",
  "approved_challans": 5,
  "challan_ids": [101, 102, 103, 104, 105],
  "months_approved": ["2026-01", "2026-02", "2026-03", "2026-04", "2026-05"],
  "total_amount_approved": 500.0,
  "approved_by": "admin@example.com",
  "approved_at": "2026-03-03T11:00:00",
  "admin_notes": "Proof verified. Payment confirmed to bank account."
}
```

**Response Fields:**
- `approved_challans` (integer): Number of challans approved (should match months_count)
- `approved_by` (string): Email of approving admin
- `status` (string): Now "approved"

**Audit Log Entry:**
- Action: `bulk_approve`
- Entity: Bulk group
- Details: "Approved 5 months for member [name]: [notes]"

**Error Responses:**
- **401 Unauthorized:** No valid token
- **403 Forbidden:** User is not admin/superadmin
- **404 Not Found:** Bulk group not found
- **400 Bad Request:** Bulk group already approved or rejected
- **422 Unprocessable Entity:** Validation error (approved != true)
- **500 Internal Server Error:** Server error

**Example cURL:**
```bash
curl -X PATCH http://localhost:8000/admin/bulk/bulk-20260303-001/approve \
  -H "Authorization: Bearer <admin_token>" \
  -H "Content-Type: application/json" \
  -d '{
    "approved": true,
    "admin_notes": "Proof verified"
  }'
```

---

### 4. Reject Bulk Challans
**PATCH** `/admin/bulk/{bulk_group_id}/reject`

**Description:** Reject all challans in a bulk group and delete associated records

**Authorization:** Admin/Superadmin only

**Path Parameters:**
- `bulk_group_id` (string, required): Bulk group ID

**Request Body:**
```json
{
  "reason": "Proof image quality too low. Please resubmit with clearer image.",
  "action": "delete"
}
```

**Request Fields:**
- `reason` (string, required): Reason for rejection (visible to member)
- `action` (string, required): Action to take. Options: `delete` (delete all challans)

**Response (200 OK):**
```json
{
  "bulk_group_id": "bulk-20260303-001",
  "status": "rejected",
  "rejected_challans": 5,
  "challan_ids": [101, 102, 103, 104, 105],
  "rejected_at": "2026-03-03T11:05:00",
  "reason": "Proof image quality too low. Please resubmit with clearer image.",
  "rejected_by": "admin@example.com"
}
```

**Audit Log Entry:**
- Action: `bulk_reject`
- Entity: Bulk group
- Details: "Rejected 5 months for member [name]: [reason]"

**Notification to Member:**
- Type: REJECTION
- Message: "Your bulk payment submission for 5 months was rejected: [reason]"
- Action: Member can resubmit with new proof

**Error Responses:**
- **401 Unauthorized:** No valid token
- **403 Forbidden:** User is not admin/superadmin
- **404 Not Found:** Bulk group not found
- **400 Bad Request:** Bulk group already approved
- **422 Unprocessable Entity:** Validation error (invalid action or reason missing)
- **500 Internal Server Error:** Server error

**Example cURL:**
```bash
curl -X PATCH http://localhost:8000/admin/bulk/bulk-20260303-001/reject \
  -H "Authorization: Bearer <admin_token>" \
  -H "Content-Type: application/json" \
  -d '{
    "reason": "Proof unclear. Please resubmit.",
    "action": "delete"
  }'
```

---

### 5. Get Bulk Operation Details
**GET** `/admin/bulk/{bulk_group_id}`

**Description:** Get detailed information about a specific bulk operation including all linked challans

**Authorization:** Admin/Superadmin only

**Path Parameters:**
- `bulk_group_id` (string, required): Bulk group ID

**Response (200 OK):**
```json
{
  "bulk_group_id": "bulk-20260303-001",
  "member_id": 5,
  "member_name": "Ahmed Khan",
  "member_email": "ahmed@example.com",
  "months": ["2026-01", "2026-02", "2026-03", "2026-04", "2026-05"],
  "total_amount": 500.0,
  "amount_per_month": 100.0,
  "proof_file_id": "550e8400-e29b-41d4-a716-446655440000",
  "proof_url": "http://localhost:8000/uploads/proofs/abc123.jpg",
  "status": "pending_approval",
  "created_at": "2026-03-03T10:30:00",
  "created_by_email": "ahmed@example.com",
  "approved_at": null,
  "approved_by": null,
  "admin_notes": null,
  "notes": "Q1 2026 bulk payment",
  "linked_challans": [
    {
      "challan_id": 101,
      "month": "2026-01",
      "amount": 100.0,
      "status": "pending",
      "created_at": "2026-03-03T10:30:00"
    },
    {
      "challan_id": 102,
      "month": "2026-02",
      "amount": 100.0,
      "status": "pending",
      "created_at": "2026-03-03T10:30:00"
    }
  ]
}
```

**Error Responses:**
- **401 Unauthorized:** No valid token
- **403 Forbidden:** User is not admin/superadmin
- **404 Not Found:** Bulk group not found
- **500 Internal Server Error:** Server error

---

## Notification Management

### 1. Create Notification
**POST** `/notifications/`

**Description:** Create and send notification

**Authorization:** Admin/Superadmin only

**Request Body:**
```json
{
  "user_id": 5,
  "title": "Payment Approved",
  "message": "Your March 2026 payment has been approved.",
  "target_role": null
}
```

**Field Details:**
- `user_id` (integer, optional): Send to specific user
- `title` (string, required): Notification title
- `message` (string, required): Notification message
- `target_role` (string, optional): Send to all users with role (`superadmin`, `admin`, `member`)
- If both `user_id` and `target_role` are null, sends to all users

**Response (201 Created):**
```json
{
  "sent_count": 1,
  "message": "Notification sent successfully"
}
```

---

### 2. Get My Notifications
**GET** `/notifications/`

**Description:** Get current user's notifications

**Authorization:** Required (Any authenticated user)

**Query Parameters:**
- `skip` (integer, default: 0): Pagination offset
- `limit` (integer, default: 50): Max records

**Response (200 OK):**
```json
[
  {
    "id": 25,
    "user_id": 5,
    "title": "Payment Approved",
    "message": "Your March 2026 payment has been approved.",
    "is_read": false,
    "created_at": "2026-03-04T09:00:00",
    "read_at": null
  },
  {
    "id": 24,
    "user_id": 5,
    "title": "Welcome to CharityConnect",
    "message": "Thank you for joining our community.",
    "is_read": true,
    "created_at": "2026-03-01T10:00:00",
    "read_at": "2026-03-01T15:30:00"
  }
]
```

---

### 3. Get Unread Count
**GET** `/notifications/unread/count`

**Description:** Get count of unread notifications

**Authorization:** Required (Any authenticated user)

**Response (200 OK):**
```json
{
  "unread_count": 3
}
```

---

### 4. Get Notification by ID
**GET** `/notifications/{notification_id}`

**Description:** Get specific notification

**Authorization:** Required (Own notification only)

**Path Parameters:**
- `notification_id` (integer, required): Notification ID

**Response (200 OK):**
```json
{
  "id": 25,
  "user_id": 5,
  "title": "Payment Approved",
  "message": "Your March 2026 payment has been approved.",
  "is_read": false,
  "created_at": "2026-03-04T09:00:00",
  "read_at": null
}
```

**Error Responses:**
- **403 Forbidden:** Not your notification
- **404 Not Found:** Notification not found

---

### 5. Mark Notification as Read
**PUT** `/notifications/{notification_id}/read`

**Description:** Mark notification as read

**Authorization:** Required (Own notification only)

**Path Parameters:**
- `notification_id` (integer, required): Notification ID

**Response (200 OK):**
```json
{
  "id": 25,
  "user_id": 5,
  "title": "Payment Approved",
  "message": "Your March 2026 payment has been approved.",
  "is_read": true,
  "created_at": "2026-03-04T09:00:00",
  "read_at": "2026-03-04T10:30:00"
}
```

---

### 6. Mark All as Read
**POST** `/notifications/mark-all-read`

**Description:** Mark all user's notifications as read

**Authorization:** Required (Any authenticated user)

**Response (200 OK):**
```json
{
  "updated_count": 5,
  "message": "All notifications marked as read"
}
```

---

### 7. Update Notification (Admin)
**PUT** `/notifications/{notification_id}`

**Description:** Update notification content

**Authorization:** Admin/Superadmin only

**Path Parameters:**
- `notification_id` (integer, required): Notification ID

**Request Body:**
```json
{
  "title": "Updated Title (optional)",
  "message": "Updated message (optional)",
  "is_read": true
}
```

**Response (200 OK):**
```json
{
  "id": 25,
  "user_id": 5,
  "title": "Updated Title",
  "message": "Updated message",
  "is_read": true,
  "created_at": "2026-03-04T09:00:00",
  "read_at": "2026-03-04T11:00:00"
}
```

---

### 8. Delete Notification
**DELETE** `/notifications/{notification_id}`

**Description:** Delete notification

**Authorization:** Admin/Superadmin only

**Path Parameters:**
- `notification_id` (integer, required): Notification ID

**Response (204 No Content):**
No response body

---

## File Management

### 1. Upload File
**POST** `/files/upload`

**Description:** Upload file to server

**Authorization:** Required (Any authenticated user)

**Request Body:**
Form-data multipart/form-data
- `file` (file, required): Image or PDF file

**File Requirements:**
- **Allowed types:** image/jpeg (.jpg), image/png (.png), application/pdf (.pdf)
- **Max size:** 3 MB

**Response (200 OK):**
```json
{
  "file_url": "/uploads/proofs/550e8400-e29b-41d4-a716-446655440000.jpg",
  "filename": "550e8400-e29b-41d4-a716-446655440000.jpg"
}
```

**Error Responses:**
- **400 Bad Request:**
  - Invalid file type
  - File too large

**Usage Example (JavaScript):**
```javascript
const formData = new FormData();
formData.append('file', fileInput.files[0]);

const response = await fetch('http://localhost:8000/files/upload', {
  method: 'POST',
  headers: {
    'Authorization': 'Bearer ' + accessToken
  },
  body: formData
});

const result = await response.json();
console.log(result.file_url);
```

---

## Audit Log Management

### 1. Get Audit Logs
**GET** `/audit-logs/`

**Description:** Retrieve audit logs with filtering

**Authorization:** Admin/Superadmin only

**Query Parameters:**
- `skip` (integer, default: 0): Pagination offset
- `limit` (integer, default: 100): Max records
- `user_id` (integer, optional): Filter by user ID
- `entity_type` (string, optional): Filter by entity type (e.g., "Member", "Challan", "Campaign")
- `action` (string, optional): Filter by action (e.g., "create", "update", "delete", "approve")

**Example Request:**
```
GET /audit-logs/?skip=0&limit=50&entity_type=Challan&action=approve
```

**Response (200 OK):**
```json
[
  {
    "id": 150,
    "user_id": 2,
    "action": "approve",
    "entity_type": "Challan",
    "entity_id": 10,
    "old_values": "{\"status\": \"pending\"}",
    "new_values": "{\"status\": \"approved\", \"approved_at\": \"2026-03-04T09:00:00\"}",
    "ip_address": "192.168.1.100",
    "created_at": "2026-03-04T09:00:00"
  }
]
```

---

### 2. Create Audit Log
**POST** `/audit-logs/`

**Description:** Manually create audit log entry

**Authorization:** Admin/Superadmin only

**Request Body:**
```json
{
  "user_id": 2,
  "action": "update",
  "entity_type": "Member",
  "entity_id": 5,
  "old_values": "{\"monthly_amount\": 500.0}",
  "new_values": "{\"monthly_amount\": 600.0}",
  "ip_address": "192.168.1.50"
}
```

**Response (201 Created):**
```json
{
  "id": 151,
  "user_id": 2,
  "action": "update",
  "entity_type": "Member",
  "entity_id": 5,
  "old_values": "{\"monthly_amount\": 500.0}",
  "new_values": "{\"monthly_amount\": 600.0}",
  "ip_address": "192.168.1.50",
  "created_at": "2026-03-04T10:00:00"
}
```

---

## Error Response Format

All error responses follow a consistent format:

### Standard Error Response
```json
{
  "detail": [
    {
      "type": "validation_error",
      "loc": ["body", "field_name"],
      "msg": "Error message describing the issue",
      "input": "user_provided_value"
    }
  ]
}
```

### Common HTTP Status Codes

| Status Code | Meaning | When It Occurs |
|-------------|---------|----------------|
| **200** | OK | Successful GET/PATCH/PUT request |
| **201** | Created | Successful POST request creating resource |
| **204** | No Content | Successful DELETE request |
| **400** | Bad Request | Invalid input data or business logic error |
| **401** | Unauthorized | Missing or invalid authentication token |
| **403** | Forbidden | Valid token but insufficient permissions |
| **404** | Not Found | Resource does not exist |
| **422** | Unprocessable Entity | Validation error (invalid data format) |
| **500** | Internal Server Error | Server-side error |

### Error Examples

**Validation Error (422):**
```json
{
  "detail": [
    {
      "type": "validation_error",
      "loc": ["body", "email"],
      "msg": "value is not a valid email address",
      "input": "invalid-email"
    },
    {
      "type": "validation_error",
      "loc": ["body", "password"],
      "msg": "field required",
      "input": null
    }
  ]
}
```

**Authentication Error (401):**
```json
{
  "detail": [
    {
      "type": "http_error",
      "loc": ["request"],
      "msg": "Could not validate credentials",
      "input": null
    }
  ]
}
```

**Authorization Error (403):**
```json
{
  "detail": [
    {
      "type": "http_error",
      "loc": ["request"],
      "msg": "Admin access required",
      "input": null
    }
  ]
}
```

**Not Found Error (404):**
```json
{
  "detail": [
    {
      "type": "http_error",
      "loc": ["request"],
      "msg": "Campaign 999 not found",
      "input": null
    }
  ]
}
```

**Business Logic Error (400):**
```json
{
  "detail": [
    {
      "type": "http_error",
      "loc": ["body"],
      "msg": "Cannot create challan for inactive member",
      "input": null
    }
  ]
}
```

---

## Data Types & Enums

### UserRole Enum
```
- "superadmin"
- "admin"
- "member"
```

### ChallanStatus Enum
```
- "generated" - Challan created but no proof uploaded
- "pending" - Proof uploaded, awaiting admin approval
- "approved" - Payment approved by admin
- "rejected" - Payment rejected by admin
```

### ChallanType Enum
```
- "monthly" - Regular monthly donation
- "campaign" - Campaign-specific donation
```

### Date/Time Format
All date/time values use **ISO 8601** format:
```
YYYY-MM-DDTHH:MM:SS
Example: 2026-03-04T15:30:00
```

### Phone Number Format
**Recommended format:** Include country code
```
Examples:
+1234567890
+92 300 1234567
```

### Member Code Format
```
Pattern: MEM-YYYY-XXX
Example: MEM-2026-001
```

### Invite Code Format
```
Pattern: INV-XXXXXX (randomly generated)
Example: INV-ABC123
```

### Month Format (for Challans)
```
Pattern: YYYY-MM
Example: 2026-03
```

---

## Authentication Flow Examples

### New User Registration Flow

1. **Frontend requests invite validation** (optional)
```
POST /invites/validate?email_or_phone=user@example.com&invite_code=INV-ABC123
```

2. **User completes registration form**
```
POST /auth/register
{
  "invite_code": "INV-ABC123",
  "username": "new_user",
  "password": "securePassword123",
  "email": "user@example.com",
  "phone": "+1234567890",
  "full_name": "John Doe",
  "address": "123 Main St",
  "monthly_amount": 500.0
}
```

3. **Backend returns token and user details**
```json
{
  "access_token": "eyJhbGc...",
  "token_type": "bearer",
  "user": { /* user details */ }
}
```

4. **Frontend stores token and navigates to dashboard**

### Existing User Login Flow

1. **User submits credentials**
```
POST /auth/login
{
  "email": "user@example.com",
  "password": "securePassword123"
}
```

2. **Backend returns token**
```json
{
  "access_token": "eyJhbGc...",
  "token_type": "bearer",
  "user": { /* user details */ }
}
```

3. **Frontend stores token in localStorage/sessionStorage**
```javascript
localStorage.setItem('access_token', response.access_token);
localStorage.setItem('user', JSON.stringify(response.user));
```

4. **All subsequent requests include token**
```javascript
headers: {
  'Authorization': `Bearer ${localStorage.getItem('access_token')}`
}
```

---

## Challan Workflow Examples

### Member Creating Monthly Challan

1. **Get member profile to verify active status**
```
GET /members/me
Authorization: Bearer <token>
```

2. **Create challan**
```
POST /challans/
Authorization: Bearer <token>
{
  "type": "monthly",
  "month": "2026-03",
  "amount": 500.0,
  "payment_method": "bank_transfer"
}
```

3. **Upload payment proof**
```
POST /challans/10/upload-proof
Authorization: Bearer <token>
Content-Type: multipart/form-data

file: [binary data]
```

4. **Check challan status periodically**
```
GET /challans/10
Authorization: Bearer <token>
```

### Admin Approving Challan

1. **Get all pending challans**
```
GET /challans/?status_filter=pending
Authorization: Bearer <admin_token>
```

2. **Review specific challan**
```
GET /challans/10
Authorization: Bearer <admin_token>
```

3. **Approve challan**
```
PATCH /challans/10/approve
Authorization: Bearer <admin_token>
{
  "approved_by_admin_id": 2
}
```

OR **Reject challan**
```
PATCH /challans/10/reject
Authorization: Bearer <admin_token>
{
  "rejection_reason": "Invalid payment proof"
}
```

---

## Campaign Contribution Flow

### Contributing to Campaign

1. **Browse active campaigns**
```
GET /campaigns/?active_only=true
Authorization: Bearer <token>
```

2. **View campaign details**
```
GET /campaigns/3
Authorization: Bearer <token>
```

3. **Create campaign challan**
```
POST /challans/
Authorization: Bearer <token>
{
  "type": "campaign",
  "campaign_id": 3,
  "amount": 1000.0,
  "payment_method": "online"
}
```

4. **Upload payment proof**
```
POST /challans/11/upload-proof
Authorization: Bearer <token>
[file upload]
```

---

## Pagination Best Practices

All list endpoints support pagination using `skip` and `limit` parameters:

```javascript
// Page 1 (first 20 items)
GET /campaigns/?skip=0&limit=20

// Page 2 (next 20 items)
GET /campaigns/?skip=20&limit=20

// Page 3 (next 20 items)
GET /campaigns/?skip=40&limit=20
```

**Frontend Implementation:**
```javascript
const page = 1; // Current page (1-based)
const itemsPerPage = 20;
const skip = (page - 1) * itemsPerPage;

const url = `/campaigns/?skip=${skip}&limit=${itemsPerPage}`;
```

---

## File Upload Implementation

### JavaScript/Fetch Example
```javascript
async function uploadPaymentProof(challanId, file, token) {
  const formData = new FormData();
  formData.append('file', file);

  const response = await fetch(`http://localhost:8000/challans/${challanId}/upload-proof`, {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${token}`
    },
    body: formData
  });

  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail[0].msg);
  }

  return await response.json();
}
```

### React Example with Axios
```javascript
import axios from 'axios';

const uploadFile = async (file) => {
  const formData = new FormData();
  formData.append('file', file);

  try {
    const response = await axios.post(
      'http://localhost:8000/files/upload',
      formData,
      {
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'multipart/form-data'
        }
      }
    );
    
    return response.data.file_url;
  } catch (error) {
    console.error('Upload failed:', error.response.data);
    throw error;
  }
};
```

---

## WebSocket / Real-Time Updates

**Note:** The current API does not implement WebSocket connections. For real-time notifications:

1. **Polling Approach:** Check unread count periodically
```javascript
setInterval(async () => {
  const response = await fetch('/notifications/unread/count', {
    headers: { 'Authorization': `Bearer ${token}` }
  });
  const data = await response.json();
  updateBadge(data.unread_count);
}, 30000); // Every 30 seconds
```

2. **Future Enhancement:** WebSocket support can be added for real-time push notifications

---

## Security Considerations

### Token Storage
- **Never** store tokens in cookies without HttpOnly flag
- **Recommended:** Use localStorage or sessionStorage
- **Best Practice:** Clear token on logout

### Password Requirements
- Minimum length: 8 characters (recommended)
- Include uppercase, lowercase, numbers, and special characters

### CORS Configuration
- Backend accepts requests from all origins (`allow_origins=["*"]`)
- **Production:** Restrict to specific frontend domain

### File Upload Security
- File type validation enforced on backend
- File size limits enforced
- Files stored with unique UUID filenames

---

## Testing Endpoints with cURL

### Login Example
```bash
curl -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@example.com","password":"admin123"}'
```

### Authenticated Request Example
```bash
curl -X GET http://localhost:8000/members/me \
  -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
```

### File Upload Example
```bash
curl -X POST http://localhost:8000/challans/10/upload-proof \
  -H "Authorization: Bearer <token>" \
  -F "file=@/path/to/payment_proof.jpg"
```

---

## Postman Collection

Import the following environment variables into Postman:

```json
{
  "base_url": "http://localhost:8000",
  "access_token": "",
  "user_id": "",
  "member_id": "",
  "challan_id": "",
  "campaign_id": ""
}
```

Set `access_token` after login, then use `{{access_token}}` in Authorization headers.

---

## API Rate Limiting

**Current Status:** No rate limiting implemented

**Recommendation:** Implement frontend throttling for:
- Search/filter operations
- Notification polling
- File uploads

---

## Frontend-Backend Contract Alignment (2026-03-03)

### 1. Member Write Contract Confirmation

**Status:** ✅ Confirmed and documented

**Canonical writable fields for `PUT /members/{id}`:**
- `monthly_amount` (float)
- `address` (string)
- `status` (string: "active", "inactive", "suspended")

**Not currently writable** (requires explicit backend contract extension):
- `full_name` - Read-only, derived from User.username
- `phone` - Managed via User record, not Member record
- `email` - Managed via User record, not Member record
- `member_code` - Read-only, generated on member creation
- `city` - Not in current schema
- `notes` - Not in current schema

**Frontend Action:** If admin member edit needs additional fields, backend endpoint must be extended. Current implementation fully satisfies documented contract.

---

### 2. Notification Audience Model for List Responses

**Status:** ✅ Confirmed

**List Response Structure - `GET /notifications/`**
```json
[
  {
    "id": 25,
    "user_id": 5,
    "title": "Payment Approved",
    "message": "Your payment has been approved.",
    "is_read": false,
    "created_at": "2026-03-04T09:00:00",
    "read_at": null
  }
]
```

**Audience Metadata Notes:**
- `user_id` always populated (notification is per-user in storage)
- Creation respects `target_role` broadcast model (admin sends once, stored per user)
- List responses show user-scoped notifications only (each user sees their own copy)
- Audience metadata (`target_role` field) is **not persisted** per notification; admin broadcast creates multiple notification records (one per eligible user)

**Frontend Guidance:**
- Treat list responses as user-scoped by design
- Don't expect audience metadata in list; use for filtering/display at creation time only

---

### 3. Audit Log Accepted Payload Keys

**Status:** ✅ Confirmed

**Canonical payload mapping - `POST /audit-logs/`**

| Frontend Key | Backend Key | Type | Notes |
|--------------|-------------|------|-------|
| `action_type` | `action` | string | e.g., "create", "update", "delete", "approve" |
| `target_entity_type` | `entity_type` | string | e.g., "Member", "Challan", "Campaign" |
| `target_id` / `target_entity_id` | `entity_id` | integer | Entity ID being acted upon |
| `user_id` | `user_id` | integer (optional) | Acting user; omit if system action |
| `new_values` | `new_values` | string (JSON) | JSON stringified new state |
| `old_values` | `old_values` | string (JSON) | JSON stringified previous state (optional) |
| `ip_address` | `ip_address` | string (optional) | Request IP for audit trail |

**Backend Behavior:**
- Extra/unknown keys are **ignored** (no validation error)
- Required keys: `action`, `entity_type`, `entity_id`
- JSON value fields must be pre-stringified by frontend

**Frontend Note:** Map frontend event keys to backend schema. Backend accepts and ignores unknown fields.

---

### 4. Challan Monthly Multi-Month Behavior

**Status:** ✅ Confirmed

**Backend Model - Single Month per Challan:**
```json
{
  "type": "monthly",
  "month": "2026-03",
  "amount": 500.0
}
```

**Canonical Behavior:**
- Each challan represents payment for **one month only**
- `month` field is YYYY-MM format (e.g., "2026-03", "2026-04")
- To submit multiple months, frontend must create separate challans per month
- Backend does **not** support multi-month aggregation in single challan request

**Frontend Implementation Options:**

**Option A: Create one challan per month**
```
POST /challans/ { type: "monthly", month: "2026-03", amount: 500.0 }
POST /challans/ { type: "monthly", month: "2026-04", amount: 500.0 }
```

**Option B: Aggregate into single challan with note in payment_method**
```
POST /challans/ { 
  type: "monthly", 
  month: "2026-03",
  amount: 1000.0,  // Sum of March + April
  payment_method: "Mar-Apr aggregate"
}
```

**Frontend Decision:** Choose Option A (per-month separation) for cleaner tracking, or Option B (aggregation) if user prefers single submission. Backend supports both; aggregation logic is frontend responsibility.

---

### 5. Member Detail Endpoint for Admin Edit Flows

**Status:** ✅ Confirmed

**Purpose:** `GET /members/{id}` provides complete record for admin edit form population

**Behavior Confirmation:**
- Returns all member fields (readable):
  - `id`, `user_id`, `full_name`, `member_code`, `monthly_amount`, `address`
  - `join_date`, `status`, `created_at`, `updated_at`
- 404 if member not found
- 403 if requester is not admin and member is not own record

**Frontend Validation Guarantee:**
- Fresh read before edit form opens prevents stale values
- Error surface flows are supported; clear error messages provided on read failure

**Error Handling Note:**
- Frontend surfaces 404/403/500 errors as admin toast feedback
- Prevents silent failure in admin edit UX

---

## Changelog & Version History

### Version 1.0.1 (March 3, 2026)
- Added frontend-backend contract alignment confirmations (2026-03-03)
- Clarified member write contract scope
- Documented notification audience model
- Specified audit log payload mapping
- Confirmed challan single-month behavior
- Added member detail endpoint behavior notes

### Version 1.0.0 (March 3, 2026)
- Initial API documentation
- All core endpoints documented
- Authentication flow defined
- Error response format standardized

---

## Support & Contact

For API questions or issues:
- Review this documentation thoroughly
- Check error responses for specific details
- Verify authentication token validity
- Ensure request body matches schema exactly

---

**End of API Reference**
