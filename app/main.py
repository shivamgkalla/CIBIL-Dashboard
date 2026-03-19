"""FastAPI application entry point."""

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.database import get_db

from app.core.config import get_settings
from app.core.rate_limit import limiter
from app.routers import auth_router, admin_router, user_router
from app.routers.upload_router import router as upload_router
from app.routers.customer_router import router as customer_router
from app.routers.saved_filter_router import router as saved_filter_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan (startup/shutdown)."""
    yield


app = FastAPI(
    title="CIBIL Bureau",
    version="1.0.0",
    lifespan=lifespan,
)

# Attach rate limiter state and register the 429 error handler.
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-New-Token"],
)

app.include_router(auth_router.router)
app.include_router(admin_router.router)
app.include_router(user_router.router)
app.include_router(upload_router)
app.include_router(customer_router)
app.include_router(saved_filter_router)


@app.get("/", tags=["Health"])
def root(db: Session = Depends(get_db)):
    """Health check with database connectivity verification."""
    try:
        db.execute(text("SELECT 1"))
        return {"status": "ok", "message": "System is healthy"}
    except Exception:
        return {"status": "degraded", "message": "Database unreachable"}
