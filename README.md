# CharityConnect Backend

Backend API for **CharityConnect** — a membership and donation management system built with FastAPI, PostgreSQL, and SQLAlchemy.

---

## Tech Stack

| Component     | Details                         |
|---------------|---------------------------------|
| Framework     | FastAPI (Python 3.11+)          |
| Database      | PostgreSQL 15+                  |
| ORM           | SQLAlchemy 2.0                  |
| Auth          | JWT (python-jose) + bcrypt      |
| Validation    | Pydantic v2                     |
| Server        | Uvicorn (ASGI)                  |
| Task Queue    | Celery + Redis (optional)       |
| File Storage  | Local disk or Cloudflare R2     |

---

## Features

- **Invite-only registration** — admins generate invite codes; members register with them
- **Role-based access** — `superadmin`, `admin`, `member` with endpoint-level enforcement
- **Member management** — CRUD, search, CSV/XLSX import, profile updates
- **Monthly challans** — create, upload proof, admin approve/reject workflow
- **Bulk challans** — pay multiple months at once with single proof
- **Campaigns** — targeted or unlimited fundraising with progress tracking
- **Payment proofs** — file upload (JPG/PNG/PDF) to local storage or R2
- **Notifications** — in-app broadcast/role-based/individual, mark-read
- **Member requests** — monthly amount changes, profile updates, complaints — with admin approval
- **Audit logs** — track all entity changes with old/new values
- **Import/Export** — bulk member & challan history import from CSV/XLSX
- **Dashboard charts** — monthly collections, campaign progress, top donors

---

## Project Structure

```
charity-connect-backend/
├── app/
│   ├── main.py                    # FastAPI app, middleware, exception handlers, health checks
│   ├── config.py                  # Pydantic Settings (env vars, validation)
│   ├── database.py                # SQLAlchemy engine, session, runtime migrations
│   ├── models/
│   │   └── models.py              # All ORM models (User, Member, Challan, Campaign, etc.)
│   ├── schemas/
│   │   └── schemas.py             # Pydantic request/response schemas
│   ├── routes/
│   │   ├── auth_routes.py         # POST /auth/login, /register, GET /auth/me
│   │   ├── member_routes.py       # /members CRUD, import, summary
│   │   ├── challan_routes.py      # /challans CRUD, proof upload, approve/reject, import
│   │   ├── bulk_challan_routes.py # POST /challans/bulk-create
│   │   ├── campaign_routes.py     # /campaigns CRUD, import
│   │   ├── invite_routes.py       # /invites CRUD, validate
│   │   ├── notification_routes.py # /notifications CRUD, broadcast, WhatsApp
│   │   ├── request_routes.py      # /requests member requests + admin actions
│   │   ├── admin_router.py        # /admin dashboard charts, bulk review, system wipe
│   │   ├── user_routes.py         # /users admin user management
│   │   ├── file_routes.py         # POST /files/upload
│   │   └── audit_log_routes.py    # /audit-logs list + create
│   ├── services/                  # Business logic layer
│   │   ├── auth_service.py        # Login (with rate limiting), registration, invite claim
│   │   ├── member_service.py      # Member CRUD, import, deduplication
│   │   ├── challan_service.py     # Challan lifecycle, payable months, summary, import
│   │   ├── campaign_service.py    # Campaign CRUD, stats, import
│   │   ├── invite_service.py      # Invite create/validate/manage
│   │   ├── notification_service.py# Notification broadcast, feed, mark-read
│   │   ├── request_service.py     # Member requests lifecycle
│   │   ├── import_job_service.py  # Async import job tracking
│   │   └── whatsapp_service.py    # WhatsApp Cloud API integration
│   ├── utils/
│   │   ├── auth.py                # JWT create/verify, password hash, role guards
│   │   └── file_handler.py        # File save (local/R2), validation
│   ├── workers/
│   │   ├── celery_app.py          # Celery configuration
│   │   └── tasks.py               # Background tasks (WhatsApp, reminders)
│   └── uploads/proofs/            # Local file storage for payment proofs
├── migrations/
│   └── 20260318_member_requests.sql  # Schema migration for member_requests table
├── init_db.sql                    # Full PostgreSQL schema DDL (fresh installs)
├── seed_admin.py                  # CLI script to create admin users
├── requirements.txt               # Python dependencies
├── Dockerfile                     # Multi-stage Docker build
├── Procfile                       # Heroku process definitions
└── docker-compose.yml             # Full stack (in parent directory)
```

