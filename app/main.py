from fastapi import Depends, FastAPI
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.v1.auth import router as auth_router
from app.api.v1.tickets import router as tickets_router

app = FastAPI(title="SupportDesk API")
app.include_router(auth_router)
app.include_router(tickets_router)


@app.get("/health")
def health_check(db: Session = Depends(get_db)) -> dict[str, str]:
    db.execute(text("SELECT 1"))
    return {"status": "ok"}
