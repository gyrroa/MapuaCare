from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form, status
from sqlalchemy.orm import Session
from sqlalchemy import select, func, or_, delete, insert
from typing import Optional, Tuple, Any
from .. import models, schemas, database, auth
from ..services import embedding
from ..services import skill_extractor
import json
import os
import uuid
import mimetypes

# Supabase (Python v2)  ->  pip install supabase
from supabase import create_client, Client

router = APIRouter(prefix="/company", tags=["companies"])

# ---------- DB ----------
def get_db():
    db = database.SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ---------- Supabase config (Unchanged) ----------
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_ANON_KEY")
if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError("Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY/ANON in environment")

def _sb() -> Client:
    return create_client(SUPABASE_URL, SUPABASE_KEY)

BUCKET_NAME = os.getenv("SUPABASE_BUCKET", "files")
FOLDER_COMPANY_PHOTOS = os.getenv("SUPABASE_FOLDER_COMPANY_PHOTOS", "company_photos")
PHOTO_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}

def _split_public_url(url: str) -> Optional[Tuple[str, str]]:
    if not url:
        return None
    marker = "/storage/v1/object/public/"
    if marker not in url:
        return None
    after = url.split(marker, 1)[1]
    parts = after.split("/", 1)
    if len(parts) != 2:
        return None
    return parts[0], parts[1]

async def _upload_company_photo(user_id: int, photo: UploadFile) -> str:
    ext = os.path.splitext(photo.filename or "")[-1].lower()
    if ext not in PHOTO_EXTS:
        raise HTTPException(400, f"Unsupported image type. Allowed: {', '.join(sorted(PHOTO_EXTS))}")
    content_type = photo.content_type or mimetypes.guess_type(photo.filename or "")[0] or "application/octet-stream"
    object_path = f"{FOLDER_COMPANY_PHOTOS}/{user_id}/{uuid.uuid4().hex}{ext}"

    client = _sb()
    content = await photo.read()
    if not content:
        raise HTTPException(400, "Empty upload")

    client.storage.from_(BUCKET_NAME).upload(
        object_path,
        content,
        {
            "contentType": content_type,
            "cacheControl": "31536000",
        },
    )
    return client.storage.from_(BUCKET_NAME).get_public_url(object_path)

# --- THIS IS THE FIX ---
# This function was missing
def _delete_photo_url(photo_url: Optional[str]):
    if not photo_url:
        return
    parsed = _split_public_url(photo_url)
    if not parsed:
        return
    bucket, path = parsed
    try:
        _sb().storage.from_(bucket).remove([path])
    except Exception:
        # best-effort only
        pass
# --- END OF FIX ---

# --- NEW: Helper to map model to read schema, including email ---
def _map_profile_to_read(prof: models.CompanyProfile, email: str) -> schemas.CompanyProfileRead:
    """Helper to map model to read schema, including email."""
    return schemas.CompanyProfileRead(
        company_id=prof.company_id,
        email=email,
        company_name=prof.company_name,
        location=prof.location,
        photo_url=prof.photo_url,
    )

# ---------- Compose job text for embeddings (Unchanged) ----------
def _compose_job_text(db: Session, job: models.CompanyJob) -> str:
    skill_names = [
        s.preferred_label for s in db.query(models.Skill.preferred_label)
        .join(models.job_skills, models.job_skills.c.skill_id == models.Skill.skill_id)
        .filter(models.job_skills.c.job_id == job.job_id)
        .limit(5).all()
    ]
    skill_names = [sn[0] if isinstance(sn, tuple) else sn for sn in skill_names]
    parts = [
        (job.job_title or "").strip().lower(),
        (f"category: {job.job_category}" if job.job_category else "").lower(),
        (f"skills: {', '.join(skill_names)}" if skill_names else ""),
        (job.job_description or "").strip().lower()
    ]
    return "\n".join([p for p in parts if p])

# ---------------------------
# COMPANY PROFILE
# ---------------------------
@router.post(
    "/profile",
    response_model=schemas.CompanyProfileRead,
    summary="Create your company profile",
    description="Uses the authenticated user's ID; optional logo upload.",
    responses={400: {"description": "Already exists / invalid role"}, 404: {"description": "User not found"}},
)
async def create_company_profile(
    company_name: str = Form(...),
    location: Optional[str] = Form(None),
    photo: Any = File(None, description="optional company photo/logo"),
    db: Session = Depends(get_db),
    current: models.User = Depends(auth.get_current_user),
):
    uid = current.user_id
    if current.role != "company":
        raise HTTPException(400, "User is not a company")
    if db.get(models.CompanyProfile, uid):
        raise HTTPException(400, "Company profile already exists")

    photo_url: Optional[str] = None
    
    if isinstance(photo, UploadFile) and photo.filename:
        photo_url = await _upload_company_photo(uid, photo)

    prof = models.CompanyProfile(
        company_id=uid,
        company_name=company_name,
        location=location,
        photo_url=photo_url,
    )
    db.add(prof)
    db.commit()
    db.refresh(prof)
    
    return _map_profile_to_read(prof, current.email)

