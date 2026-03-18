# 🎗️ Charity Connect Backend

Welcome to the **Charity Connect** backend API – the engine powering donation management, member tracking, and administrative workflows for a socially-driven community platform.

> _A secure, invite-only system where giving meets governance._

---

## 🚀 What It Does

This service handles everything necessary for membership and donation operations:

- 🔐 JWT-based authentication & role control
- 📨 Invite-only user registration
- 👥 Member creation and management
- 💰 Monthly challan tracking
- 🚨 Urgent campaign coordination
- 📸 Payment proof uploads with storage
- ✅ Admin approvals for actions
- 🔔 Notifications and alerts
- 📊 Reporting dashboards
- 📝 Audit logs for accountability

---

## 🛠️ Technology Stack

| Component        | Details                    |
|------------------|----------------------------|
| Framework        | FastAPI (Python 3.11+)     |
| Database         | PostgreSQL                 |
| ORM              | SQLAlchemy 2.0             |
| Auth             | JWT + role-based policies  |
| Validation       | Pydantic                   |
| Server           | Uvicorn (ASGI)             |

> Fully containerizable and production-ready.

---

## 📁 Repository Layout

```
charity-connect-backend/
├── app/
│   ├── main.py                      # FastAPI app entry point
│   ├── config.py                    # Settings & env loader
│   ├── database.py                  # SQLAlchemy engine/session
│   ├── models/models.py             # 7 database ORM models
│   ├── schemas/schemas.py           # Pydantic validation schemas
│   ├── routes/                      # FastAPI routers (6 modules)
│   ├── services/                    # Business logic layer (6 services)
│   ├── utils/                       # JWT & file utilities
│   └── uploads/proofs/              # Payment proof storage
├── .env                     # Environment configuration (ignored)
├── requirements.txt         # Python dependencies
├── README.md                # Project overview (this file)
├── IMPLEMENTATION.md        # Technical documentation
├── GETTING_STARTED.md       # Setup & development guide
└── .gitignore
```

---

## ⚡ Local Development

### Prerequisites

- Python **3.11+**
- PostgreSQL server
- Git (for repo cloning)
- VS Code (recommended, with Python extension)

### Get Started

```bash
# clone
git clone https://github.com/Irfanvk/charity-connect-backend.git
cd charity-connect-backend

# create & activate virtual environment
python -m venv venv
# Windows:
venv\Scripts\activate
# macOS/Linux:
source venv/bin/activate

# install dependencies
pip install -r requirements.txt
```

_If you haven't generated `requirements.txt` yet:_

```bash
pip install fastapi uvicorn sqlalchemy psycopg2-binary python-jose passlib[bcrypt] \
    python-multipart pydantic-settings python-dotenv
pip freeze > requirements.txt
```

### Database Setup

1. Log in to PostgreSQL:
   ```bash
   psql -U postgres
   ```
2. Create the project database:
   ```sql
   CREATE DATABASE charity_connect;
   ```
3. Exit with `\q`.

### Environment Variables

Create a `.env` file in project root with:

```
DATABASE_URL=postgresql://postgres:YOUR_PASSWORD@localhost:5432/charity_connect
SECRET_KEY=<secure-random-string>
ACCESS_TOKEN_EXPIRE_MINUTES=60
REDIS_URL=redis://localhost:6379/0
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/0
ENABLE_FASTAPI_LIMITER=false
```

> **Never** commit `.env` to source control.

### Running the Server

```bash
uvicorn app.main:app --reload
```

### Running Worker and Scheduler

Use separate terminals for API, Celery worker, and Celery Beat scheduler.

```bash
celery -A app.workers.celery_app.celery worker --loglevel=info
celery -A app.workers.celery_app.celery beat --loglevel=info
```

This enables:
- invite WhatsApp queue processing
- welcome notification queue for newly registered users
- monthly membership reminder scheduler

- **API Base**: `http://127.0.0.1:8000`
- **Swagger Docs**: `http://127.0.0.1:8000/docs` (try endpoints interactively)
- **ReDoc**: `http://127.0.0.1:8000/redoc` (view full API documentation)

> For detailed setup instructions, see [GETTING_STARTED.md](GETTING_STARTED.md)

