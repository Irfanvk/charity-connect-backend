# Charity Connect -- Backend API

## Project Overview

Charity Connect is a Membership & Donation Management System designed
for charity organizations to manage:

-   Members
-   Monthly Membership Payments
-   Urgent / Campaign Donations
-   Challans
-   Proof Uploads
-   Admin Approval Workflow
-   Notifications
-   Reports

This backend is built using:

-   FastAPI (Python 3.11+)
-   PostgreSQL
-   SQLAlchemy ORM
-   JWT Authentication
-   Role-Based Access Control

------------------------------------------------------------------------

# Architecture

Frontend (React + Vite + PWA) | FastAPI Backend (Python) |
PostgreSQL Database | File Storage (Local → Cloud Later)

------------------------------------------------------------------------

# Technology Stack

Backend Framework: FastAPI\
Database: PostgreSQL\
ORM: SQLAlchemy\
Authentication: JWT + Passlib (bcrypt)\
Server: Uvicorn\
Environment Config: Pydantic Settings\
Deployment: VPS (Ubuntu)

------------------------------------------------------------------------

# Folder Structure

app/ 
├── main.py 
├── config.py 
├── database.py 
├── models/ 
├── schemas/
├── routes/ 
├── services/ 
└── utils/

------------------------------------------------------------------------

# Local Development Setup

## 1. Clone Repository

git clone `<repo-url>`{=html} cd charity-connect-backend

## 2. Create Virtual Environment

python -m venv venv venv`\Scripts`{=tex}`\activate`{=tex}

## 3. Install Dependencies

pip install -r requirements.txt

## 4. Create .env File

Create a .env file in root:

DATABASE_URL=postgresql://postgres:YOURPASSWORD@localhost:5432/charity_connect
SECRET_KEY=change_this_to_secure_key ACCESS_TOKEN_EXPIRE_MINUTES=60

## 5. Run Development Server

uvicorn app.main:app --reload

Access: http://127.0.0.1:8000 Swagger Docs: http://127.0.0.1:8000/docs

------------------------------------------------------------------------

# Database Schema (Planned)

## users

-   id (uuid)
-   username
-   email
-   phone
-   password_hash
-   role (superadmin, admin, member)
-   is_active
-   created_at

## members

-   id
-   user_id
-   member_code
-   address
-   monthly_amount
-   joined_at
-   status

## invites

-   id
-   email_or_phone
-   invite_code
-   is_used
-   expires_at
-   created_by
-   created_at

## campaigns

-   id
-   title
-   description
-   target_amount
-   start_date
-   end_date
-   is_active

## challans

-   id
-   member_id
-   type (monthly / campaign)
-   campaign_id (nullable)
-   amount
-   status (generated, pending, approved, rejected)
-   payment_method
-   proof_path
-   month
-   created_at
-   approved_by
-   approved_at

## notifications

-   id
-   title
-   message
-   target_role
-   created_by
-   created_at

------------------------------------------------------------------------

# Development Roadmap

## Phase 1 -- Core Infrastructure

-   Database connection
-   User model
-   Password hashing
-   JWT authentication
-   Role-based access control

## Phase 2 -- Invite System

-   Admin creates invite
-   User registers with invite code
-   Member ID assignment

## Phase 3 -- Member Management

-   CRUD operations
-   Monthly membership setup

## Phase 4 -- Campaigns & Donations

-   Campaign CRUD
-   Challan generation
-   Payment proof upload
-   Admin approval workflow

## Phase 5 -- Notifications

-   Admin post system
-   Role-based visibility

## Phase 6 -- Reports

-   Member statements
-   Monthly collections
-   Export endpoints

------------------------------------------------------------------------

# Git Workflow (For Collaboration)

Branch Strategy:

main → Production-ready code\
dev → Integration branch\
feature/\* → New features\
hotfix/\* → Emergency fixes

Never push directly to main. Use Pull Requests.

------------------------------------------------------------------------

# Hosting Plan

Recommended VPS: - 2 vCPU - 2--4 GB RAM - 40--80 GB SSD - Ubuntu 22.04

Estimated cost: \$8--15/month

Use: - Nginx - Gunicorn or Uvicorn workers - Let's Encrypt SSL - Daily
PostgreSQL backups

------------------------------------------------------------------------

# Security Best Practices

-   Never commit .env
-   Use strong SECRET_KEY
-   Hash passwords with bcrypt
-   Enforce HTTPS in production
-   Limit file upload size (max 5MB)
-   Implement audit logs

------------------------------------------------------------------------

# Future Enhancements

-   SMS/WhatsApp notifications
-   Payment gateway integration
-   Multi-language support
-   Multi-organization support
-   Cloud storage (S3)
-   CI/CD pipeline
-   Automated backups

------------------------------------------------------------------------

# Contributors

Project Owner: Abdul Latheef\
Backend Developer: Mr. Simsar

------------------------------------------------------------------------

Charity Connect -- Building Transparent & Accountable Charity Systems
