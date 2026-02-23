from fastapi import FastAPI

app = FastAPI(title="Charity Connect API")

@app.get("/")
def root():
    return {"message": "Charity Connect Backend Running"}
