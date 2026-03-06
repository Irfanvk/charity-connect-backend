# Backend-Frontend Alignment Analysis

**Date:** February 24, 2026  
**Status:** Analysis Complete - Action Items Identified  
**Last Updated:** File size limits corrected to 3MB (Feb 24, 2026)

---

## Executive Summary

The planned **FastAPI backend** (Python) is **well-aligned** with the existing React frontend but requires **critical adjustments** to match the frontend's API contract expectations. The frontend uses a **generic entity-based API pattern** (`/entities/:entity`) while the backend implements **resource-specific routes** (`/members/`, `/challans/`, etc.).

### Overall Assessment: ⚠️ **MAJOR ALIGNMENT ISSUES**

---

## Critical Misalignments

### 🔴 1. API Route Structure Mismatch

**Frontend Expectation:**
```javascript
// Generic entity proxy pattern
charityClient.entities.Member.list()     → GET  /entities/Member
charityClient.entities.Member.get(id)     → GET  /entities/Member/:id
charityClient.entities.Challan.create()   → POST /entities/Challan
```

**Backend Implementation:**
```python
# Resource-specific routes
GET    /members/              # List members
GET    /members/{id}          # Get member
POST   /challans/             # Create challan
```

**Impact:** 🔴 **CRITICAL - Frontend will fail to communicate with backend**

**Solution Options:**

#### Option A: Modify Backend (Recommended)
Add a generic entity router that wraps resource-specific logic:

```python
# app/routes/entity_routes.py
from fastapi import APIRouter

entity_router = APIRouter(prefix="/entities")

@entity_router.get("/{entity_name}")
async def list_entities(entity_name: str):
    entity_map = {
        "Member": member_service.list_members,
        "Challan": challan_service.list_challans,
        "Campaign": campaign_service.list_campaigns,
        # ... map all entities
    }
    handler = entity_map.get(entity_name)
    if not handler:
        raise HTTPException(404, "Entity not found")
    return await handler()

@entity_router.get("/{entity_name}/{id}")
async def get_entity(entity_name: str, id: str):
    # Similar mapping logic
    pass

@entity_router.post("/{entity_name}")
async def create_entity(entity_name: str, data: dict):
    # Similar mapping logic
    pass
```

#### Option B: Modify Frontend (Not Recommended)
Replace generic entity client with resource-specific API calls throughout ~30+ components.

---

### 🔴 2. Authentication Endpoint Mismatch

**Frontend:**
```javascript
POST /auth/login
Body: { "email": "user@example.com", "password": "..." }

// Alternative: email-only login (current mock)
Body: { "email": "user@example.com" }
```

**Backend:**
```python
POST /auth/login
# Expects username OR email
Body: { "username": "...", "password": "..." }
```

**Issues:**
1. Frontend sends `email` field, backend expects `username`
2. Frontend mock supports email-only auth (no password), backend requires password

**Solution:**
```python
# app/routes/auth_routes.py
@router.post("/login")
async def login(credentials: dict):
    # Accept both email and username
    identifier = credentials.get("email") or credentials.get("username")
    password = credentials.get("password")
    
    # Support email-only for dev/testing (optional)
    if not password and os.getenv("DEBUG"):
        user = await auth_service.get_user_by_email(identifier)
    else:
        user = await auth_service.authenticate(identifier, password)
    
    return {"token": create_token(user), "user": user}
```

---

### 🟡 3. Registration Flow Difference

**Frontend:**
```javascript
// Registration without user creation
await charityClient.entities.Invite.list()  // Check invite
await charityClient.entities.Member.create({
  invite_code: "...",
  full_name: "...",
  email: "...",
  // No password or username
})
await charityClient.entities.Invite.update(inviteId, { status: "used" })
```

**Backend:**
```python
POST /auth/register
Body: {
  "invite_code": "...",
  "username": "...",
  "password": "...",
  "email": "...",
  "full_name": "..."
}
# Creates User + Member atomically
```

**Issues:**
1. Frontend doesn't collect username/password during registration
2. Frontend manages invite validation separately
3. Frontend creates Member directly, not through auth/register

**Solution:**

#### Backend Approach (Better):
Keep `/auth/register` endpoint but also support direct Member creation for backward compatibility:

```python
# app/routes/member_routes.py
@router.post("/")  # Also mapped to POST /entities/Member
async def create_member(data: MemberCreate, db: Session):
    # If invite_code provided, validate it
    if data.invite_code:
        invite = await invite_service.validate_invite(data.invite_code)
        if not invite:
            raise HTTPException(400, "Invalid invite code")
    
    # Create user account (optional - can be added later)
    # For now, create member profile only
    member = await member_service.create_member(data)
    
    # Mark invite as used
    if data.invite_code:
        await invite_service.mark_used(invite.id, member.id)
    
    return member
```

