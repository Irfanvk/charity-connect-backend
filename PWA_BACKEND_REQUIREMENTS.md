# PWA Backend Requirements & Compatibility Checklist

**Document Date:** March 6, 2026  
**Backend Framework:** FastAPI (Python)  
**Frontend:** CharityConnect (React + Vite)

---

## Overview

The frontend CharityConnect app is now PWA-enabled (Progressive Web App), allowing users to:
- Install the app on mobile devices (iOS, Android) and desktop (Windows, Mac)
- Work offline with cached API responses and images
- Receive push notifications (future)

**Good News:** No backend code changes are required for basic PWA support.

---

## ✅ Current Backend Configuration Status

### 1. CORS Headers - **ALREADY CONFIGURED ✅**

**Current Setup (app/main.py):**
```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

**Why This Matters:**
- Service workers require CORS compliance to cache cross-origin requests
- Currently allows all origins (fine for dev, restrict in production)
- Allows all request methods and headers (authentication compatible)

**Production Update Needed:**
```python
allow_origins=[
    "https://charity-connect.example.com",
    "https://www.charity-connect.example.com",
]
```

---

### 2. API Response Caching - **OPTIONAL OPTIMIZATION**

The frontend service worker automatically caches API responses for 24 hours regardless of server headers.

**However, to optimize:**

Add `Cache-Control` headers to appropriate endpoints:

#### 2.1 Cacheable Endpoints (Safe to Cache)

These endpoints return same data for same parameters and change rarely:

```python
# app/routes/member_router.py or campaign_router.py
from fastapi import Response

@router.get("/members/{member_id}")
async def get_member(member_id: int, response: Response):
    # ...
    response.headers["Cache-Control"] = "public, max-age=3600"  # 1 hour
    return member_data

@router.get("/campaigns/")
async def get_campaigns(response: Response):
    # ...
    response.headers["Cache-Control"] = "public, max-age=86400"  # 24 hours
    return campaigns
```

**Good Candidates:**
- Profile data: `GET /members/{id}` (rarely changes)
- Campaign lists: `GET /campaigns/` (can be cached longer)
- Public notifications: `GET /notifications/` (safe to cache with expiry)

#### 2.2 Non-Cacheable Endpoints (Must NOT Cache)

These endpoints return user-session-specific or sensitive data:

```python
@router.post("/auth/login", response: Response)
async def login(credentials: UserLogin, response: Response):
    # ...
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, proxy-revalidate"
    return token_data

@router.get("/challans/")
async def get_challans(response: Response):
    # Status-sensitive, should revalidate
    response.headers["Cache-Control"] = "private, max-age=300"  # 5 minutes
    return challans
```

**Must NOT Cache:**
- Authentication endpoints: `/auth/login`, `/auth/register`
- Token refresh endpoints (if added)
- User-specific sensitive data
- Admin-only endpoints

#### 2.3 Header Recommendation (Middleware)

Add a middleware to set default cache headers:

```python
# app/middleware.py
from fastapi import Request
from fastapi.responses import Response
from datetime import datetime, timedelta

async def add_cache_headers(request: Request, call_next):
    response = await call_next(request)
    
    # Don't cache POST/PATCH/DELETE
    if request.method not in ["GET", "HEAD"]:
        response.headers["Cache-Control"] = "no-store"
        return response
    
    # Don't cache auth endpoints
    if "/auth/" in request.url.path:
        response.headers["Cache-Control"] = "no-store, no-cache"
        return response
    
    # Default: cache GET endpoints for 1 hour
    if "Cache-Control" not in response.headers:
        response.headers["Cache-Control"] = "public, max-age=3600"
    
    return response

# In app/main.py
app.add_middleware(CacheHeaderMiddleware)
```

---

### 3. Manifest.json Serving - **ONLY IF BACKEND SERVES FRONTEND**

**Current Setup:** Frontend is a separate React app (likely served separately or by a different web server).

**If backend needs to serve frontend files in production:**

```python
from fastapi.staticfiles import StaticFiles