# READ ONE (public)
@router.get(
    "/profiles/{company_id}",
    response_model=schemas.CompanyProfileRead,
    summary="Get a company profile",
    responses={404: {"description": "Company profile not found"}},
)
def get_company_profile(company_id: int, db: Session = Depends(get_db)):
    result = db.query(models.CompanyProfile, models.User.email).join(
        models.User, models.User.user_id == models.CompanyProfile.company_id
    ).filter(models.CompanyProfile.company_id == company_id).first()
    
    if not result:
        raise HTTPException(404, "Company profile not found")
        
    prof, email = result
    return _map_profile_to_read(prof, email)

# READ ALL (public)
@router.get(
    "/profiles",
    response_model=schemas.PageCompany,
    summary="List company profiles",
    description="Search in company name with `q`. Returns company details.",
)
def list_company_profiles(
    db: Session = Depends(get_db),
    q: Optional[str] = Query(None, description="search in company name"),
    page: int = Query(1, ge=1),
    per_page: int = Query(10, ge=1, le=100),
):
    stmt = select(models.CompanyProfile, models.User.email).join(
        models.User, models.User.user_id == models.CompanyProfile.company_id
    )
    
    if q:
        like = f"%{q}%"
        stmt = stmt.where(models.CompanyProfile.company_name.ilike(like))
    
    total_stmt = select(func.count()).select_from(stmt.with_only_columns(models.CompanyProfile.company_id).subquery())
    total = db.scalar(total_stmt)
    
    results = db.execute(
        stmt.order_by(models.CompanyProfile.company_id.desc())
             .offset((page - 1) * per_page)
             .limit(per_page)
    ).all()

    items = [_map_profile_to_read(prof, email) for prof, email in results]

    return schemas.PageCompany(
        meta=schemas.PageMeta(page=page, per_page=per_page, total=total or 0),
        items=items,
    )

# UPDATE COMPANY PROFILE
@router.put(
    "/profiles/{company_id}",
    response_model=schemas.CompanyProfileRead,
    summary="Update your company profile",
    description="Optionally upload a new logo to Supabase or remove the existing one.",
    responses={403: {"description": "Forbidden"}, 404: {"description": "Company profile not found"}},
)
async def update_company_profile(
    company_id: int,
    company_name: Optional[str] = Form(None),
    location: Optional[str] = Form(None),
    photo: Any = File(None, description="optional new photo"),
    remove_photo: Optional[bool] = Form(False),
    db: Session = Depends(get_db),
    current: models.User = Depends(auth.get_current_user),
):
    if current.user_id != company_id:
        raise HTTPException(403, "You can only update your own company profile")
    prof = db.get(models.CompanyProfile, company_id)
    if not prof:
        raise HTTPException(404, "Company profile not found")

    if company_name is not None:
        prof.company_name = company_name
    if location is not None:
        prof.location = location

    if isinstance(photo, UploadFile) and photo.filename:
        new_url = await _upload_company_photo(company_id, photo)
        _delete_photo_url(prof.photo_url)
        prof.photo_url = new_url
    elif remove_photo:
        _delete_photo_url(prof.photo_url)
        prof.photo_url = None

    db.commit()
    db.refresh(prof)
    
    return _map_profile_to_read(prof, current.email)

# DELETE COMPANY PROFILE
@router.delete(
    "/profiles/{company_id}",
    status_code=204,
    summary="Delete your company profile",
    responses={403: {"description": "Forbidden"}, 404: {"description": "Company profile not found"}},
)
def delete_company_profile(
    company_id: int,
    db: Session = Depends(get_db),
    current: models.User = Depends(auth.get_current_user),
):
    if current.user_id != company_id:
        raise HTTPException(403, "You can only delete your own company profile")
    prof = db.get(models.CompanyProfile, company_id)
    if not prof:
        raise HTTPException(404, "Company profile not found")
    _delete_photo_url(prof.photo_url)
    db.delete(prof)
    db.commit()

