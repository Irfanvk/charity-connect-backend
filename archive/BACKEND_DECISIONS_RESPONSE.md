# Backend Decisions & Response to Frontend Team

**Date:** February 24, 2026  
**Status:** Decisions Made - Implementation Required

---

## Executive Summary

After reviewing the frontend implementation plan and current backend code, I'm providing clear decisions on all blocking issues. Both teams have action items to complete integration.

---

## 🔴 CRITICAL DECISIONS - BLOCKING ISSUES RESOLVED

### 1. ✅ API Route Structure - **FRONTEND TO CHANGE**

**Decision:** Keep backend resource-specific routes. Frontend should refactor.

**Rationale:**
- Generic entity router adds unnecessary abstraction layer
- Resource-specific routes are more explicit and maintainable
- Easier to add custom business logic per resource
- Standard REST API pattern

**Backend Action:** ✅ **NO CHANGES NEEDED** - Keep current structure

**Frontend Action:** 🔴 **REQUIRED - Refactor API Client**

Frontend needs to update `src/api/charityClient.js`:

```javascript
// REMOVE: Generic entity proxy
// charityClient.entities.Member.list()

// ADD: Resource-specific methods
charityClient = {
  members: {
    list: () => fetch('/members/'),
    get: (id) => fetch(`/members/${id}`),
    create: (data) => fetch('/members/', { method: 'POST', body: data }),
    update: (id, data) => fetch(`/members/${id}`, { method: 'PUT', body: data }),
    delete: (id) => fetch(`/members/${id}`, { method: 'DELETE' }),
  },
  challans: {
    list: () => fetch('/challans/'),
    get: (id) => fetch(`/challans/${id}`),
    create: (data) => fetch('/challans/', { method: 'POST', body: data }),
    uploadProof: (id, file) => fetch(`/challans/${id}/upload-proof`, ...),
    approve: (id) => fetch(`/challans/${id}/approve`, { method: 'POST' }),
    reject: (id, reason) => fetch(`/challans/${id}/reject`, { method: 'POST', body: { reason } }),
  },
  campaigns: { /* ... similar */ },
  notifications: { /* ... similar */ },
  invites: { /* ... similar */ },
  auth: {
    login: (credentials) => fetch('/auth/login', { method: 'POST', body: credentials }),
    register: (data) => fetch('/auth/register', { method: 'POST', body: data }),
    me: () => fetch('/auth/me'),
    logout: () => fetch('/auth/logout', { method: 'POST' }),
  }
}
```

**Estimated Frontend Effort:** 6-8 hours to refactor API client and update all components

---

### 2. ✅ Login Endpoint Field Name - **BACKEND TO CHANGE**

**Decision:** Backend will accept BOTH `username` and `email` fields

**Rationale:**
- More flexible authentication
- Email is more user-friendly
- Simple change to implement

**Backend Action:** 🟡 **IMPLEMENT THIS** (see code below)

**Frontend Action:** ✅ **NO CHANGES NEEDED** - Can send `email` field

**Backend Implementation Required:**

Update `app/schemas/schemas.py`:
```python
class UserLogin(BaseModel):
    username: Optional[str] = None
    email: Optional[str] = None
    password: str
    
    @validator('username', 'email')
    def check_identifier(cls, v, values):
        if not values.get('username') and not values.get('email'):
            raise ValueError('Either username or email is required')
        return v
```

Update `app/services/auth_service.py`:
```python
@staticmethod
def login(db: Session, user_login: UserLogin):
    """Authenticate user with username OR email."""
    # Try to find user by username or email
    if user_login.username:
        user = db.query(User).filter(User.username == user_login.username).first()
    elif user_login.email:
        user = db.query(User).filter(User.email == user_login.email).first()
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username or email required",
        )
    
    if not user or not verify_password(user_login.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )
    
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is inactive",
        )
    
    return user
```

**Estimated Backend Effort:** 1 hour

---

### 3. ✅ File Upload Flow - **BACKEND TO ADD ENDPOINT**

**Decision:** Backend will add separate `POST /files/upload` endpoint

**Rationale:**
- Better separation of concerns
- Reusable for other file upload needs
- Frontend can upload file first, then update entity
- Cleaner API design

**Backend Action:** 🟡 **IMPLEMENT THIS** (see code below)

**Frontend Action:** ✅ **NO CHANGES NEEDED** - Frontend flow is correct

**Backend Implementation Required:**