---

## Database Setup (PostgreSQL)

### Option 1: Local PostgreSQL Install

1. **Install PostgreSQL 15+**
   - Windows: Download from https://www.postgresql.org/download/windows/
   - macOS: `brew install postgresql@15`
   - Ubuntu: `sudo apt install postgresql postgresql-contrib`

2. **Start PostgreSQL service**
   ```bash
   # Windows (Services panel or):
   pg_ctl start -D "C:\Program Files\PostgreSQL\15\data"

   # macOS:
   brew services start postgresql@15

   # Linux:
   sudo systemctl start postgresql
   ```

3. **Create the database**
   ```bash
   # Connect to PostgreSQL
   psql -U postgres

   # In the psql shell:
   CREATE DATABASE charity_connect;
   CREATE USER charity_user WITH PASSWORD 'your_secure_password';
   GRANT ALL PRIVILEGES ON DATABASE charity_connect TO charity_user;
   \q
   ```

4. **Initialize the schema**
   ```bash
   psql -U charity_user -d charity_connect -f init_db.sql
   ```
   This creates all tables, enums, indexes, triggers, and a default superadmin user.

5. **Run migrations** (if the database already had some tables)
   ```bash
   psql -U charity_user -d charity_connect -f migrations/20260318_member_requests.sql
   ```

### Option 2: Docker (Recommended)

From the **parent directory** (`CharityConnect-main/`):
```bash
docker-compose up postgres -d
```
This starts PostgreSQL 15 with:
- User: `charity_user` / Password: `charity_password`
- Database: `charity_connect`
- Port: `5432`
- Auto-runs `init_db.sql` on first start

### Option 3: Cloud PostgreSQL (Neon, Supabase, etc.)

Create a database instance and use the connection string:
```
DATABASE_URL=postgresql://user:password@host:5432/dbname?sslmode=require
```

### Auto-migration

On first startup, `app/database.py` runs `ensure_schema()` which auto-creates any missing columns/tables using SQLAlchemy's `metadata.create_all()`. This handles most schema drift, but for enum types or indexes you should run the SQL migrations above.

---

## Environment Variables

Create a `.env` file in the backend root:

```env
# Database (required)
DATABASE_URL=postgresql://charity_user:your_password@localhost:5432/charity_connect

# Security (required — use a long random string in production)
SECRET_KEY=your-secret-key-minimum-32-characters-long
ACCESS_TOKEN_EXPIRE_MINUTES=60

# Debug mode (set False in production)
DEBUG=True

# CORS — comma-separated frontend origins
ALLOWED_ORIGINS=http://localhost:5173,http://localhost:3000

# Redis / Celery (optional — needed for async tasks like WhatsApp)
REDIS_URL=redis://localhost:6379/0
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/0
ENABLE_FASTAPI_LIMITER=false

# File storage (optional — defaults to local disk)
# R2_ENDPOINT_URL=https://your-account.r2.cloudflarestorage.com
# R2_BUCKET_NAME=charity-connect
# R2_PUBLIC_URL=https://pub-xxx.r2.dev
# R2_ACCESS_KEY_ID=
# R2_SECRET_ACCESS_KEY=

# WhatsApp Cloud API (optional)
# WHATSAPP_ENABLED=false
# WHATSAPP_API_TOKEN=
# WHATSAPP_PHONE_NUMBER_ID=

# Logging
LOG_LEVEL=INFO
```