# ---------------------------
# JOBS
# ---------------------------
@router.post(
    "/jobs",
    response_model=schemas.JobCreateResponse,
    summary="Create a job posting (Step 1: Suggest Skills)",
    description="Creates the job with its text details (title, description). It then extracts suggested skills from the CSV and returns them for review. The job's embedding is NOT calculated in this step.",
    responses={409: {"description": "A job with this title already exists"}},
)
def create_job(
    job: schemas.JobCreate,
    db: Session = Depends(get_db),
    current: models.User = Depends(auth.get_current_user),
):
    cid = current.user_id

    # Check for duplicate job title (case-insensitive) for this company
    existing_job = db.query(models.CompanyJob).filter(
        models.CompanyJob.company_id == cid,
        func.lower(models.CompanyJob.job_title) == func.lower(job.job_title)
    ).first()
    
    if existing_job:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A job with this exact title already exists for your company."
        )

    company_job = models.CompanyJob(
        company_id=cid,
        job_title=job.job_title,
        job_description=job.job_description,
        job_category=job.job_category,
    )
    db.add(company_job)
    db.commit()
    db.refresh(company_job)

    full_text = (job.job_title or "") + " " + (job.job_description or "")
    suggested_skills = skill_extractor.extract_skills_with_details(full_text)

    return schemas.JobCreateResponse(
        job_id=company_job.job_id,
        job_title=company_job.job_title,
        job_description=company_job.job_description,
        job_category=company_job.job_category,
        suggested_skills=suggested_skills
    )