Create `app/routes/file_routes.py`:
```python
from fastapi import APIRouter, UploadFile, File, HTTPException
from app.utils.file_handler import validate_file, save_file
import uuid

router = APIRouter(prefix="/files", tags=["Files"])

@router.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    """
    Upload file and return public URL.
    
    Accepts: jpg, png, pdf
    Max size: 3MB
    """
    # Read file content
    content = await file.read()
    
    # Validate
    try:
        validate_file(content, file.filename, max_size_mb=3)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    # Save file
    filename = f"{uuid.uuid4()}_{file.filename}"
    file_path = save_file(content, filename)
    
    # Return URL
    file_url = f"/uploads/proofs/{filename}"
    return {"file_url": file_url, "filename": filename}
```

Update `app/main.py`:
```python
from app.routes import file_router  # Add import

app.include_router(file_router)  # Add to routers
```

**Note:** Keep existing `/challans/{id}/upload-proof` endpoint for backward compatibility and direct integration.

**Estimated Backend Effort:** 2 hours

---

### 4. ✅ Registration Flow - **FRONTEND TO CHANGE**

**Decision:** Frontend must collect username and password during registration

**Rationale:**
- Security best practice: users should set their own password
- Username needed for login
- Backend registration endpoint requires these fields
- Proper authentication flow

**Backend Action:** ✅ **NO CHANGES NEEDED** - Current implementation is correct

**Frontend Action:** 🔴 **REQUIRED - Update Registration Form**

Frontend needs to update `src/pages/Register.jsx`:

```javascript
// ADD to registration form:
<input 
  type="text" 
  name="username"
  placeholder="Choose a username"
  required
/>

<input 
  type="password" 
  name="password"
  placeholder="Create password"
  minLength="8"
  required
/>

<input 
  type="password" 
  name="confirmPassword"
  placeholder="Confirm password"
  required
/>

// Update form submission:
const handleSubmit = async (e) => {
  e.preventDefault();
  
  // Validate passwords match
  if (formData.password !== formData.confirmPassword) {
    alert("Passwords don't match");
    return;
  }
  
  // Call backend /auth/register
  const response = await charityClient.auth.register({
    invite_code: formData.inviteCode,
    username: formData.username,
    password: formData.password,
    email: formData.email,
    phone: formData.phone,
    address: formData.address,
    monthly_amount: formData.monthlyAmount || 0
  });
  
  // Registration creates both User and Member automatically
  // No need to create Member separately
};
```

**Backend automatically creates:**
1. User account with username/password
2. Member profile with auto-generated member code (MEM-001, MEM-002, etc.)
3. Marks invite as used

**Estimated Frontend Effort:** 2-3 hours

---

### 5. ✅ Login Page - **FRONTEND TO CREATE**

**Decision:** Frontend needs to create Login.jsx page

**Rationale:**
- Production apps need proper login flow
- Dev mode auto-authentication should be removed
- Users need ability to login after registration