> **Never** commit `.env` to source control.

---

## Running Locally

### 1. Setup Python environment

```bash
cd charity-connect-backend

# Create virtual environment
python -m venv .venv

# Activate it
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Start the API server

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

The server starts at **http://localhost:8000**

- **Swagger docs**: http://localhost:8000/docs (only when `DEBUG=True`)
- **ReDoc**: http://localhost:8000/redoc (only when `DEBUG=True`)
- **Health check**: http://localhost:8000/health
- **DB connectivity test**: http://localhost:8000/test-db

### 3. Seed an admin user (if not using init_db.sql)

```bash
python seed_admin.py
```
Follow the interactive prompts to create a superadmin account.

### 4. Optional: Start Celery workers

```bash
# Worker (processes WhatsApp sends, import jobs)
celery -A app.workers.celery_app.celery worker --loglevel=info

# Beat scheduler (periodic reminders)
celery -A app.workers.celery_app.celery beat --loglevel=info
```

---

## Running with Docker

### Full Stack (backend + frontend + PostgreSQL)

From `CharityConnect-main/` parent directory:
```bash
docker-compose up --build
```

| Service    | URL                    |
|------------|------------------------|
| Backend    | http://localhost:8000  |
| Frontend   | http://localhost:3000  |
| PostgreSQL | localhost:5432         |

### Backend Only

```bash
cd charity-connect-backend
docker build -t charity-backend .
docker run -p 8000:8000 \
  -e DATABASE_URL=postgresql://user:pass@host:5432/db \
  -e SECRET_KEY=your-secret-key-minimum-32-chars \
  -e DEBUG=False \
  charity-backend