---

### 🟡 4. File Upload Pattern Mismatch

**Frontend:**
```javascript
// Expects integration-style upload
const { file_url } = await charityClient.integrations?.Core?.UploadFile?.({ file });

// Then updates challan with URL
await charityClient.entities.Challan.update(challanId, {
  proof_url: file_url,
  status: 'proof_uploaded'
})
```

**Backend:**
```python
POST /challans/{id}/upload-proof
# Expects multipart/form-data file upload
# Returns updated challan
```

**Issues:**
1. Frontend expects separate file upload endpoint returning URL
2. Frontend then updates challan separately
3. Backend combines upload + challan update in one endpoint

**Solution:**

Add a generic file upload endpoint:

```python
# app/routes/file_routes.py
from fastapi import APIRouter, UploadFile

router = APIRouter(prefix="/files")

@router.post("/upload")
async def upload_file(file: UploadFile):
    # Validate file
    if file.size > 3 * 1024 * 1024:  # 3MB (updated from 5MB)
        raise HTTPException(400, "File too large")
    
    allowed_types = ["image/jpeg", "image/png", "application/pdf"]
    if file.content_type not in allowed_types:
        raise HTTPException(400, "Invalid file type")
    
    # Save file
    filename = f"{uuid4()}_{file.filename}"
    filepath = f"app/uploads/proofs/{filename}"
    
    with open(filepath, "wb") as f:
        f.write(await file.read())
    
    # Return URL
    file_url = f"/uploads/proofs/{filename}"
    return {"file_url": file_url}
```

Then keep the challan-specific upload endpoint as well for direct integration.

---

### 🟡 5. Entity Name Case Sensitivity

**Frontend:**
```javascript
charityClient.entities.Member      // PascalCase
charityClient.entities.Challan
charityClient.entities.Campaign
charityClient.entities.RecurringDonation
charityClient.entities.AuditLog
```

**Backend:**
```python
GET /members/    # lowercase
GET /challans/
GET /campaigns/
```

**Solution:**
Backend entity router should handle case-insensitive mapping:

```python
def normalize_entity_name(name: str) -> str:
    """Convert PascalCase to lowercase"""
    return name.lower()

@entity_router.get("/{entity_name}")
async def list_entities(entity_name: str):
    normalized = normalize_entity_name(entity_name)
    # Map: member → member_service, challan → challan_service
```

---

## Moderate Alignment Issues

### 🟢 6. Response Format Differences

**Frontend Expectation:**
```javascript
// Direct array response
const members = await charityClient.entities.Member.list()
// Expected: [{ id: "1", name: "..." }, ...]

// Fallback support for wrapped responses
// { items: [...] } or { data: [...] }
```

**Backend:**
Most endpoints return direct objects/arrays, which is ✅ **GOOD**.

**Recommendation:** Keep simple array/object responses. Avoid unnecessary wrappers unless pagination needed.

---

### 🟢 7. Challan Status Flow Match

**Frontend Status:**
```javascript
const statusConfig = {
  generated: "Generated",
  proof_uploaded: "Proof Uploaded", 
  pending: "Pending Review",
  approved: "Approved",
  rejected: "Rejected"
}
```

**Backend Status Enum:**
```python
class ChallanStatus(str, Enum):
    GENERATED = "generated"
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
```

**Status:** ⚠️ **PARTIAL ALIGNMENT**

**Note:** Backend does NOT have a `proof_uploaded` status in the enum. However, the Challan model has a `proof_uploaded_at` timestamp field to track when proof was uploaded. Frontend's `proof_uploaded` status should map to backend's `PENDING` status after proof upload.

**Recommendation:** 
- Backend workflow: `GENERATED` → (upload proof) → `PENDING` → (admin review) → `APPROVED`/`REJECTED`
- Frontend should map `proof_uploaded` display status to backend `PENDING` state
- Use `proof_uploaded_at` field to determine if proof has been submitted

---

### 🟢 8. Notification Target Types

**Frontend:**
```javascript
// From Documentation.jsx
target_type: "all" | "member" | "admins"
```

**Backend:**
Not explicitly documented in BACKEND_IMPLEMENTATION.md

**Recommendation:**
```python
class NotificationTargetType(str, Enum):
    ALL = "all"
    MEMBER = "member"
    ADMINS = "admins"
```