---

## 🛣️ Roadmap

### Phase 1 – Infrastructure
- FastAPI setup
- PostgreSQL connection
- Alembic migrations

### Phase 2 – Authentication
- Password hashing (bcrypt)
- JWT token generation
- Login endpoint
- Logout endpoint
- Current user endpoint
- Role-based access control
  - **Endpoints:**
    - `POST /auth/login`
    - `POST /auth/logout`
    - `GET /auth/me`
  - **Roles:**
    - superadmin
    - admin
    - member

### Phase 3 – Invite System
- Admin creates invite code
- Invite has email/phone + expiry
- User registers using invite
- Invite marked used
  - **Endpoints:**
    - `POST /invites`
    - `POST /invites/validate`
    - `POST /auth/register`

Endpoints:

POST /invites

POST /invites/validate

POST /auth/register

### Phase 4 – Member System
- member_code (sequential suggestion)
- monthly_amount
- join date
- status
  - **Endpoints:**
    - `GET /members`
    - `POST /members`
    - `PUT /members/{id}`
    - `DELETE /members/{id}`

### Phase 5 – Campaign System
- title
- description
- target_amount
- start_date
- end_date
- active status
  - **Endpoints:**
    - `GET /campaigns`
    - `POST /campaigns`
    - `PUT /campaigns/{id}`
    - `DELETE /campaigns/{id}`

### Phase 6 – Challan System
- **Status Flow:** generated → pending → approved / rejected
- **Fields:**
  - member_id
  - type (monthly / campaign)
  - campaign_id (optional)
  - month (for monthly)
  - amount
  - payment_method
  - proof_path
  - status
  - approved_by
  - **Endpoints:**
    - `POST /challans/generate`
    - `POST /challans/{id}/upload-proof`
    - `PUT /challans/{id}/approve`
    - `PUT /challans/{id}/reject`
    - `GET /challans`

### Phase 7 – Notifications
- title
- message
- target_role (optional)
  - **Endpoints:**
    - `GET /notifications`
    - `POST /notifications`
    - `GET /notifications/feed`
    - `PATCH /notifications/read`

### Phase 8 – Dashboard Aggregates
- `GET /admin/dashboard/charts`
  - campaign progress
  - monthly donations
  - top donors

---

### 📂 File Upload Strategy
- Store proofs in `/uploads/proofs/`
- **Rules:**
  - Max 3MB per file
  - jpg, png, pdf only
  - Timestamped filenames for uniqueness
  - Validate MIME type

### 🔐 Security Features
- Password hashing with bcrypt
- JWT expiration and validation
- Role-based route protection
- File size and type validation
- Audit logging for compliance
- HTTPS recommended for production

### 🚢 Deployment Plan (Budget-Friendly)
**Recommended: single VPS**

- **Minimum specs:**
  - 2 vCPU
  - 2–4 GB RAM
  - 40+ GB SSD
- **Stack:**
  - Ubuntu
  - PostgreSQL
  - Nginx
  - Uvicorn
  - Let’s Encrypt SSL
- **Estimated cost:** $10–15 per month

---

### 🎯 Goals Achieved

✅ Replaced Excel workflows with robust database system
✅ Reduced admin workload with automation
✅ Maintained clean financial records with audit logs
✅ Built modular, scalable architecture
✅ Implemented budget-friendly solution (self-hosted)
✅ Production-ready code with comprehensive error handling

---

## 📚 Documentation & Resources

View detailed documentation for setup and development:
- **[GETTING_STARTED.md](GETTING_STARTED.md)** - Setup guide, testing endpoints, common tasks
- **[IMPLEMENTATION.md](IMPLEMENTATION.md)** - Technical architecture, API reference, models
- **API Docs** - Interactive at `/docs` when server runs

## 🔗 Next Steps

1. Follow [GETTING_STARTED.md](GETTING_STARTED.md) to set up your development environment
2. Access API docs at `http://127.0.0.1:8000/docs` after running the server
3. Review [IMPLEMENTATION.md](IMPLEMENTATION.md) for technical details
4. Integrate with [charity-connect-frontend](../charity-connect-frontend) (Vue.js)