```

---

## API Endpoints

### Authentication

| Method | Endpoint           | Access   | Description                    |
|--------|--------------------|----------|--------------------------------|
| POST   | /auth/login        | Public   | Login with username or email + password |
| POST   | /auth/register     | Public   | Register with invite code      |
| GET    | /auth/me           | Auth     | Get current user + member profile |
| POST   | /auth/logout       | Auth     | Logout (client-side token clear) |

### Members

| Method | Endpoint                | Access     | Description                           |
|--------|-------------------------|------------|---------------------------------------|
| GET    | /members                | Auth       | List members (admin=all, member=self) |
| GET    | /members/me             | Auth       | Get own member profile                |
| GET    | /members/summary        | Admin      | Aggregate member counts               |
| POST   | /members                | Superadmin | Create new member                     |
| PUT    | /members/{id}           | Admin      | Update member details                 |
| DELETE | /members/{id}           | Superadmin | Delete member and related data        |
| POST   | /members/import         | Superadmin | Synchronous import from CSV/XLSX      |
| POST   | /members/import/jobs    | Superadmin | Async import with progress tracking   |

### Challans (Payments)

| Method | Endpoint                      | Access   | Description                        |
|--------|-------------------------------|----------|------------------------------------|
| GET    | /challans                     | Auth     | List challans (with filters)       |
| POST   | /challans                     | Auth     | Create challan for a month/campaign|
| GET    | /challans/{id}                | Auth     | Get single challan                 |
| PUT    | /challans/{id}                | Auth     | Update challan                     |
| POST   | /challans/{id}/upload-proof   | Auth     | Upload payment proof file          |
| PATCH  | /challans/{id}/approve        | Admin    | Approve challan                    |
| PATCH  | /challans/{id}/reject         | Admin    | Reject challan                     |
| GET    | /challans/summary             | Auth     | Challan metrics (totals, counts)   |
| GET    | /challans/payable-months      | Auth     | Months available for payment       |
| POST   | /challans/bulk-create         | Auth     | Create challans for multiple months|
| POST   | /challans/import              | Superadmin | Import challan history from file |

### Campaigns

| Method | Endpoint            | Access     | Description                |
|--------|---------------------|------------|----------------------------|
| GET    | /campaigns          | Auth       | List campaigns             |
| POST   | /campaigns          | Admin      | Create campaign            |
| GET    | /campaigns/{id}     | Auth       | Get campaign details       |
| PATCH  | /campaigns/{id}     | Admin      | Update campaign            |
| DELETE | /campaigns/{id}     | Superadmin | Delete campaign            |
| POST   | /campaigns/import   | Superadmin | Import campaigns from file |

### Invites

| Method | Endpoint              | Access   | Description                    |
|--------|-----------------------|----------|--------------------------------|
| POST   | /invites              | Admin    | Create invite (email/phone)    |
| GET    | /invites              | Admin    | List all invites               |
| POST   | /invites/validate     | Public   | Validate invite code           |
| PUT    | /invites/{id}         | Admin    | Update invite                  |
| DELETE | /invites/{id}         | Admin    | Delete invite                  |

### Notifications

| Method | Endpoint                    | Access   | Description                        |
|--------|-----------------------------|----------|------------------------------------|
| GET    | /notifications              | Auth     | Get user's notification feed       |
| POST   | /notifications              | Admin    | Send notification (broadcast/role) |
| PATCH  | /notifications/read         | Auth     | Mark notifications as read         |
| GET    | /notifications/admin/sent   | Admin    | List sent notification batches     |

### Member Requests

| Method | Endpoint                         | Access   | Description                           |
|--------|----------------------------------|----------|---------------------------------------|
| POST   | /requests                        | Auth     | Create request (amount change, etc.)  |
| GET    | /requests                        | Auth     | List own requests                     |
| DELETE | /requests/{id}                   | Auth     | Cancel pending request                |
| GET    | /requests/admin                  | Admin    | List all pending/historical requests  |
| PATCH  | /requests/{id}/approve           | Admin    | Approve request (auto-applies change) |
| PATCH  | /requests/{id}/reject            | Admin    | Reject request with reason            |

### Admin

| Method | Endpoint                        | Access     | Description                        |
|--------|---------------------------------|------------|------------------------------------|
| GET    | /admin/dashboard/charts         | Admin      | Dashboard chart data (collections) |
| GET    | /admin/bulk/pending             | Admin      | Pending bulk challan groups        |
| PATCH  | /admin/bulk/{id}/approve        | Admin      | Approve bulk challan group         |
| PATCH  | /admin/bulk/{id}/reject         | Admin      | Reject bulk challan group          |
| POST   | /admin/system/wipe              | Superadmin | Wipe all operational data          |

### Users (Admin)

| Method | Endpoint        | Access     | Description             |
|--------|-----------------|------------|-------------------------|
| GET    | /users          | Admin      | List all users          |
| GET    | /users/{id}     | Admin      | Get user details        |
| PUT    | /users/{id}     | Admin      | Update user (safe fields only) |
| DELETE | /users/{id}     | Superadmin | Delete user             |

### Files

| Method | Endpoint         | Access | Description                        |
|--------|------------------|--------|------------------------------------|
| POST   | /files/upload    | Auth   | Upload file (proof of payment)     |

### Audit Logs

| Method | Endpoint       | Access | Description                     |
|--------|----------------|--------|---------------------------------|
| GET    | /audit-logs    | Admin  | List audit log entries          |
| POST   | /audit-logs    | Auth   | Create audit log entry          |

---

## Data Model

```
Users (superadmin / admin / member)
  └── Member (1:1, linked via user_id)
        ├── Challans (monthly or campaign payments)
        │     └── BulkChallanGroup (multi-month bundles)
        └── MemberRequests (amount changes, profile updates, complaints)

Campaigns (fundraising goals with target amounts)
  └── Challans (campaign-type donations link here)

Invites (admin-generated registration codes, one-time use)

Notifications (in-app alerts, role-based or individual broadcast)