@router.put(
    "/jobs/{job_id}/skills",
    response_model=schemas.CompanyJobRead,
    summary="Finalize job skills (Step 2: Save, Create, & Embed)",
    description="Provide the final, human-reviewed list of skill NAMES. This will search for existing skills or CREATE new ones if they don't exist. It then overwrites previous skills and triggers the job's embedding calculation.",
    responses={403: {"description": "Forbidden"}, 404: {"description": "Job not found"}},
)
def update_job_skills(
    job_id: int,
    skills_data: schemas.JobSkillUpdate,
    db: Session = Depends(get_db),
    current: models.User = Depends(auth.get_current_user),
):
    job = db.get(models.CompanyJob, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if job.company_id != current.user_id:
        raise HTTPException(403, "You can only update your own company's job")

    # --- 1. Clear old skills ---
    delete_stmt = delete(models.job_skills).where(
        models.job_skills.c.job_id == job_id
    )
    db.execute(delete_stmt)
    
    final_skill_ids = []
    
    # 2. Loop through submitted names
    for skill_name in set(skills_data.skill_names): # Use set() to avoid duplicates
        if not skill_name:
            continue
            
        skill_name_lower = skill_name.lower()
        
        # 3. Check if skill exists (as preferred_label OR altLabel)
        search_alt_label = f"%;{skill_name_lower};%"
        
        db_skill = db.query(models.Skill).filter(
            or_(
                func.lower(models.Skill.preferred_label) == skill_name_lower,
                models.Skill.alt_labels.ilike(search_alt_label)
            )
        ).first()
        
        if db_skill:
            # 4a. If found, use its ID
            final_skill_ids.append(db_skill.skill_id)
        else:
            # 4b. If not found, CREATE IT!
            new_skill = models.Skill(
                preferred_label=skill_name.strip().capitalize(),
                concept_uri=f"local:{skill_name.lower().strip().replace(' ', '-')}",
                alt_labels=f";{skill_name_lower};"
            )
            db.add(new_skill)
            db.flush()
            final_skill_ids.append(new_skill.skill_id)

    # 5. Add all the final, normalized skill links
    if final_skill_ids:
        insert_values = [
            {"job_id": job_id, "skill_id": sid, "required": True} 
            for sid in set(final_skill_ids)
        ]
        insert_stmt = insert(models.job_skills).values(insert_values)
        db.execute(insert_stmt)

    # 6. (Re)calculate and save embedding
    composed = _compose_job_text(db, job)
    job.job_embedding_vector = json.dumps(embedding.get_embedding(composed))

    # 7. Commit everything
    db.commit()
    db.refresh(job)
    return job

@router.get(
    "/jobs/{job_id}",
    response_model=schemas.CompanyJobRead,
    summary="Get a job posting",
    responses={404: {"description": "Job not found"}},
)
def get_job(job_id: int, db: Session = Depends(get_db)):
    job = db.get(models.CompanyJob, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return job

@router.get(
    "/jobs",
    response_model=schemas.PageJob,
    summary="List jobs with filters",
    description="Filter by `company_id` and/or `category`, and full-text search with `q`.",
)
def list_jobs(
    db: Session = Depends(get_db),
    q: Optional[str] = Query(None, description="search in title/description/category"),
    category: Optional[str] = None,
    company_id: Optional[int] = Query(None, description="filter by company_id"),
    page: int = Query(1, ge=1),
    per_page: int = Query(10, ge=1, le=100),
):
    stmt = select(models.CompanyJob)

    if category:
        stmt = stmt.where(models.CompanyJob.job_category == category)
    if company_id is not None:
        stmt = stmt.where(models.CompanyJob.company_id == company_id)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(
            models.CompanyJob.job_title.ilike(like),
            models.CompanyJob.job_description.ilike(like),
            models.CompanyJob.job_category.ilike(like),
        ))

    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    items = db.execute(
        stmt.order_by(models.CompanyJob.job_id.desc())
             .offset((page - 1) * per_page)
             .limit(per_page)
    ).scalars().all()

    return schemas.PageJob(
        meta=schemas.PageMeta(page=page, per_page=per_page, total=total or 0),
        items=items,
    )

@router.put(
    "/jobs/{job_id}",
    response_model=schemas.CompanyJobRead,
    summary="Update a job's text details (e.g., title, description)",
    description="Updates a job's text fields (title, description, category). This will re-calculate the embedding. **Note: This endpoint does not update skills.** Use the `PUT /company/jobs/{job_id}/skills` endpoint for that.",
    responses={403: {"description": "Forbidden"}, 404: {"description": "Job not found"}},
)
def update_job(
    job_id: int,
    patch: schemas.JobTextUpdate,
    db: Session = Depends(get_db),
    current: models.User = Depends(auth.get_current_user),
):
    job = db.get(models.CompanyJob, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if job.company_id != current.user_id:
        raise HTTPException(403, "You can only update your own company's job")

    changed = False
    for f in ["job_title", "job_description", "job_category"]:
        val = getattr(patch, f, None)
        if val is not None:
            setattr(job, f, val)
            if f in ("job_title", "job_description", "job_category"):
                changed = True

    if changed:
        composed = _compose_job_text(db, job)
        job.job_embedding_vector = json.dumps(embedding.get_embedding(composed))

    db.commit()
    db.refresh(job)
    return job

@router.delete(
    "/jobs/{job_id}",
    status_code=204,
    summary="Delete a job posting",
    responses={403: {"description": "Forbidden"}, 404: {"description": "Job not found"}},
)
def delete_job(
    job_id: int,
    db: Session = Depends(get_db),
    current: models.User = Depends(auth.get_current_user),
):
    job = db.get(models.CompanyJob, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if job.company_id != current.user_id:
        raise HTTPException(403, "You can only delete your own company's job")
    db.delete(job)
    db.commit()

@router.get(
    "/my_jobs",
    response_model=schemas.PageJob,
    summary="List my company's jobs",
    description="Uses the authenticated user's ID; pagination with `page` and `per_page`.",
)
def list_my_jobs(
    db: Session = Depends(get_db),
    current: models.User = Depends(auth.get_current_user),
    page: int = Query(1, ge=1),
    per_page: int = Query(10, ge=1, le=100),
):
    stmt = select(models.CompanyJob).where(models.CompanyJob.company_id == current.user_id)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    items = db.execute(
        stmt.order_by(models.CompanyJob.job_id.desc())
             .offset((page - 1) * per_page)
             .limit(per_page)
    ).scalars().all()
    return schemas.PageJob(
        meta=schemas.PageMeta(page=page, per_page=per_page, total=total or 0),
        items=items,
    )

@router.get(
    "/job/{job_id}/applicants",
    response_model=schemas.PageCandidate,
    summary="List candidates who applied to a job",
    description="Returns the candidates who applied to a specific job.",
)
def get_job_applicants(
    job_id: int,
    db: Session = Depends(get_db),
    current: models.User = Depends(auth.get_current_user),
    page: int = Query(1, ge=1),
    per_page: int = Query(10, ge=1, le=100),
):
    job = db.get(models.CompanyJob, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if job.company_id != current.user_id:
        raise HTTPException(403, "You can only see applicants for your own jobs")

    stmt = select(models.CandidateProfile).join(
        models.JobApplication, models.JobApplication.candidate_id == models.CandidateProfile.candidate_id
    ).where(models.JobApplication.job_id == job_id)

    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    items = db.execute(
        stmt.order_by(models.CandidateProfile.candidate_id.desc())
             .offset((page - 1) * per_page)
             .limit(per_page)
    ).scalars().all()

    return schemas.PageCandidate(
        meta=schemas.PageMeta(page=page, per_page=per_page, total=total or 0),
        items=items,
    )