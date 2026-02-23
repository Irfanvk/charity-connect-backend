from fastapi import FastAPI
from sqlalchemy import text
from app.database import engine

app = FastAPI(title="Charity Connect API")

@app.get("/")
def root():
    return {"message": "Charity Connect Backend Running"}

@app.get("/test-db")
def test_db():
    with engine.connect() as connection:
        result = connection.execute(text("SELECT 1"))
        return {"database_status": "connected", "result": result.scalar()}