---

## Missing Backend Features

### 🔴 9. Missing Entities

**Frontend Uses (but not in backend spec):**

1. **RecurringDonation**
   ```javascript
   charityClient.entities.RecurringDonation.list()
   ```
   
   **Action Required:** Add RecurringDonation model and endpoints

2. **Request** (for member requests/complaints)
   ```javascript
   charityClient.entities.Request.create({
     request_type: "approval|question|complaint|suggestion|other",
     subject: "...",
     description: "..."
   })
   ```
   
   **Action Required:** Add Request model and endpoints

3. **User** entity (separate from Member)
   ```javascript
   charityClient.entities.User.list()  // Settings page
   ```
   
   **Note:** Backend has User model but no documented endpoints for listing users

---

### 🟡 10. Missing Endpoints

**Frontend calls these, backend doesn't document:**

1. **GET /members/me** - Get current user's member profile
   ```javascript
   // Used in Profile.jsx, Dashboard.jsx
   const currentUser = await charityClient.auth.me()
   // Then finds member by email
   ```
   
   **Recommendation:** Add convenience endpoint:
   ```python
   @router.get("/members/me")
   async def get_my_profile(current_user: User = Depends(get_current_user)):
       return await member_service.get_by_user_id(current_user.id)
   ```

2. **GET /challans/member/{member_id}** - ✅ Already in backend spec

3. **PUT /notifications/{id}/read** - ✅ Already in backend spec

---

## Schema Alignment

### ✅ Well-Aligned Schemas

#### Member Schema
Frontend entity definition matches backend model:
- ✅ `member_id` (string, e.g., "MEM-001")
- ✅ `full_name`, `email`, `phone`
- ✅ `address`, `city`
- ✅ `join_date`, `status` (active/inactive/suspended)
- ✅ `monthly_amount`
- ✅ `profile_image`

#### Challan Schema
- ✅ `challan_number` (unique string)
- ✅ `member_id`, `member_name`
- ✅ `type` (monthly/donation)
- ✅ `amount`, `month`
- ✅ `months_covered`, `months_count` (for multi-month payments)
- ✅ `campaign_id`, `campaign_name`
- ✅ `status` (generated → pending → approved/rejected)
- ✅ `proof_url`, `proof_uploaded_at`
- ✅ `approved_by`, `rejected_by`, `rejection_reason`

#### Campaign Schema
- ✅ `title`, `description`
- ✅ `target_amount`, `collected_amount`
- ✅ `start_date`, `end_date`
- ✅ `status` (draft/active/completed/cancelled)
- ✅ `created_by`

---

## Environment & Configuration Alignment

### ✅ Environment Variables

**Frontend (.env.local):**
```bash
VITE_CHARITY_APP_ID=...
VITE_CHARITY_APP_BASE_URL=http://localhost:8000  # Point to FastAPI
```

**Backend (.env):**
```bash
DATABASE_URL=postgresql://...
SECRET_KEY=...
ACCESS_TOKEN_EXPIRE_MINUTES=60
DEBUG=False
```

**Recommendation:** 
- Frontend should point to `http://localhost:8000` (FastAPI default)
- Add CORS configuration in backend to allow `http://localhost:5173` (Vite dev server)

```python
# app/main.py
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:4173"],  # Vite dev + preview
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

---

## Token & Authentication Flow

### ⚠️ Partial Alignment

**Frontend Token Storage:**
```javascript
// Stored in localStorage as 'auth_token'
localStorage.setItem(AUTH_TOKEN_KEY, token)

