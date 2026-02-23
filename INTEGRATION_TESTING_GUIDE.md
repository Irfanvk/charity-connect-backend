# Integration Testing Guide

**Version:** 1.0  
**Date:** 2026-02-24  
**Scope:** Phase 1 integration  
**Owner:** QA Lead

---

## 1. Prerequisites
- Backend running on: http://localhost:8000
- Frontend running on: http://localhost:5173
- Database seeded with: at least 1 admin user and 1 valid invite code
- Required accounts: admin account, member account for login testing

---

## 2. Test Environment
- OS: Windows
- Browser: Chrome or Edge
- API Base URL: http://localhost:8000
- Frontend URL: http://localhost:5173

---

## Frontend Status Report (2026-02-24)

**Completed:**
- API client refactored (resource-specific routes)
- Login accepts email or username
- Registration with username + password
- ProofUpload integrated with /files/upload endpoint
- Build system working (dist/ directory produced)

**Ready for Backend Coordination:**
- Waiting on backend confirmations below

---

## Backend Confirmation Checklist

**Port Configuration:**
- Backend running on http://localhost:8000
- CORS enabled for http://localhost:5173

**Critical Endpoints:**
- POST /auth/login - Accept email or username + password
- POST /auth/register - Username + password with invite code
- POST /files/upload - File upload (3MB max, JPG/PNG/PDF)
- GET/POST /members - CRUD operations
- GET/POST /challans - CRUD operations
- GET/POST /campaigns - CRUD operations
- GET /notifications - Notification polling

**Authentication:**
- Token format confirmed (JWT bearer)
- Token expiration behavior documented
- Token location in response confirmed (access_token)

**Blockers to Flag:**
- Standardized error response format across endpoints
- Validation error format (field-level vs message-only)
- File upload response format for /files/upload

**Testing Requirements:**
- Mock/test data seeded in database
- Test user credentials shared for login testing
- Sample files available for upload testing (optional)

---

## 3. Test Cases (Priority Order)

### T1 - Login (Email)
**Steps:**
1. Open http://localhost:5173/login.
2. Enter valid email and password for a test user.
3. Submit the form.
**Expected:**
- Auth succeeds and token is stored in localStorage.
- User is redirected to the dashboard.
**Actual:**
-
**Status:** Pending

### T2 - Registration
**Steps:**
1. Open http://localhost:5173/register.
2. Enter a valid invite code and required fields, including username and password.
3. Submit the form.
**Expected:**
- User and member are created; invite is marked used.
- Auto-login and redirect to dashboard.
**Actual:**
-
**Status:** Pending

### T3 - File Upload
**Steps:**
1. Create a challan and open the proof upload dialog.
2. Upload a JPG/PNG/PDF under 3MB using the ProofUpload component.
**Expected:**
- File uploads to /files/upload and returns file_url.
- Challan proof is updated and status transitions to pending.
**Actual:**
-
**Status:** Pending

---

## 4. Defect Logging
Use CHANGE_REPORT.md with severity labels: High/Med/Low.

---

## 5. Sign-off
- Backend: Name, Date
- Frontend: Name, Date
- QA: Name, Date
