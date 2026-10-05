from fastapi import FastAPI

from app.api.v1.auth import router as auth_router

app = FastAPI(title="SupportDesk API")
app.include_router(auth_router)


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}