// Sent as Bearer token
headers: { Authorization: `Bearer ${token}` }
```

**Backend JWT:**
```python
# Returns JWT token on login
{ "token": "eyJ...", "user": {...} }
```

**Status:** ✅ **Structure aligned**, but check:
1. Token expiration handling (frontend needs to handle 401 and redirect)
2. Token refresh mechanism (not implemented in either)

---

## Database Differences

### ⚠️ Consideration Needed

**Frontend Entity Files:**
- JSON schema files in `entities/` folder
- Likely used for validation or mock data generation
- Not actual database definitions

**Backend:**
- Full SQLAlchemy ORM models with relationships
- PostgreSQL database with migrations
- Proper foreign keys and cascade deletes

**Action:** Frontend entity JSON files should be kept as documentation/reference but are not authoritative. Backend models are the source of truth.

---

## Action Plan - Priority Order

### 🔴 Critical (Must Fix Before Integration)

1. **Add Generic Entity Router** (backend)
   - Create `/entities/:entity` endpoint structure
   - Map to existing service methods
   - Support GET, POST, PUT, DELETE for all entities

2. **Fix Auth Login Endpoint** (backend)
   - Accept both `email` and `username` fields
   - Support password-optional mode for dev

3. **Add File Upload Endpoint** (backend)
   - `POST /files/upload` returning `{ file_url }`
   - Separate from challan-specific upload

4. **Add Missing Entities** (backend)
   - RecurringDonation model + routes
   - Request model + routes

### 🟡 High Priority (Required for Full Features)

5. **Add Convenience Endpoints** (backend)
   - `GET /members/me`
   - `GET /users/` (for admin user management)

6. **Align Registration Flow** (frontend + backend)
   - Decide: Use `/auth/register` OR direct Member creation
   - Update frontend Register page accordingly

7. **Test File Upload Flow** (integration test)
   - Verify proof upload → URL return → challan update

### 🟢 Medium Priority (Nice to Have)

8. **Add Backend Documentation** (README updates)
   - Document generic entity API pattern
   - Add API examples matching frontend usage
   - Update setup instructions

9. **Add Response Wrappers** (backend - optional)
   - Consider pagination support for large lists
   - Add `{ data: [...], total: 100, page: 1 }` for paginated endpoints

10. **Add Integration Tests** (both)
    - End-to-end tests with real backend + frontend
    - Mock data seeding scripts

---

## Updated Backend Implementation Plan

Based on this analysis, the backend should be restructured as follows:

### Recommended Backend Structure (Updated)

```
app/
├── main.py                        # FastAPI app with CORS
├── routes/
│   ├── entity_routes.py          # 🆕 Generic /entities/:entity router
│   ├── auth_routes.py            # Updated: accept email field
│   ├── file_routes.py            # 🆕 POST /files/upload
│   ├── member_routes.py          # Keep for direct access
│   ├── challan_routes.py
│   ├── campaign_routes.py
│   ├── notification_routes.py
│   ├── recurring_routes.py       # 🆕 RecurringDonation
│   ├── request_routes.py         # 🆕 Request/Support
│   └── user_routes.py            # 🆕 User management
├── services/
│   ├── entity_service.py         # 🆕 Generic entity dispatcher
│   ├── file_service.py           # 🆕 File upload logic
│   ├── recurring_service.py      # 🆕
│   ├── request_service.py        # 🆕
│   └── [existing services...]
└── models/
    ├── recurring_donation.py     # 🆕
    ├── request.py                # 🆕
    └── [existing models...]
```

---

## Testing Checklist

Before going live, verify:

- [ ] `GET /entities/Member` returns array of members
- [ ] `POST /entities/Challan` creates challan
- [ ] `POST /auth/login` accepts `{ email, password }`
- [ ] `POST /files/upload` returns `{ file_url }`
- [ ] Frontend can upload proof and update challan
- [ ] Member registration flow works end-to-end
- [ ] Token expires and frontend redirects to login
- [ ] CORS allows requests from Vite dev server
- [ ] All entity types (Member, Challan, Campaign, etc.) work via generic API
- [ ] RecurringDonation and Request entities exist

---

## Conclusion

The planned FastAPI backend is **architecturally sound** but requires **significant route structure changes** to align with the frontend's generic entity API pattern. The main effort is implementing the entity router abstraction layer while keeping resource-specific routes for direct access.

**Estimated Implementation Time:**
- Generic entity router: 4-6 hours
- Missing entities (RecurringDonation, Request): 3-4 hours
- File upload endpoint: 1-2 hours
- Auth/registration alignment: 2-3 hours
- Testing & debugging: 4-6 hours

**Total:** ~15-20 hours of backend development to achieve full alignment.

---

**Next Steps:**
1. Review this document with backend developer
2. Implement generic entity router first (unblocks frontend)
3. Add missing entities
4. Test integration with frontend mock data
5. Deploy and verify with real database

---

## Recent Updates

### February 24, 2026
- ✅ **File size limit corrected:** All references updated from 5MB to 3MB across backend code and documentation
- ✅ **Challan status clarification:** Backend uses 4 statuses (GENERATED, PENDING, APPROVED, REJECTED). Frontend's `proof_uploaded` status should map to backend's `PENDING` status
- ✅ **Timestamp tracking:** Backend uses `proof_uploaded_at` field to track proof submission time

---

**Document Status:** ✅ Complete & Updated  
**Last Updated By:** Backend Development Team  
**Date:** February 24, 2026