**Backend Action:** ✅ **NO CHANGES NEEDED** (after #2 is implemented)

**Frontend Action:** 🔴 **REQUIRED - Create Login Page**

Create `src/pages/Login.jsx`:
```javascript
import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import charityClient from '../api/charityClient';

export default function Login() {
  const [credentials, setCredentials] = useState({
    email: '',
    password: ''
  });
  const navigate = useNavigate();
  
  const handleSubmit = async (e) => {
    e.preventDefault();
    
    try {
      const response = await charityClient.auth.login(credentials);
      
      // Store token
      localStorage.setItem('auth_token', response.access_token);
      
      // Store user info
      localStorage.setItem('user', JSON.stringify(response.user));
      
      // Redirect to dashboard
      navigate('/dashboard');
    } catch (error) {
      alert('Login failed: ' + error.message);
    }
  };
  
  return (
    <div className="login-container">
      <h2>Login to Charity Connect</h2>
      <form onSubmit={handleSubmit}>
        <input
          type="email"
          placeholder="Email"
          value={credentials.email}
          onChange={(e) => setCredentials({...credentials, email: e.target.value})}
          required
        />
        <input
          type="password"
          placeholder="Password"
          value={credentials.password}
          onChange={(e) => setCredentials({...credentials, password: e.target.value})}
          required
        />
        <button type="submit">Login</button>
      </form>
      <p>
        Don't have an account? 
        <a href="/register">Register with invite code</a>
      </p>
    </div>
  );
}
```

Add route in `src/App.jsx`:
```javascript
import Login from './pages/Login';

<Route path="/login" element={<Login />} />
```

**Estimated Frontend Effort:** 3-4 hours (including styling)

---

## 🟡 HIGH PRIORITY DECISIONS

### 6. ⚠️ Missing Entities (RecurringDonation, Request) - **BOTH TEAMS**

**Decision:** Phase 1 - Disable in frontend, Phase 2 - Backend implements

**Rationale:**
- Not critical for MVP
- Can be added in Phase 2
- Frontend should focus on core features first

**Frontend Action - Phase 1:** 🟡 **DISABLE FEATURES TEMPORARILY**

Comment out or hide:
- `src/pages/Requests.jsx` - Don't include in routes
- `src/components/campaigns/RecurringDonationForm.jsx` - Hide form option
- Navigation links to these features

**Backend Action - Phase 2:** 🟡 **IMPLEMENT WHEN NEEDED**

Will create models, services, and routes for:
1. RecurringDonation (monthly auto-donations)
2. Request (member support requests)

**Timeline:**
- Phase 1 (MVP): Disable in frontend - **Immediate**
- Phase 2: Backend implementation - **2 weeks after MVP launch**

---

## ✅ CONFIRMED OK - NO CHANGES NEEDED

### 7. ✅ Challan Status Mapping
**Status:** Frontend team already implemented correctly ✅

### 8. ✅ File Size Validation (3MB)
**Status:** Frontend team already implemented correctly ✅

### 9. ✅ Environment Configuration
**Status:** Frontend team already created .env.local.example ✅

### 10. ✅ Token Expiration Handling
**Status:** Frontend already has 401 → logout → redirect logic ✅

### 11. ✅ CORS Configuration
**Status:** Backend already has CORS enabled for all origins in `app/main.py` ✅

---

## Implementation Priority & Timeline

### 🔴 Phase 1: Critical Integration (Both Teams)

**Backend Tasks:**
1. ✅ Accept email field in login (1 hour)
2. ✅ Add `/files/upload` endpoint (2 hours)
3. ✅ Test all endpoints with Postman (1 hour)

**Frontend Tasks:**
1. 🔴 Refactor API client to resource-specific routes (6-8 hours)
2. 🔴 Create Login.jsx page (3-4 hours)
3. 🔴 Update Register.jsx with username/password fields (2-3 hours)
4. 🔴 Update all components using API client (2-3 hours)
5. 🔴 Disable RecurringDonation and Request features (1 hour)

**Total Estimated Time:**
- Backend: ~4 hours
- Frontend: ~15-20 hours

**Target Completion:** 3-4 days

---

### 🟡 Phase 2: Full Features (After MVP)

**Backend Tasks:**
1. Implement RecurringDonation model + routes + service
2. Implement Request model + routes + service
3. Add pagination to list endpoints
4. Add filtering and search

**Frontend Tasks:**
1. Re-enable RecurringDonation features
2. Re-enable Request features
3. Add pagination UI
4. Add filtering UI

**Timeline:** 2 weeks after MVP launch

---

## Testing Strategy

### Integration Testing Checklist

After Phase 1 implementation, test in this order:

1. **Authentication Flow**
   - [ ] Login with email + password
   - [ ] Login with username + password
   - [ ] Register with invite code (creates User + Member)
   - [ ] Token expiration handling

2. **Member Features**
   - [ ] List all members (admin)
   - [ ] Get my profile
   - [ ] Update profile
   - [ ] View member by ID

3. **Challan Features**
   - [ ] Create monthly challan
   - [ ] Create campaign challan
   - [ ] Upload file separately (`/files/upload`)
   - [ ] Update challan with proof URL
   - [ ] Admin approve/reject
   - [ ] Status transitions

4. **Campaign Features**
   - [ ] Create campaign
   - [ ] List active campaigns
   - [ ] Update campaign
   - [ ] Deactivate campaign

5. **Notification Features**
   - [ ] Send notification to user
   - [ ] Send notification to role (all admins)
   - [ ] Mark as read
   - [ ] List unread notifications

---

## API Endpoint Reference for Frontend

After Phase 1 implementation, complete API structure:

### Authentication
- `POST /auth/login` - Body: `{ email, password }` OR `{ username, password }`
- `POST /auth/register` - Body: `{ invite_code, username, password, email, phone, address, monthly_amount }`
- `GET /auth/me` - Returns current user
- `POST /auth/logout`

### Members
- `GET /members/` - List all (admin only)
- `GET /members/me` - Get my profile
- `GET /members/{id}` - Get member by ID
- `GET /members/code/{code}` - Get member by code (e.g., MEM-001)
- `PUT /members/{id}` - Update member

### Challans
- `GET /challans/` - List all (admin only)
- `GET /challans/member/{member_id}` - Get member's challans
- `GET /challans/{id}` - Get challan by ID
- `POST /challans/` - Create challan
- `POST /challans/{id}/upload-proof` - Upload proof (direct)
- `POST /challans/{id}/approve` - Approve challan (admin)
- `POST /challans/{id}/reject` - Reject challan (admin)

### Campaigns
- `GET /campaigns/` - List all
- `GET /campaigns/{id}` - Get campaign
- `POST /campaigns/` - Create campaign (admin)
- `PUT /campaigns/{id}` - Update campaign (admin)
- `DELETE /campaigns/{id}` - Delete campaign (admin)

### Invites
- `GET /invites/` - List invites (admin)
- `GET /invites/pending` - List pending invites (admin)
- `POST /invites/` - Create invite (admin)
- `POST /invites/validate` - Validate invite code
- `DELETE /invites/{id}` - Delete invite (admin)

### Notifications
- `GET /notifications/` - List my notifications
- `GET /notifications/{id}` - Get notification
- `POST /notifications/send` - Send notification (admin)
- `PUT /notifications/{id}/read` - Mark as read
- `POST /notifications/mark-all-read` - Mark all as read

### Files (NEW)
- `POST /files/upload` - Upload file, returns `{ file_url, filename }`

---

## Communication Protocol

### Backend Team Responsibilities:
1. Implement decisions #2 (login email field) and #3 (file upload)
2. Test all endpoints with Postman/Thunder Client
3. Update API documentation with examples
4. Notify frontend team when endpoints are ready
5. Provide Postman collection for testing

### Frontend Team Responsibilities:
1. Implement decisions #1 (API client refactor), #4 (registration), #5 (login page)
2. Disable RecurringDonation and Request features temporarily
3. Update components to use new API client structure
4. Test with backend staging environment
5. Report any integration issues

### Daily Standup Items:
- Backend: "Login email field done, file upload 50% complete"
- Frontend: "API client refactored for members and challans, working on campaigns"

### Integration Testing Session:
- Schedule 2-hour session after Phase 1 completion
- Both teams test together
- Document any issues in shared spreadsheet
- Fix issues immediately

---

## Risk Mitigation

### Potential Issues & Solutions:

1. **CORS errors**
   - Solution: Backend CORS already configured for all origins
   - If specific origin needed, update `app/main.py`

2. **Token format mismatch**
   - Solution: Backend returns `access_token`, frontend stores as `auth_token`
   - Frontend should store: `localStorage.setItem('auth_token', response.access_token)`

3. **File upload size exceeded**
   - Solution: Both validated at 3MB
   - Frontend should validate before upload to avoid unnecessary requests

4. **Status transition errors**
   - Solution: Backend enforces valid transitions
   - Frontend should disable invalid actions in UI

5. **API client refactor breaks existing features**
   - Solution: Implement feature-by-feature, test thoroughly
   - Keep old API client temporarily for comparison

---

## Success Criteria

Phase 1 is complete when:

✅ All critical decisions implemented
✅ Frontend can login with email/password
✅ Frontend can register new users
✅ Frontend can upload files separately
✅ Frontend can create and manage challans
✅ Frontend can view campaigns
✅ All API endpoints working with new frontend client
✅ No console errors in browser
✅ No CORS errors
✅ Token authentication working
✅ Integration tests passing

---

## Next Steps - Immediate Actions

### Backend Developer:
1. Read this document thoroughly
2. Start with login email field change (1 hour)
3. Then implement file upload endpoint (2 hours)
4. Test with Postman
5. Commit and push changes
6. Notify frontend team

### Frontend Developer:
1. Read this document thoroughly
2. Start with API client refactor (create new structure)
3. Test each resource (members, challans, etc.) one by one
4. Create Login.jsx page
5. Update Register.jsx
6. Disable RecurringDonation/Request features
7. Test with backend once endpoints ready

### Project Manager:
1. Schedule integration testing session (2 hours) 
2. Create shared issue tracker for integration bugs
3. Monitor progress daily
4. Plan Phase 2 timeline

---

**Document Status:** ✅ Decisions Finalized  
**Backend Implementation Required:** ~4 hours  
**Frontend Implementation Required:** ~15-20 hours  
**Last Updated:** February 24, 2026  
**Next Review:** After Phase 1 completion
