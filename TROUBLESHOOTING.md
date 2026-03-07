# CharityConnect Troubleshooting Guide

**Last Updated:** March 7, 2026

---

## Table of Contents
1. [Quick Fixes](#quick-fixes)
2. [Common Issues](#common-issues)
3. [Debugging Guide](#debugging-guide)
4. [Production Issues](#production-issues)

---

## Quick Fixes

### Issue: "No member record found for your account"

**Problem:** User account exists but has no corresponding Member profile in the database.

**Quick Fix (30 seconds):**

Open PowerShell in the backend directory and run:

```powershell
$env:PGPASSWORD='StrongPassword123'; psql -U charity_user -d charity_connect -c "INSERT INTO members (user_id, member_code, monthly_amount, status) SELECT u.id, 'MEM' || LPAD((COALESCE((SELECT MAX(CAST(SUBSTRING(member_code FROM 4) AS INT)) FROM members), 0) + ROW_NUMBER() OVER (ORDER BY u.id))::TEXT, 4, '0'), 0.0, 'active' FROM users u LEFT JOIN members m ON m.user_id = u.id WHERE u.role = 'member' AND m.id IS NULL RETURNING user_id, member_code;"
```

**Expected Output:**
```
 user_id | member_code
---------+-------------
       5 | MEM0005
(1 row)

INSERT 0 1
```

**Alternative: Use PowerShell Script**
```powershell
.\fix_missing_members.ps1
```

**Alternative: Use SQL File**
```bash
psql -U charity_user -d charity_connect -f fix_missing_members.sql
```

**Manual SQL Fix (for specific user):**
```sql
-- Check which users are missing member records
SELECT u.id, u.username, u.email, u.role
FROM users u
LEFT JOIN members m ON m.user_id = u.id
WHERE u.role = 'member' AND m.id IS NULL;

-- Get the last member code
SELECT member_code FROM members ORDER BY id DESC LIMIT 1;

-- Create member record (adjust code as needed)
INSERT INTO members (user_id, member_code, monthly_amount, status, address)
VALUES (5, 'MEM0005', 0.0, 'active', NULL);
```

**Verification:**
```sql
SELECT 
    u.id as user_id,
    u.username,
    u.email,
    m.id as member_id,
    m.member_code,
    m.status
FROM users u
LEFT JOIN members m ON m.user_id = u.id
WHERE u.id = 5;
```

**Root Causes:**
- User created directly in database without registration flow
- Member record accidentally deleted
- Registration transaction didn't complete properly

**Prevention:**
- Always create users via `/auth/register` endpoint
- Don't create users directly in database
- Use database transactions to ensure User and Member created together

---

### Issue: Challan Approve Endpoint 422 Error

**Problem:** `PATCH /challans/{id}/approve` returns 422 Unprocessable Entity when frontend sends empty body `{}`.

**Root Cause:** Backend schema required `approved_by_admin_id` in request body, but this should be extracted from JWT token.

**Solution:** Extract admin ID from JWT token automatically.

**Files Modified:**

#### 1. Schema (app/schemas/schemas.py)
```python
class ChallanApprove(BaseModel):
    approved_by_admin_id: Optional[int] = None  # Made optional
```

#### 2. Route (app/routes/challan_routes.py)
```python
@router.patch("/{challan_id}/approve", response_model=ChallanResponse)
def approve_challan(
    challan_id: int,
    approve_data: ChallanApprove,
    current_user: dict = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    # Extract admin ID from JWT if not provided
    admin_id = approve_data.approved_by_admin_id or current_user.get("user_id")
    return ChallanService.approve_challan(db, challan_id, admin_id)
```

#### 3. Service (app/services/challan_service.py)
```python
@staticmethod
def approve_challan(db: Session, challan_id: int, approved_by_admin_id: int):
    challan = db.query(Challan).filter(Challan.id == challan_id).first()
    if not challan:
        raise HTTPException(status_code=404, detail="Challan not found")
    
    challan.status = "approved"
    challan.approved_by_admin_id = approved_by_admin_id
    challan.approved_at = datetime.utcnow()
    
    db.commit()
    db.refresh(challan)
    return challan
```

**Testing:**
```bash
# Before fix - Returns 422
curl -X PATCH http://127.0.0.1:8000/challans/1/approve \
  -H "Authorization: Bearer <admin_token>" \
  -H "Content-Type: application/json" \
  -d "{}"

# After fix - Returns 200
curl -X PATCH http://127.0.0.1:8000/challans/1/approve \
  -H "Authorization: Bearer <admin_token>" \
  -H "Content-Type: application/json" \
  -d "{}"
```

**Security Benefits:**
- Client cannot spoof another admin's ID
- Leverages existing JWT validation
- Reduces frontend complexity

---

## Common Issues

### 403 Forbidden on /challans/ or /members/

**Problem:** Member role gets 403 error when accessing lists.

**Root Cause:** Endpoints were admin-only. Members should see filtered data (own records).

**Solution:** Implement role-based filtering:

**Challans:**
```python
@router.get("/", response_model=List[ChallanResponse])
def get_challans(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
    sort_by: str = Query("created_at"),
    sort_order: str = Query("desc"),
):
    role = current_user.get("role")
    
    if role in ["admin", "superadmin"]:
        return ChallanService.get_all_challans(db, sort_by, sort_order)
    else:
        # Members see only their own
        member = db.query(Member).filter(Member.user_id == current_user["user_id"]).first()
        if not member:
            raise HTTPException(status_code=404, detail="No member record found")
        return ChallanService.get_member_challans(db, member.id, sort_by, sort_order)
```

**Members:**
```python
@router.get("/", response_model=List[MemberResponse])
def get_members(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    role = current_user.get("role")
    
    if role in ["admin", "superadmin"]:
        return MemberService.get_all_members(db)
    else:
        # Members see only themselves
        member = db.query(Member).filter(Member.user_id == current_user["user_id"]).first()
        if not member:
            return []
        return [member]
```

### CORS Preflight Failures

**Problem:** Browser preflight OPTIONS requests fail with CORS errors.

**Root Cause:** Middleware order matters. TrustedHostMiddleware processing before CORS headers added.

**Solution:** Add CORSMiddleware FIRST (executes last due to middleware stack):

```python
# app/main.py - Correct order
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=["localhost", "127.0.0.1", "*.example.com"],
)
```

### Port Already in Use (Address:8000)

**Problem:** `uvicorn` fails to start with error `[Errno 10048] error while attempting to bind on address ('127.0.0.1', 8000)`

**Solution:**

**Option 1: Kill existing process**
```powershell
Get-Process python | Where-Object {$_.Path -like '*charity-connect-backend*'} | Stop-Process -Force
```

**Option 2: Use different port**
```bash
uvicorn app.main:app --port 8001
```

**Option 3: Find and kill process on port 8000**
```powershell
netstat -ano | findstr :8000
taskkill /PID <process_id> /F
```

### 401 Unauthorized After Login

**Problem:** Token returned from login, but subsequent requests return 401.

**Root Causes:**
1. **JWT subject type mismatch** - `sub` claim stored as int but parsed as string
2. **Token not included in request** - Frontend not sending Authorization header
3. **Token expired** - Check `ACCESS_TOKEN_EXPIRE_MINUTES` setting

**Solutions:**

**1. Fix JWT subject type:**
```python
# app/utils/auth.py
def create_access_token(data: dict):
    to_encode = data.copy()
    # Store sub as string
    to_encode["sub"] = str(to_encode["sub"])
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def decode_access_token(token: str):
    payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    # Convert sub back to int
    user_id = int(payload.get("sub"))
    return {"user_id": user_id, "role": payload.get("role")}
```

**2. Verify Authorization header:**
```javascript
// Frontend - Correct
headers: {
  'Authorization': `Bearer ${token}`,
  'Content-Type': 'application/json'
}
```

**3. Check token expiry:**
```python
# .env or app/config.py
ACCESS_TOKEN_EXPIRE_MINUTES=60  # Increase if needed
```

### Duplicate Username/Email on Registration

**Problem:** Registration succeeds but creates duplicate users.

**Solution:** Check for duplicates before creating:

```python
@router.post("/register", status_code=status.HTTP_201_CREATED)
def register(user_data: UserRegister, db: Session = Depends(get_db)):
    # Check duplicates
    existing_user = db.query(User).filter(
        (User.username == user_data.username) | 
        (User.email == user_data.email)
    ).first()
    
    if existing_user:
        if existing_user.username == user_data.username:
            raise HTTPException(status_code=409, detail="Username already exists")
        else:
            raise HTTPException(status_code=409, detail="Email already exists")
    
    # Continue with registration...
```

---

## Debugging Guide

### Enable Debug Mode

```python
# app/config.py or .env
DEBUG=True
```

**Effects:**
- Detailed error stack traces in responses
- Auto-reload on code changes
- Enhanced logging

**Warning:** Never enable in production!

### Check Database Connection

```python
# Test script
from app.database import SessionLocal

def test_db():
    db = SessionLocal()
    try:
        db.execute("SELECT 1")
        print("✅ Database connected")
    except Exception as e:
        print(f"❌ Database error: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    test_db()
```

### Verify Environment Variables

```python
# app/config.py
from dotenv import load_dotenv
import os

load_dotenv()

print("Database URL:", os.getenv("DATABASE_URL"))
print("Secret Key:", os.getenv("SECRET_KEY")[:10] + "...")
print("Debug Mode:", os.getenv("DEBUG"))
```

### Test JWT Token Manually

```python
from app.utils.auth import create_access_token, decode_access_token

# Create token
token = create_access_token({"sub": 1, "role": "admin"})
print(f"Token: {token}")

# Decode token
payload = decode_access_token(token)
print(f"Payload: {payload}")
```

### Common Log Messages

**Good:**
```
INFO:     Started server process [12345]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://127.0.0.1:8000
```

**Bad:**
```
ERROR:    Can't connect to database
ERROR:    Invalid token signature
WARNING:  CORS origin not allowed
```

---

## Production Issues

### Database Migration Issues

**Problem:** Schema mismatch between models and database.

**Solution:** Use Alembic for migrations:

```bash
# Install Alembic
pip install alembic

# Initialize
alembic init alembic

# Create migration
alembic revision --autogenerate -m "Add new field"

# Apply migration
alembic upgrade head
```

### Environment Variables Not Loading

**Problem:** Application uses default values instead of .env values.

**Solutions:**

1. **Check .env location** - Must be in project root
2. **Verify python-dotenv installed** - `pip install python-dotenv`
3. **Load explicitly:**
```python
from dotenv import load_dotenv
load_dotenv()  # Call before accessing os.getenv()
```

### Performance Issues

**Symptoms:**
- Slow response times
- High CPU usage
- Database connection errors

**Solutions:**

1. **Add database indexes:**
```sql
CREATE INDEX idx_challans_status ON challans(status);
CREATE INDEX idx_challans_member_id ON challans(member_id);
CREATE INDEX idx_members_user_id ON members(user_id);
```

2. **Enable connection pooling:**
```python
# app/database.py
engine = create_engine(
    DATABASE_URL,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True
)
```

3. **Add query pagination:**
```python
@router.get("/challans/")
def get_challans(
    skip: int = Query(0),
    limit: int = Query(100, le=1000),
    db: Session = Depends(get_db)
):
    challans = db.query(Challan).offset(skip).limit(limit).all()
    return challans
```

---

## Still Having Issues?

1. Check `COMMUNICATION_LOG.md` for recent changes
2. Review `API_DOCUMENTATION.md` for correct usage
3. Test endpoints with Swagger UI at `/docs`
4. Enable debug mode and check logs
5. Verify database state with SQL queries

**Emergency Database Reset:**
```sql
-- DANGER: This deletes all data
DROP DATABASE charity_connect;
CREATE DATABASE charity_connect;
-- Then run migrations or initialization script
```
