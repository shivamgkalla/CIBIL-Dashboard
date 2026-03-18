"""FastAPI application entry point."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
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

settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
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
def root():
    """Health check."""
    return {"status": "ok", "message": "System is healthy"}
