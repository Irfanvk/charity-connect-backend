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
│   ├── main.py              # entrypoint
│   ├── config.py            # settings & env loader
│   ├── database.py          # SQLAlchemy engine/session
│   ├── models/              # ORM models
│   ├── schemas/             # Pydantic schemas
│   ├── routes/              # FastAPI routers
│   ├── services/            # business logic
│   └── utils/               # helpers & misc
├── .env                     # local environment (ignored)
├── requirements.txt         # pinned dependencies
├── README.md                # this file
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
```

> **Never** commit `.env` to source control.

### Running the Server

```bash
uvicorn app.main:app --reload
```

- Open the API: `http://127.0.0.1:8000`
- Explore docs: `http://127.0.0.1:8000/docs`

---

## 🛣️ Roadmap

### Phase 1 – Infrastructure

- FastAPI project scaffolding
- PostgreSQL connectivity
- Alembic migrations (TODO)

### Phase 2 – Authentication & Authorization

- bcrypt password hashing
- JWT token handling
- Login / logout / current-user endpoints
- Role-based access: `superadmin`, `admin`, `member`

### Phase 3 – Invite-Only Registration

- Admin generates invite codes
- Codes attach to email/phone & expiry
- Registration endpoint validates invite and marks as used

Endpoints:
```
POST /invites             # create invite
POST /invites/validate    # check invite
POST /auth/register       # register with invite
```

### Phase 4 – Member System

- Sequential member codes
- Profile management
- (more to come...)

---

## 💡 Tips & Notes

- Use a tool like `pgAdmin` or `psql` to inspect data.
- Add tests under `tests/` as features stabilize.
- Consider Dockerizing for deployment.

---

Thanks for contributing! 🎉

Let’s make charity simple and transparent.


monthly_amount

join date

status

Endpoints:

GET /members

POST /members

PUT /members/{id}

DELETE /members/{id}

Phase 5 – Campaign System

title

description

target_amount

start_date

end_date

active status

Endpoints:

GET /campaigns

POST /campaigns

PUT /campaigns/{id}

DELETE /campaigns/{id}

Phase 6 – Challan System

Status Flow:
generated → pending → approved / rejected

Fields:

member_id

type (monthly / campaign)

campaign_id (optional)

month (for monthly)

amount

payment_method

proof_path

status

approved_by

Endpoints:

POST /challans/generate

POST /challans/{id}/upload-proof

PUT /challans/{id}/approve

PUT /challans/{id}/reject

GET /challans

Phase 7 – Notifications

title

message

target_role (optional)

Endpoints:

GET /notifications

POST /notifications

8. File Upload Strategy

Store proofs in:

/uploads/proofs/


Rules:

Max 5MB

jpg, png, pdf only

Save relative path in database

Validate MIME type

9. Security

Hash all passwords

Protect admin routes

Validate all inputs

Use HTTPS in production

Log important actions (audit logs)

10. Deployment Plan (Budget-Friendly)

Recommended:
Single VPS

Minimum:

2 vCPU

2–4 GB RAM

40+ GB SSD

Install:

Ubuntu

PostgreSQL

Nginx

Uvicorn

Let's Encrypt SSL


Goal

Build a stable, scalable backend powering Charity Connect that:

Replaces Excel workflows

Reduces admin workload

Maintains clean financial records

Supports long-term growth