app.mount(
    "/",
    StaticFiles(directory="dist", html=True),
    name="static"
)
```

**Ensure Headers:**
- `GET /manifest.json` → `Content-Type: application/json` (auto-handled)
- `GET /icons/icon-192.png` → `Content-Type: image/png` (auto-handled)

---

### 4. Service Worker Scope - **VERIFY PRODUCTION URL**

The frontend service worker scope is `/` (entire domain).

**Backend must be accessible at (from frontend perspective):**

**Development:**
```
VITE_CHARITY_APP_BASE_URL=http://localhost:8000
```

**Production:**
```
VITE_CHARITY_APP_BASE_URL=https://api.charity-connect.example.com
(or same domain if served together)
```

**Verify in production:**
```bash
# These should all be 200 OK
curl https://api.charity-connect.example.com/api/members/
curl https://api.charity-connect.example.com/manifest.json
curl https://api.charity-connect.example.com/icons/icon-192.png
```

---

### 5. Authentication & Token Expiration - **NO CHANGES NEEDED**

**Current Behavior:**
- Tokens expire after 60 minutes (no refresh token)
- On 401 response, frontend redirects to login
- Service worker caches responses but respects 401 auth failures

**How PWA Handles Auth:**

| Scenario | Behavior |
|----------|----------|
| **Online + Valid Token** | Fresh API request → Response cached |
| **Offline + Cached Response** | Serves stale cache (but data is safe) |
| **Online + Token Expired** | 401 response → Frontend redirects to login |
| **Offline + No Cache** | Empty state or error message |

**No backend changes needed** — Frontend already handles token expiration and re-login.

---

### 6. HTTPS & Security - **PRODUCTION REQUIREMENT**

**In production, PWA requires HTTPS:**

```
https://charity-connect.example.com/   ✅ PWA works
http://charity-connect.example.com/    ❌ Service worker blocked
localhost:8000                          ✅ Dev mode allowed
```

**Backend Should:**
- [ ] Enable HTTPS (TLS certificate)
- [ ] Redirect HTTP → HTTPS
- [ ] Set Strict-Transport-Security header

```python
@app.middleware("http")
async def https_redirect(request: Request, call_next):
    if "x-forwarded-proto" in request.headers:
        if request.headers["x-forwarded-proto"] != "https":
            return RedirectResponse(url=request.url.replace("http://", "https://"))
    return await call_next(request)
```

---

## ✅ Backend Compatibility Checklist

- [x] **CORS Configured** - Service workers can make cross-origin requests
- [x] **No Auth Conflicts** - Frontend handles token validation
- [ ] **Cache Headers Optimized** (optional, recommended for production)
- [ ] **HTTPS Enabled** (production requirement)
- [ ] **Static Files Served** (only if backend serves frontend)
- [ ] **Manifest Accessible** (only if backend serves frontend)
- [ ] **API Rate Limiting** (consider adding for PWA)
- [ ] **Error Responses Clear** (frontend needs error.detail in standardized format)

---

## 📝 Testing Backend PWA Compatibility

### 1. Test CORS from Frontend Service Worker

```bash
# From frontend dev environment
npm run dev

# In browser console:
fetch('/api/members/').then(r => r.json()).then(console.log)

# Should work without CORS errors
```

### 2. Test API Caching

```bash
# Online:
curl -X GET http://localhost:8000/api/campaigns/ \
  -H "Authorization: Bearer <token>"

# Go offline (disable network in DevTools)

# Offline:
# Should still load from service worker cache
```

### 3. Test Auth on Expired Token

```bash
# 1. Login and get token (expires in 60 minutes)
# 2. Wait for token expiration or manually delete token
# 3. Try API request
# 4. Should get 401 response
# 5. Frontend should redirect to /login
```

---

## 🚀 Deployment Checklist

### Pre-Production

- [ ] Enable HTTPS and valid certificate
- [ ] Update CORS allowed origins to production domain
- [ ] Add Cache-Control headers to appropriate endpoints
- [ ] Test CORS with production URLs
- [ ] Verify manifest.json is accessible (if serving frontend)
- [ ] Verify icon files are served correctly
- [ ] Test PWA installation on production domain
- [ ] Test offline functionality
- [ ] Monitor service worker errors in production

### Production

- [ ] Monitor API response times (caching may reduce load)
- [ ] Set up rate limiting if not present
- [ ] Monitor error rates (411 auth failures expected)
- [ ] Have a plan for PWA updates/version management
- [ ] Document PWA cache invalidation procedures for admins

---

## 📞 Communication with Frontend Team

### If Issues Arise

1. **CORS Error on Service Worker:**
   - Frontend will report "Failed to fetch" or "NetworkError"
   - Check `app.add_middleware(CORSMiddleware)` configuration
   - Verify `allow_origins` includes frontend domain

2. **401 Redirects Happening:**
   - This is expected when token expires
   - Frontend handles the redirect
   - No backend action needed unless error message needs adjustment

3. **Cached Stale Data:**
   - Cache is 24 hours by default
   - Frontend can force refresh by clearing service worker cache
   - Add `Cache-Control` headers if specific endpoints should cache less

4. **Offline Issues:**
   - Check if endpoints return 200 (required for caching)
   - Check if response `Content-Type` is correct
   - Verify frontend has visited endpoint online before going offline

---

## 📚 Additional Resources

- **Frontend PWA Docs:** [Backend-Guidance/FRONTEND_INTEGRATION_GUIDE.md](../CharityConnect/Backend-Guidance/FRONTEND_INTEGRATION_GUIDE.md#progressive-web-app-pwa-support-new---v20)
- **Frontend Changelog:** [CHANGELOG.md](../CharityConnect/CHANGELOG.md) (Version 2.0 - PWA Support)
- **Vite PWA Plugin Docs:** https://vite-pwa-org.netlify.app/
- **FastAPI CORS Docs:** https://fastapi.tiangolo.com/tutorial/cors/
- **Service Worker Guide:** https://developer.mozilla.org/en-US/docs/Web/API/Service_Worker_API

---

**PWA Support Status: ✅ Backend Compatible - No Code Changes Required**

Last Updated: March 6, 2026
