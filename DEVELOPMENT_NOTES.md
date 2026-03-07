# CharityConnect Development Notes

**Project:** CharityConnect Backend  
**Framework:** FastAPI (Python 3.11+)  
**Database:** PostgreSQL  
**Last Updated:** March 7, 2026

---

## Table of Contents
1. [Quick Start](#quick-start)
2. [Architecture Overview](#architecture-overview)
3. [Change History](#change-history)
4. [PWA Compatibility](#pwa-compatibility)
5. [Production Deployment](#production-deployment)

---

## Quick Start

### 5-Minute Setup

```bash
# 1. Navigate to project
cd d:\Projects\IrfAn\CharityConnect-main\charity-connect-backend

# 2. Create virtual environment
python -m venv venv
venv\Scripts\activate  # Windows
# source venv/bin/activate  # macOS/Linux

# 3. Install dependencies
pip install -r requirements.txt

# 4. Setup database
createdb charity_connect
# Or using psql:
# psql -U postgres -c "CREATE DATABASE charity_connect;"

# 5. Configure environment
cp .env.example .env  # Create from template
# Edit .env with your database credentials

# 6. Run server
uvicorn app.main:app --reload

# 7. Access API
# http://127.0.0.1:8000 - API
# http://127.0.0.1:8000/docs - Swagger UI
# http://127.0.0.1:8000/redoc - ReDoc
```

### Environment Configuration

Create `.env` in project root:

```env
# Database
DATABASE_URL=postgresql://postgres:YOUR_PASSWORD@localhost:5432/charity_connect

# Security
SECRET_KEY=super-secret-key-change-this-in-production-use-64-chars
ACCESS_TOKEN_EXPIRE_MINUTES=60

# Application
DEBUG=False
ALLOWED_HOSTS=["localhost", "127.0.0.1"]

# CORS (Development)
CORS_ORIGINS=["http://localhost:5173", "http://localhost:3000"]
```

### Testing the Installation

```bash
# Health check
curl http://127.0.0.1:8000/health

# Expected response:
# {"status": "healthy", "database": "connected"}
```

---

## Architecture Overview

### Project Structure

```
app/
├── config.py                  # Environment configuration
├── database.py                # SQLAlchemy setup & session
├── main.py                    # FastAPI app entry point
│
├── models/
│   ├── __init__.py
│   └── models.py              # SQLAlchemy ORM models (7 models)
│
├── schemas/
│   ├── __init__.py
│   └── schemas.py             # Pydantic validation schemas (40+ schemas)
│
├── routes/                    # API endpoints (11 modules)
│   ├── __init__.py
│   ├── auth_routes.py         # Authentication: login, register, me, logout
│   ├── invite_routes.py       # Invite CRUD & validation
│   ├── member_routes.py       # Member management
│   ├── challan_routes.py      # Challan/payment operations
│   ├── bulk_challan_routes.py # Bulk operations
│   ├── campaign_routes.py     # Campaign management
│   ├── notification_routes.py # Notification system
│   ├── user_routes.py         # User admin operations
│   ├── audit_log_routes.py    # Audit logging
│   ├── file_routes.py         # File upload
│   └── admin_routes.py        # Admin utilities
│
├── services/                  # Business logic (6 modules)
│   ├── __init__.py
│   ├── auth_service.py        # Authentication logic
│   ├── invite_service.py      # Invite management
│   ├── member_service.py      # Member operations
│   ├── challan_service.py     # Challan workflow
│   ├── campaign_service.py    # Campaign operations
│   └── notification_service.py# Notification delivery
│
├── utils/                     # Utilities
│   ├── __init__.py
│   ├── auth.py                # JWT & password hashing
│   └── file_handler.py        # File validation & storage
│
└── uploads/
    └── proofs/                # Payment proof storage
```

### Database Models

#### 1. User (Authentication)
**Purpose:** Account authentication and role management

**Fields:**
- `id` (PK), `username` (unique), `email` (unique), `phone`, `password_hash`
- `role` (enum: superadmin, admin, member)
- `is_active` (boolean)
- `created_at`, `updated_at`

**Relationships:**
- One-to-One with Member
- One-to-Many with Notifications

#### 2. Member (Donor Profiles)
**Purpose:** Donation member profiles

**Fields:**
- `id` (PK), `user_id` (FK→User, unique)
- `member_code` (unique, format: MEM0001, MEM0002...)
- `full_name`, `email`, `phone`, `address`, `city`, `notes`
- `monthly_amount` (decimal)
- `status` (enum: active, inactive, suspended)
- `join_date`, `created_at`, `updated_at`

**Relationships:**
- Belongs-to User
- One-to-Many with Challans

**Member Code Generation:**
```python
last_member = db.query(Member).order_by(Member.id.desc()).first()
last_code_num = int(last_member.member_code[3:]) if last_member else 0
new_code = f"MEM{str(last_code_num + 1).zfill(4)}"
```

#### 3. Invite (Registration System)
**Purpose:** Controlled registration via invite codes

**Fields:**
- `id` (PK), `invite_code` (unique, format: INV-XXXXXX)
- `email`, `phone`
- `expiry_date` (datetime)
- `is_used` (boolean), `used_by_user_id` (FK→User)
- `created_by_admin_id` (FK→User)
- `created_at`, `used_at`

**Validation:**
- Must be unused
- Must not be expired
- Single-use only

#### 4. Campaign (Occasional Donations)
**Purpose:** Special donation campaigns (e.g., Ramadan, emergencies)

**Fields:**
- `id` (PK), `title`, `description`, `image_url`
- `target_amount` (decimal), `collected_amount` (decimal)
- `start_date`, `end_date`
- `is_active` (boolean)
- `created_by_admin_id` (FK→User)
- `created_at`, `updated_at`

#### 5. Challan (Payment Records)
**Purpose:** Monthly membership or campaign donation records

**Fields:**
- `id` (PK), `member_id` (FK→Member)
- `type` (enum: monthly, campaign)
- `campaign_id` (FK→Campaign, optional)
- `month` (string, format: YYYY-MM, for monthly type)
- `amount` (decimal)
- `status` (enum: generated, pending, approved, rejected)
- `payment_method` (enum: cash, online, bank_transfer)
- `proof_file_url` (string)
- `bulk_group_id` (string, for bulk operations)
- `approved_by_admin_id` (FK→User), `approved_at`
- `rejection_reason` (text)
- `notes`, `created_at`, `updated_at`

**Status Flow:**
```
generated → pending (proof uploaded) → approved/rejected
```

#### 6. Notification (In-App Messaging)
**Purpose:** User notifications for approvals, rejections, campaigns

**Fields:**
- `id` (PK), `user_id` (FK→User)
- `title`, `message`, `icon`
- `is_read` (boolean), `read_at`
- `entity_type`, `entity_id`
- `created_at`, `updated_at`

**Scope:** User-scoped (each user sees only their notifications)

#### 7. AuditLog (Change Tracking)
**Purpose:** Security and compliance audit trail

**Fields:**
- `id` (PK), `user_id` (FK→User)
- `action` (enum: CREATE, UPDATE, DELETE, LOGIN, etc.)
- `entity_type` (string: User, Member, Challan, etc.)
- `entity_id` (integer)
- `old_values` (JSON), `new_values` (JSON)
- `ip_address`
- `created_at`

---

### Authentication Flow

#### Registration
```
1. Admin creates invite code → POST /invites/
2. Invite sent to user (email/phone)
3. User validates code → POST /invites/validate
4. User registers → POST /auth/register
   - Creates User record
   - Creates Member record
   - Marks invite as used
   - Returns JWT token
5. User authenticated automatically
```

#### Login
```
1. User submits credentials → POST /auth/login
2. Backend validates username/email + password
3. Backend generates JWT token with payload:
   {
     "sub": user_id (as string),
     "role": user.role,
     "exp": expiry_timestamp
   }
4. Backend returns token + user object
5. Frontend stores token in localStorage
6. Frontend includes in all requests:
   Authorization: Bearer <token>
```

#### Access Control
```
Public routes:
- POST /auth/login
- POST /auth/register
- POST /invites/validate

User routes (any authenticated user):
- GET /auth/me
- GET /members/me
- POST /challans/
- GET /notifications/

Admin routes (admin/superadmin only):
- All /invites/* (except validate)
- All /users/*
- All /admin/*
- PATCH /challans/{id}/approve
- PATCH /challans/{id}/reject
- POST /campaigns/
- PUT /members/{id}
```

### Challan Workflow

```
Member Flow:
1. Member creates challan → POST /challans/
   Status: generated
2. Member uploads proof → POST /challans/{id}/upload-proof
   Status: pending
3. Admin reviews → GET /challans/?status=pending
4. Admin approves → PATCH /challans/{id}/approve
   Status: approved
   OR
   Admin rejects → PATCH /challans/{id}/reject
   Status: rejected
5. If rejected, member can re-upload proof → back to step 2

Admin On-Behalf Flow:
1. Admin creates challan for member → POST /challans/ with member_id
2. Admin uploads proof → POST /challans/{id}/upload-proof
3. Admin approves immediately (optional)
```

### File Upload System

**Endpoint:** `POST /files/upload`

**Constraints:**
- Max size: 3MB
- Allowed types: JPG, PNG, PDF
- MIME validation required
- Stored in: `app/uploads/proofs/`

**Process:**
```python
1. Validate file size (<= 3MB)
2. Validate file extension (.jpg, .png, .pdf)
3. Validate MIME type (image/jpeg, image/png, application/pdf)
4. Generate unique filename (UUID + extension)
5. Save to uploads/proofs/
6. Return file_url or file_id
```

---

## Change History

### March 8, 2026 - Critical Bug Fixes & Security Enhancement
**Fixed:**
- Admin bulk operations 500 error: Fixed auth context mismatch in dict-based JWT (added `_is_admin_role()` helper)
- Audit logs 422 validation error: Changed `user_id` parameter from Optional[int] to Optional[str] with normalization
- Audit logs frontend: Enhanced query builder to filter empty params; added field normalizer for backend→frontend mapping

**Changed:**
- Authentication: Login now accepts username OR email (auto-detection)
- Username validation: Added frontend real-time validation (3-30 chars, alphanumeric + underscore/hyphen)

**Security:**
- Enforced username uniqueness across all users (409 CONFLICT on duplicates)
- Database UNIQUE constraint on users.username verified
- Backend validation at lines 86-89 in auth_service.py

**Testing:**
- Comprehensive end-to-end test suite executed (20+ test scenarios)
- All tests passed: admin operations, audit logs, login variants, registration with duplicate detection
- Test users created: `newuser123` (ID 10), `anotheruser456` (ID 11)
- Duplicate rejection confirmed: 409 CONFLICT returned correctly

**Files Modified:**
- Backend: `app/routes/admin_router.py`, `app/routes/audit_log_routes.py`, `app/services/auth_service.py`
- Frontend: `src/pages/Login.jsx`, `src/pages/Register.jsx`, `src/pages/AuditLogs.jsx`, `src/api/charityClient.js`

**Documentation:**
- Updated API_CHANGELOG.md with all 2026-03-08 changes
- Updated COMMUNICATION_LOG.md with 6 new decision log entries
- Created comprehensive CHANGE_REPORT.md

### March 7, 2026 - E2E Alignment & Production Prep
**Added:**
- Member CRUD endpoints: `POST /members/`, `DELETE /members/{id}`
- User management: `GET /users/{id}`, `PUT /users/{id}`
- Challan update: `PATCH /challans/{id}`
- Sort parameters: `sort_by`, `sort_order` for challan list endpoints

**Fixed:**
- Bulk challan member validation (compared member.id not user.id)
- Exception chaining in challan routes
- Role-based access for GET /challans/ and GET /members/

**Documentation:**
- Consolidated 23 markdown files into 4 organized documents
- Created API_DOCUMENTATION.md
- Created TROUBLESHOOTING.md
- Created FRONTEND_INTEGRATION.md
- Created DEVELOPMENT_NOTES.md

### March 6, 2026 - Bulk Operations Implementation
**Added:**
- `POST /challans/bulk-create` - Multi-month challan creation
- `GET /admin/bulk-pending-review` - Bulk operation review
- `PATCH /admin/bulk-operations/{bulk_group_id}/approve`
- `PATCH /admin/bulk-operations/{bulk_group_id}/reject`
- `BulkChallanGroup` model for tracking bulk operations

**Documentation:**
- BULK_OPERATIONS_API.md with complete guide

### March 3, 2026 - Frontend Contract Finalization
**Documentation:**
- Locked 5 critical contracts:
  1. Member write fields
  2. Notification user-scoping
  3. Audit log payload keys
  4. Challan multi-month strategy
  5. Member detail endpoint reliability
- Updated FRONTEND_ALIGNMENT_COMPLETE.md
- Updated FRONTEND_ALIGNMENT_QUICK_REFERENCE.md

### March 2, 2026 - Invite & Notification Fixes
**Fixed:**
- Invite expiry timezone-aware/naive comparison crash
- Invite code format standardized to `INV-XXXXXX`

**Changed:**
- Invite validation normalizes datetime to UTC-naive
- Canonical invite field: `expiry_date` (backward-compatible: `expires_at`)

### March 1, 2026 - Authorization & Role Fixes
**Fixed:**
- Authorization checks use JWT `role` instead of non-existent `is_admin`
- Added missing `HTTPException` import in member routes
- Null-member guards in challan ownership checks

**Impact:**
- 401: Missing/invalid/expired token
- 403: Valid token but insufficient role/permission

### February 26, 2026 - Registration & Token Fixes
**Changed:**
- `POST /auth/register` returns token + user with HTTP 201
- Register schema accepts optional `full_name`
- Duplicate checks return HTTP 409 (Conflict)

**Fixed:**
- JWT `sub` claim stored as string, parsed as integer
- `/auth/me` token validation after login
- Bearer token handling returns 401 consistently

**Validated:**
- Smoke tests passed for all auth endpoints

### February 24, 2026 - Initial Integration Prep
**Added:**
- `POST /files/upload` endpoint (3MB, jpg/png/pdf)
- Login accepts email or username

**Documentation:**
- COMMUNICATION_LOG.md created
- INTEGRATION_TESTING_GUIDE.md created
- CHANGE_REPORT.md created

---

## PWA Compatibility

### Overview
Frontend CharityConnect app is PWA-enabled. Backend is **already compatible** with basic PWA requirements.

### Current Status

#### ✅ CORS Headers (Already Configured)
```python
# app/main.py
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Development
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

**Production Update:**
```python
allow_origins=[
    "https://charity-connect.example.com",
    "https://www.charity-connect.example.com",
]
```

#### Optional: Response Caching
Frontend service worker caches responses for 24 hours automatically. To optimize, add `Cache-Control` headers:

**Cacheable Endpoints:**
```python
from fastapi import Response

@router.get("/members/{member_id}")
async def get_member(member_id: int, response: Response):
    response.headers["Cache-Control"] = "public, max-age=3600"  # 1 hour
    return member_data

@router.get("/campaigns/")
async def get_campaigns(response: Response):
    response.headers["Cache-Control"] = "public, max-age=86400"  # 24 hours
    return campaigns
```

**Non-Cacheable Endpoints:**
```python
@router.post("/auth/login")
async def login(response: Response):
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    return token_data

@router.get("/challans/")
async def get_challans(response: Response):
    response.headers["Cache-Control"] = "private, max-age=300"  # 5 minutes
    return challans
```

#### Push Notifications (Future)
Not yet implemented. Requirements when ready:
- VAPID keys configuration
- Web Push library integration
- Push endpoint registration

---

## Production Deployment

### Pre-Deployment Checklist

#### 1. Environment Variables
```env
# Production .env
DATABASE_URL=postgresql://prod_user:secure_password@prod_host:5432/charity_connect_prod
SECRET_KEY=generate-new-64-char-random-string-for-production
ACCESS_TOKEN_EXPIRE_MINUTES=60
DEBUG=False
ALLOWED_HOSTS=["charity-connect.example.com", "www.charity-connect.example.com"]
CORS_ORIGINS=["https://charity-connect.example.com", "https://www.charity-connect.example.com"]
```

#### 2. Database
- [ ] PostgreSQL production instance configured
- [ ] Database migrations applied
- [ ] Database backups configured
- [ ] Connection pooling enabled
- [ ] Indexes created for performance

**Indexes:**
```sql
CREATE INDEX idx_challans_status ON challans(status);
CREATE INDEX idx_challans_member_id ON challans(member_id);
CREATE INDEX idx_members_user_id ON members(user_id);
CREATE INDEX idx_members_code ON members(member_code);
CREATE INDEX idx_invites_code ON invites(invite_code);
CREATE INDEX idx_notifications_user_read ON notifications(user_id, is_read);
```

#### 3. Security
- [ ] DEBUG=False in production
- [ ] SECRET_KEY is strong random string (64+ chars)
- [ ] HTTPS enabled
- [ ] CORS origins restricted to production domains
- [ ] Rate limiting configured (optional)
- [ ] SQL injection protection (built-in with SQLAlchemy)
- [ ] Password policy enforced (min length, complexity)

#### 4. Performance
- [ ] Database connection pooling:
```python
# app/database.py
engine = create_engine(
    DATABASE_URL,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
    pool_recycle=3600
)
```
- [ ] Query pagination on list endpoints
- [ ] File upload size limits enforced
- [ ] Static file serving optimized

#### 5. Monitoring
- [ ] Application logging configured
- [ ] Error tracking (Sentry, etc.)
- [ ] Performance monitoring
- [ ] Uptime monitoring
- [ ] Database query performance tracking

#### 6. Deployment Options

**Option A: Traditional Server (Ubuntu)**
```bash
# 1. Install dependencies
sudo apt update
sudo apt install python3.11 python3-pip postgresql nginx

# 2. Clone repository
git clone <repository>
cd charity-connect-backend

# 3. Setup virtual environment
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 4. Configure systemd service
sudo nano /etc/systemd/system/charity-connect.service

# 5. Start service
sudo systemctl start charity-connect
sudo systemctl enable charity-connect

# 6. Configure nginx reverse proxy
sudo nano /etc/nginx/sites-available/charity-connect

# 7. Enable site
sudo ln -s /etc/nginx/sites-available/charity-connect /etc/nginx/sites-enabled/
sudo systemctl restart nginx
```

**Option B: Docker**
```dockerfile
# Dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

```bash
# Build and run
docker build -t charity-connect-backend .
docker run -d -p 8000:8000 --env-file .env charity-connect-backend
```

**Option C: Platform as a Service**
- Heroku
- Railway
- Render
- DigitalOcean App Platform

---

## Development Best Practices

### Code Style
- Follow PEP 8
- Use type hints
- Write docstrings for public functions
- Keep functions small and focused

### Database
- Always use SQLAlchemy ORM (no raw SQL)
- Use transactions for multi-step operations
- Add indexes for frequently queried fields
- Use database migrations (Alembic)

### Security
- Never commit .env files
- Hash passwords with bcrypt (12 rounds minimum)
- Validate all user inputs with Pydantic
- Use parameterized queries (built-in with ORM)
- Implement rate limiting for sensitive endpoints

### Testing
- Write unit tests for services
- Write integration tests for routes
- Test authentication flows
- Test role-based access control
- Test file upload validation

### Documentation
- Keep API documentation up to date
- Document breaking changes in CHANGELOG
- Document decisions in COMMUNICATION_LOG
- Update TROUBLESHOOTING with common issues

---

## Useful Commands

### Database
```bash
# Create database
createdb charity_connect

# Drop database (DANGER!)
dropdb charity_connect

# Backup database
pg_dump charity_connect > backup.sql

# Restore database
psql charity_connect < backup.sql

# Connect to database
psql -U charity_user -d charity_connect
```

### Development
```bash
# Run server
uvicorn app.main:app --reload

# Run on different port
uvicorn app.main:app --port 8001

# Run server with logs
uvicorn app.main:app --reload --log-level debug

# Install new package
pip install package_name
pip freeze > requirements.txt
```

### Testing
```bash
# Run tests (if configured)
pytest

# Run specific test file
pytest tests/test_auth.py

# Run with coverage
pytest --cov=app tests/
```

---

## Additional Resources

- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [SQLAlchemy Documentation](https://docs.sqlalchemy.org/)
- [Pydantic Documentation](https://docs.pydantic.dev/)
- [PostgreSQL Documentation](https://www.postgresql.org/docs/)

---

**For API usage:** See [API_DOCUMENTATION.md](API_DOCUMENTATION.md)  
**For frontend integration:** See [FRONTEND_INTEGRATION.md](FRONTEND_INTEGRATION.md)  
**For troubleshooting:** See [TROUBLESHOOTING.md](TROUBLESHOOTING.md)
