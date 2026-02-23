# Charity Connect – Backend API

Backend service for **Charity Connect**, a membership and donation management system.

This API handles:

- Authentication (JWT-based)
- Invite-only registration
- Member management
- Monthly challans
- Campaign (urgent donation) management
- Payment proof uploads
- Admin approvals
- Notifications
- Reporting
- Audit logs

---

## Tech Stack

- FastAPI (Python 3.11+)
- PostgreSQL
- SQLAlchemy 2.0
- JWT Authentication
- Pydantic Validation
- Uvicorn ASGI server

---

# 1. Project Architecture

Frontend (React + Vite + PWA)
        |
FastAPI Backend
        |
PostgreSQL
        |
Local file storage (proof uploads)

---

# 2. Repository Structure


app/
├── main.py
├── config.py
├── database.py
├── models/
├── schemas/
├── routes/
├── services/
└── utils/

.env
requirements.txt
.gitignore
README.md


---

# 3. Local Development Setup

## Requirements

- Python 3.11+
- PostgreSQL
- Git
- VS Code (recommended)

---

## Clone Repository

```bash
git clone https://github.com/Irfanvk/charity-connect-backend.git
cd charity-connect-backend

Create Virtual Environment

Windows:
python -m venv venv
venv\Scripts\activate

Mac/Linux:

python -m venv venv
source venv/bin/activate

Install Dependencies
pip install -r requirements.txt


If requirements.txt not yet created:

pip install fastapi uvicorn sqlalchemy psycopg2-binary python-jose passlib[bcrypt] python-multipart pydantic-settings python-dotenv
pip freeze > requirements.txt

4. PostgreSQL Setup

Login to PostgreSQL:

psql -U postgres


Create database:

CREATE DATABASE charity_connect;


Exit:

\q

5. Environment Variables

Create .env file in project root:

DATABASE_URL=postgresql://postgres:YOUR_PASSWORD@localhost:5432/charity_connect
SECRET_KEY=replace_with_secure_random_string
ACCESS_TOKEN_EXPIRE_MINUTES=60


Never commit .env.

6. Run Backend
uvicorn app.main:app --reload


Open in browser:

http://127.0.0.1:8000


Swagger Docs:

http://127.0.0.1:8000/docs

7. Development Roadmap
Phase 1 – Infrastructure

FastAPI setup

PostgreSQL connection

Alembic migrations

Phase 2 – Authentication

Password hashing (bcrypt)

JWT token generation

Login endpoint

Logout endpoint

Current user endpoint

Role-based access control

Endpoints:

POST /auth/login

POST /auth/logout

GET /auth/me

Roles:

superadmin

admin

member

Phase 3 – Invite System

Admin creates invite code

Invite has email/phone + expiry

User registers using invite

Invite marked used

Endpoints:

POST /invites

POST /invites/validate

POST /auth/register

Phase 4 – Member System

member_code (sequential suggestion)

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