AuditLogs (entity change tracking with old/new JSON values)
```

### Key Tables

| Table              | Description                                                  |
|--------------------|--------------------------------------------------------------|
| users              | Auth accounts (username, email, password_hash, role)         |
| members            | Member profiles (member_code, phone, monthly_amount, notes)  |
| challans           | Payment records (month, amount, status, proof_url)           |
| bulk_challan_groups| Groups of multi-month payments with single proof             |
| campaigns          | Fundraising campaigns with targets and deadlines             |
| invites            | Registration invite codes (email, phone, expiry)             |
| notifications      | In-app notifications with read tracking                      |
| member_requests    | Member-initiated requests for changes/complaints             |
| audit_logs         | Entity change history with old/new values                    |

---

## Key Flows

### Payment / Challan Flow

1. **Member creates challan** → status: `generated`
2. **Member uploads payment proof** (JPG/PNG/PDF) → status: `pending`
3. **Admin reviews proof** → approves (`approved`) or rejects (`rejected`)
4. **If rejected**, member can re-upload proof → back to `pending`

For **bulk payments**: member selects multiple unpaid months → uploads one proof → individual challans created under a `BulkChallanGroup` → admin approves/rejects the group atomically.

### Registration Flow

1. **Admin creates invite** with target email/phone → invite code generated
2. **User opens registration page** → enters invite code → validated
3. **User fills registration form** (username, password, email, phone)
4. **Backend creates User + Member** in a transaction, marks invite as used
5. **User is logged in** with JWT token

### Member Request Flow

1. **Member submits request** — types: `monthly_amount_change`, `profile_update`, `complaint`, `suggestion`
2. **Request saved** with status `pending`
3. **Admin views pending requests** in admin panel
4. **Admin approves** → if amount change, `member.monthly_amount` is auto-updated
5. **Admin rejects** → provides reason, member sees status update

---

## Security

- **Password hashing** — bcrypt via passlib
- **JWT tokens** — short-lived (configurable), signed with HS256
- **Role guards** — `require_role()` dependency on every protected route
- **Field whitelists** — user update endpoint restricts settable fields
- **File validation** — size limit (3MB), allowed extensions (jpg/png/pdf), MIME checks
- **Rate limiting** — login attempts tracked per username (5 per 15 min window)
- **CORS** — strict origin whitelist via `ALLOWED_ORIGINS` env var
- **Error sanitization** — production errors return generic messages, details logged server-side
- **Audit trail** — all significant changes are logged with old/new values

---

## Deployment

### Heroku
```bash
heroku create charity-connect-api
heroku addons:create heroku-postgresql:mini
heroku config:set SECRET_KEY=your-key ALLOWED_ORIGINS=https://your-frontend.com
git push heroku main
```

### VPS (Budget-Friendly)
- **Minimum**: 2 vCPU, 2 GB RAM, 40 GB SSD (~$10-15/month)
- **Stack**: Ubuntu + PostgreSQL + Nginx reverse proxy + Uvicorn + Let's Encrypt SSL
- Run with: `gunicorn app.main:app -w 4 -k uvicorn.workers.UvicornWorker`

### Docker
See the [Running with Docker](#running-with-docker) section above.

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| `psycopg2` install fails | Install `libpq-dev`: `sudo apt install libpq-dev` (Linux) or use `psycopg2-binary` |
| Database connection error | Verify PostgreSQL is running and `DATABASE_URL` is correct |
| Import error on .xlsx | Ensure `openpyxl` is installed (included in requirements.txt) |
| CORS errors from frontend | Add your frontend URL to `ALLOWED_ORIGINS` in `.env` |
| JWT decode errors | Ensure `SECRET_KEY` is set and consistent across restarts |
| File upload returns 404 | Ensure `app/uploads/proofs/` directory exists |
| Celery tasks not executing | Verify Redis is running and `CELERY_BROKER_URL` is correct |
| Login rate limited | Wait 15 minutes or restart server (clears in-memory counter) |
