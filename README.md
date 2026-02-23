Charity Connect – Backend API

Backend service for Charity Connect, a membership and donation management system.

This API handles:

Authentication (JWT-based)

Invite-only registration

Member management

Monthly challans

Campaign (urgent donation) management

Payment proof uploads

Admin approvals

Notifications

Reporting

Audit logs

Built with:

FastAPI (Python 3.11+)

PostgreSQL

SQLAlchemy 2.0

JWT Authentication

Pydantic Validation

1. Project Architecture
Frontend (React + Vite + PWA)
        |
        |
FastAPI Backend
        |
        |
PostgreSQL
        |
        |
Local file storage (proof uploads)

2. Repository Structure
app/
 ├── main.py              # Application entrypoint
 ├── config.py            # Environment settings
 ├── database.py          # DB engine and session
 ├── models/              # SQLAlchemy models
 ├── schemas/             # Pydantic schemas
 ├── routes/              # API route modules
 ├── services/            # Business logic
 └── utils/               # Utilities (auth, hashing, etc.)

.env                      # Local environment variables (NOT committed)
requirements.txt
.gitignore

3. Local Development Setup
3.1 Requirements

Python 3.11+

PostgreSQL installed

Git

VS Code (recommended)

3.2 Clone Repository
git clone https://github.com/Irfanvk/charity-connect-backend.git
cd charity-connect-backend

3.3 Create Virtual Environment
python -m venv venv


Activate (Windows):

venv\Scripts\activate


Activate (Mac/Linux):

source venv/bin/activate

3.4 Install Dependencies
pip install -r requirements.txt


If requirements file not present:

pip install fastapi uvicorn sqlalchemy psycopg2-binary python-jose passlib[bcrypt] python-multipart pydantic-settings python-dotenv
pip freeze > requirements.txt

4. PostgreSQL Setup
4.1 Create Database

Login to PostgreSQL:

psql -U postgres


Create database:

CREATE DATABASE charity_connect;


Exit:

\q

4.2 Create .env File

Create .env in root:

DATABASE_URL=postgresql://postgres:YOUR_PASSWORD@localhost:5432/charity_connect
SECRET_KEY=replace_with_secure_random_string
ACCESS_TOKEN_EXPIRE_MINUTES=60


Never commit .env.

5. Run Backend
uvicorn app.main:app --reload


Visit:

http://127.0.0.1:8000


Swagger Docs:

http://127.0.0.1:8000/docs


Database test endpoint (if enabled):

http://127.0.0.1:8000/test-db

6. Git Collaboration Rules
Branch Strategy

Never push directly to main.

Create feature branches:

feature/auth-system
feature/member-model
feature/invite-system
feature/challan-system
feature/campaigns
feature/notifications


Workflow:

git checkout -b feature/xyz
git commit -m "Add xyz"
git push origin feature/xyz


Then open Pull Request.

7. Backend Development Roadmap
Phase 1 – Core Infrastructure

 FastAPI setup

 PostgreSQL connection

 Base model configuration

 Alembic migrations setup

Phase 2 – Authentication System
Features:

Password hashing (bcrypt)

JWT token generation

Login endpoint

Logout endpoint

Get current user endpoint

Role-based access control

Endpoints:

POST /auth/login
POST /auth/logout
GET  /auth/me


Roles:

superadmin

admin

member

Phase 3 – Invite System

Admins create invite codes.

Flow:

Admin generates invite

Invite contains:

email or phone

invite code

expiry date

User registers using invite code

Invite marked as used

Endpoints:

POST /invites
POST /invites/validate
POST /auth/register

Phase 4 – Member System

Each member has:

member_code (auto-suggested sequential)

monthly_amount

join date

status

Endpoints:

GET    /members
POST   /members
PUT    /members/{id}
DELETE /members/{id}

Phase 5 – Campaign System

For urgent donations.

Fields:

title

description

target amount

start date

end date

active status

Endpoints:

GET    /campaigns
POST   /campaigns
PUT    /campaigns/{id}
DELETE /campaigns/{id}

Phase 6 – Challan System

Supports:

Monthly dues

Campaign donations

Status flow:

generated → pending → approved/rejected


Fields:

member_id

type

campaign_id (optional)

month (for monthly payments)

amount

payment_method

proof_path

status

approved_by

Endpoints:

POST   /challans/generate
POST   /challans/{id}/upload-proof
PUT    /challans/{id}/approve
PUT    /challans/{id}/reject
GET    /challans

Phase 7 – Notifications

Admin-created posts.

Fields:

title

message

target_role (optional)

Endpoints:

GET  /notifications
POST /notifications

Phase 8 – Reports

Monthly collection summary

Member payment statement

Campaign performance

Export-ready endpoints

8. File Upload Strategy

Proof uploads:

/uploads/proofs/


Rules:

Max size: 5MB

Allowed: jpg, png, pdf

Store relative path in DB

Validate MIME type

Later upgrade:

Move to S3-compatible storage

9. Security Rules

Always hash passwords

Never expose SECRET_KEY

Use HTTPS in production

Validate all input via Pydantic

Restrict admin endpoints via role check

Implement audit logs for:

Approvals

Member edits

Invite creation

10. Deployment Plan (Budget-Friendly)

Recommended:

Single VPS:

2 vCPU

2–4 GB RAM

40+ GB SSD

Install:

Ubuntu

PostgreSQL

Nginx

Uvicorn (systemd service)

Let's Encrypt SSL

Estimated cost:

$10–15 per month

11. Immediate Next Tasks

Next development priority:

Create User model

Implement password hashing utility

Implement JWT token creation

Implement /auth/login

Protect routes with dependency injection

After auth works, move to Invite system.

12. Development Principles

Keep code modular

Keep routes thin

Put logic in services

Use migrations (Alembic)

Do not over-engineer

Test endpoints in Swagger first

Commit small changes frequently

13. Long-Term Enhancements

Email reminders

WhatsApp notifications

Payment gateway integration

Multi-organization support

Multi-language UI

Automated backups

Role expansion

End Goal

Deliver a stable, scalable, secure backend powering Charity Connect:

Replace Excel workflows

Reduce admin workload

Maintain accurate donation records

Support long-term growth