## Backend Implementation Guide

Complete FastAPI backend for **Charity Connect** - a membership and donation management system.

### Project Structure

```
app/
├── config.py                  # Settings and environment configuration
├── database.py                # SQLAlchemy setup
├── main.py                    # FastAPI application entry point
├── models/
│   ├── models.py              # SQLAlchemy ORM models
│   └── __init__.py
├── schemas/
│   ├── schemas.py             # Pydantic validation schemas
│   └── __init__.py
├── routes/
│   ├── auth_routes.py         # Authentication endpoints
│   ├── invite_routes.py       # Invite management endpoints
│   ├── member_routes.py       # Member management endpoints
│   ├── challan_routes.py      # Challan/payment endpoints
│   ├── campaign_routes.py     # Campaign endpoints
│   ├── notification_routes.py # Notification endpoints
│   └── __init__.py
├── services/
│   ├── auth_service.py        # Authentication logic
│   ├── invite_service.py      # Invite logic
│   ├── member_service.py      # Member logic
│   ├── challan_service.py     # Challan logic
│   ├── campaign_service.py    # Campaign logic
│   ├── notification_service.py# Notification logic
│   └── __init__.py
├── utils/
│   ├── auth.py                # JWT & password utilities
│   ├── file_handler.py        # File upload utilities
│   └── __init__.py
└── uploads/
    └── proofs/                # Payment proof storage
```

### Database Models

#### User (Authentication)
- Role-based: superadmin, admin, member
- JWT-based authentication with bcrypt password hashing
- Active/inactive status tracking

#### Member
- Personal profiles linked to users
- Sequential member codes (MEM001, MEM002...)
- Monthly amount and join date
- Status tracking (active, inactive, suspended)

#### Invite
- Invite codes for new registrations
- Email/phone based validation
- Expiry dates
- Track used/unused status

#### Campaign
- Occasional donation campaigns
- Title, description, target amount
- Start/end dates with active status
- Admin-created with creator tracking

#### Challan
- Monthly membership or campaign donations
- Status flow: Generated → Pending → Approved/Rejected
- Proof upload with file validation
- Admin approval workflow

#### Notification
- User notifications (in-app)
- Role-based distribution
- Read/unread tracking

#### AuditLog
- Track all important actions
- IP logging for security
- Change history with old/new values

### API Endpoints

#### Authentication
```
POST   /auth/login              # User login
POST   /auth/register           # Register with invite code
GET    /auth/me                 # Get current user
POST   /auth/logout             # Logout
```

#### Invites (Admin)
```
POST   /invites/                # Create invite
GET    /invites/pending         # Get pending invites
POST   /invites/validate        # Validate invite
DELETE /invites/{id}            # Delete invite
```

#### Members
```
GET    /members/                # List all members (admin)
GET    /members/me              # Get my profile
GET    /members/{id}            # Get member details
GET    /members/code/{code}     # Get by member code (admin)
PUT    /members/{id}            # Update member (admin)
```

#### Challans
```
POST   /challans/               # Create challan
POST   /challans/{id}/upload-proof     # Upload payment proof
GET    /challans/               # List all (admin)
GET    /challans/member/{id}    # List member's challans
GET    /challans/{id}           # Get challan details
PUT    /challans/{id}/approve   # Approve (admin)
PUT    /challans/{id}/reject    # Reject (admin)
```

#### Campaigns
```
POST   /campaigns/              # Create campaign (admin)
GET    /campaigns/              # List campaigns
GET    /campaigns/{id}          # Get details
PUT    /campaigns/{id}          # Update (admin)
DELETE /campaigns/{id}          # Delete (admin)
```

#### Notifications
```
POST   /notifications/          # Create & send (admin)
GET    /notifications/          # Get user's notifications
GET    /notifications/unread/count  # Unread count
PUT    /notifications/{id}/read # Mark as read
POST   /notifications/mark-all-read  # Mark all as read
```

### Setup & Running

#### 1. Environment Setup
```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # or venv\Scripts\activate on Windows

# Install dependencies
pip install -r requirements.txt
```

#### 2. Database Setup
```bash
# Create PostgreSQL database
createdb charity_connect

# or via psql:
psql -U postgres
CREATE DATABASE charity_connect;
```

#### 3. Configure Environment
Create `.env` file:
```
DATABASE_URL=postgresql://postgres:password@localhost:5432/charity_connect
SECRET_KEY=your-secure-random-string-here
ACCESS_TOKEN_EXPIRE_MINUTES=60
DEBUG=False
```

#### 4. Run Server
```bash
uvicorn app.main:app --reload
```

Access at: `http://127.0.0.1:8000`
API Docs: `http://127.0.0.1:8000/docs`

### Authentication Flow

1. **User Registration:**
   - Admin creates invite code
   - User provides invite code + credentials
   - System validates and creates user + member profile

2. **Login:**
   - User provides username/password
   - Backend validates & returns JWT token
   - Token included in Authorization header for requests

3. **Access Control:**
   - Superadmin: Full access
   - Admin: Manage invites, members, challenges, approvals
   - Member: View profile, create challans, upload proofs

### Challan Flow

1. **Generation:**
   - Monthly: Auto-available for all members
   - Campaign: Available when campaign active

2. **Proof Upload:**
   - Max 3MB file
   - Supported: JPG, PNG, PDF
   - System stores with timestamp

3. **Approval:**
   - Admin reviews proof
   - Approves or rejects with reason
   - Member notified

### File Upload

Files stored at: `app/uploads/proofs/`

Validation:
- Max 3MB per file
- Allowed: `.jpg`, `.png`, `.pdf`
- MIME type validation
- Timestamp added to filename

### Security Features

- Password hashing: bcrypt
- JWT token expiration
- Role-based access control
- File type/size validation
- Audit logging
- HTTPS recommended for production

### Development Notes

- Uses SQLAlchemy 2.0 with async support ready
- Pydantic v2 for validation
- CORS enabled for frontend integration
- Database tables auto-created on startup
- Cascade delete relationships configured

### Deployment

See README.md for production deployment recommendations (VPS, SSL, backups, etc.)

### Future Enhancements

- Email/SMS notifications
- Payment gateway integration
- Cloud storage for files
- Multi-language support
- Advanced analytics
- Mobile app integration
- Multi-organization support

---

**Status:** Complete and ready for frontend integration
**Last Updated:** February 23, 2026
