from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from .database import Base, engine
from .routes import companies, users, candidates, matching, skills
from .config import settings
import os

Base.metadata.create_all(bind=engine)

# ensure uploads root exists for static serving
os.makedirs("uploads", exist_ok=True)

app = FastAPI(title=settings.PROJECT_NAME, version=settings.VERSION)

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

@app.get("/")
def root():
    return {"message": "CARE Backend API is running"}
