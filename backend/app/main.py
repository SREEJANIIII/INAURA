from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .core.config import get_settings
from .api.v1.router import api_router

app = FastAPI(
    title="INAURA API",
    description="Bridging skills to industry.",
    version="0.1.0",
)

# CORS — include configured frontend URL + local dev origins
settings = get_settings()
origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    settings.frontend_url,
]
# dedupe
origins = list(dict.fromkeys([o for o in origins if o]))

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(api_router)


@app.get("/api/v1/health")
def health_check():
    return {
        "status": "ok",
        "service": "INAURA backend",
        "message": "Bridging skills to industry — backend is running.",
    }


@app.get("/")
def root():
    return {
        "service": "INAURA backend",
        "docs": "/docs",
        "health": "/api/v1/health",
    }
