from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from .database import Base, engine
from .routes import companies, users, candidates, matching, skills
from .config import settings
import os

Base.metadata.create_all(bind=engine)

os.makedirs("uploads", exist_ok=True)

tags_metadata = [
    {"name": "users", "description": "Register, login, and obtain bearer tokens."},
    {"name": "candidates", "description": "Candidate profile CRUD and CV upload."},
    {"name": "companies", "description": "Company profile and job postings (logo upload supported)."},
    {"name": "skills", "description": "Skill catalog (typically ESCO-derived)."},
    {"name": "matching", "description": "Semantic matching and recommendations between candidates and jobs."},
]

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description=(
        "CARE API\n\n"
        "**Auth**: Click **Authorize** and use `Bearer <access_token>` from `/users/login`.\n"
        "**Roles**: `candidate` or `company`.\n"
        "IDs derived from the bearer token are not accepted from clients on mutation endpoints."
    ),
    openapi_tags=tags_metadata,
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o for o in settings.CORS_ORIGINS if o],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve files saved under /uploads via /static/*
app.mount("/static", StaticFiles(directory="uploads"), name="static")

app.include_router(users)
app.include_router(candidates)
app.include_router(companies)
app.include_router(skills)
app.include_router(matching)

@app.get("/", summary="Health check", tags=["users"])
def root():
    return {"message": "CARE Backend API is running"}
