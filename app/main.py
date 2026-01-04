from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import engine, Base
from app import models  # Import models to ensure they're registered
from app.routers import host_auth, client_auth, cars, payment_methods, media

app = FastAPI(
    title="Car Rental API",
    description="Backend API for car rental platform",
    version="1.0.0"
)


@app.on_event("startup")
async def startup_event():
    """Create database tables on startup"""
    Base.metadata.create_all(bind=engine)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8081",  # Expo default
        "http://localhost:19000",  # Expo web
        "http://localhost:19006",  # Expo web alternative
        "exp://localhost:8081",   # Expo client
        "*"  # Allow all for development - RESTRICT IN PRODUCTION
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(host_auth.router, prefix="/api/v1", tags=["Host Auth"])
app.include_router(client_auth.router, prefix="/api/v1", tags=["Client Auth"])
app.include_router(cars.router, prefix="/api/v1", tags=["Car Management"])
app.include_router(payment_methods.router, prefix="/api/v1", tags=["Payment Methods"])
app.include_router(media.router, prefix="/api/v1", tags=["Media Upload"])


@app.get("/")
async def root():
    return {"message": "Car Rental API"}


@app.get("/health")
async def health_check():
    return {"status": "healthy"}


