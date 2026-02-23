## Getting Started - Backend Development

### Quick Start (5 minutes)

#### 1. Setup Environment
```bash
# Clone and navigate
cd d:\Projects\IrfAn\CharityConnect-main\charity-connect-backend

# Create virtual environment
python -m venv venv
venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

#### 2. Setup Database
```bash
# Ensure PostgreSQL is running
# Create database using psql or your preferred client
createdb charity_connect

# Or manually:
psql -U postgres
CREATE DATABASE charity_connect;
\q
```

#### 3. Configure Environment
Create `.env` file in project root:
```
DATABASE_URL=postgresql://postgres:YOUR_PASSWORD@localhost:5432/charity_connect
SECRET_KEY=super-secret-key-change-this-in-production
ACCESS_TOKEN_EXPIRE_MINUTES=60
DEBUG=False
```

#### 4. Run Server
```bash
uvicorn app.main:app --reload
```

**Server Running:**
- API: http://127.0.0.1:8000
- Docs: http://127.0.0.1:8000/docs (interactive)
- ReDoc: http://127.0.0.1:8000/redoc

---

### Testing the API

#### 1. Create Admin User (Direct Database)
```sql
INSERT INTO users (username, email, phone, password_hash, role, is_active)
VALUES (
    'admin1',
    'admin@example.com',
    '+1234567890',
    -- bcrypt hash of 'password123'
    '$2b$12$your_bcrypt_hash_here',
    'admin',
    true
);
```

Or use Python:
```python
from app.utils import hash_password
pwd_hash = hash_password("password123")
print(pwd_hash)  # Use this in database
```

#### 2. Login with Swagger UI
1. Go to http://127.0.0.1:8000/docs
2. Click "Try it out" on POST /auth/login
3. Enter: `{"username": "admin1", "password": "password123"}`
4. Copy the `access_token` from response
5. Click "Authorize" button and paste token

#### 3. Create Invite Code
1. Under POST /invites, click "Try it out"
2. Enter invite data:
```json
{
  "email": "member@example.com",
  "phone": "+9876543210",
  "expiry_date": "2026-03-23T23:59:59"
}
```

#### 4. Register New Member
1. Under POST /auth/register, click "Try it out"
2. Use the invite code from response:
```json
{
  "invite_code": "ABC123XYZ456",
  "username": "member1",
  "password": "password123",
  "email": "member@example.com",
  "phone": "+9876543210",
  "address": "123 Main St",
  "monthly_amount": 500
}
```

---

### Database Troubleshooting

#### Connection Error
```
psycopg2.OperationalError: connection to server at "localhost" refused
```

**Solutions:**
1. Check PostgreSQL is running:
   ```bash
   # Windows
   pg_isready -h localhost
   ```

2. Verify DATABASE_URL in .env

3. Test connection:
   ```bash
   psql -U postgres -d charity_connect
   ```

#### Table Already Exists
Tables auto-create on first run. If you need to reset:
```python
# Run this in Python terminal
from app.models import Base
from app.database import engine

Base.metadata.drop_all(engine)  # Drop all
Base.metadata.create_all(engine)  # Recreate
```

---

### Development Workflow

#### Adding New Endpoint

1. **Create Schema** (`app/schemas/schemas.py`):
```python
class NewItemCreate(BaseModel):
    name: str
    value: int
```

2. **Create Service** (`app/services/new_service.py`):
```python
from sqlalchemy.orm import Session

class NewService:
    @staticmethod
    def create(db: Session, item_data):
        # Business logic
        pass
```

3. **Create Route** (`app/routes/new_routes.py`):
```python
from fastapi import APIRouter, Depends

router = APIRouter(prefix="/items", tags=["Items"])

@router.post("/", response_model=ItemResponse)
def create_item(data: ItemCreate, db: Session = Depends(get_db)):
    return NewService.create(db, data)
```

4. **Register Route** in `app/main.py`:
```python
from app.routes import new_router
app.include_router(new_router)
```

#### Running Tests
```bash
# Create tests/ directory with pytest
pytest tests/
```

---

### Common Tasks

#### Generate Member Code
```python
from app.utils import generate_member_code

last_code = "MEM003"
next_code = generate_member_code(last_code)  # Returns "MEM004"
```

#### Hash Password
```python
from app.utils import hash_password, verify_password

hashed = hash_password("mypassword")
is_valid = verify_password("mypassword", hashed)  # Returns True
```

#### Create JWT Token
```python
from app.utils import create_access_token
from datetime import timedelta

token = create_access_token(
    data={"sub": 1, "role": "member"},
    expires_delta=timedelta(hours=24)
)
```

---

### Environment Variables Reference

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | Required | PostgreSQL connection string |
| `SECRET_KEY` | Required | JWT signing key (generate random) |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | 60 | JWT token expiration |
| `DEBUG` | False | Debug mode (never True in production) |

---

### Project Commands

```bash
# Run with auto-reload on code changes
uvicorn app.main:app --reload

# Run with specific host/port
uvicorn app.main:app --host 0.0.0.0 --port 8000

# Run in production
uvicorn app.main:app --workers 4

# Check dependencies
pip list

# Update dependencies
pip install --upgrade -r requirements.txt

# Export requirements
pip freeze > requirements.txt
```

---

### Next Steps

1. **Database Initialization**: Run server once to auto-create tables
2. **Create Admin Account**: Use SQL or API to create first admin
3. **Test Endpoints**: Use Swagger UI at `/docs`
4. **Frontend Integration**: Get token, include in `Authorization: Bearer {token}` header
5. **Deploy**: Push to server and configure production `.env`

---

### Support

For issues or questions:
1. Check API docs at `/docs`
2. Review models in `app/models/models.py`
3. Check implementation guide: `IMPLEMENTATION.md`
4. Review route implementation in `app/routes/`

---

**Status**: Ready for development
**Last Updated**: February 23, 2026
