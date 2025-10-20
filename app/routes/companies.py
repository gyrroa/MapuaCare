from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form
from sqlalchemy.orm import Session
from sqlalchemy import select, func, or_
from typing import Optional, Tuple
from .. import models, schemas, database, auth
from ..services import embedding
import json
import os
import uuid
import mimetypes

# Supabase (Python v2)  ->  pip install supabase
from supabase import create_client, Client

router = APIRouter(prefix="/company", tags=["companies"])

# ---------- DB ----------
def get_db():
    db = database.SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ---------- Supabase config ----------
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_ANON_KEY")
if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError("Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY/ANON in environment")

def _sb() -> Client:
    return create_client(SUPABASE_URL, SUPABASE_KEY)

# Single bucket "files", with folder prefixes
BUCKET_NAME = os.getenv("SUPABASE_BUCKET", "files")
FOLDER_COMPANY_PHOTOS = os.getenv("SUPABASE_FOLDER_COMPANY_PHOTOS", "company_photos")

PHOTO_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}

def _split_public_url(url: str) -> Optional[Tuple[str, str]]:
    """
    Given a public URL like:
      https://<project>.supabase.co/storage/v1/object/public/<bucket>/<path>
    return (bucket, path)
    """
    if not url:
        return None
    marker = "/storage/v1/object/public/"
    if marker not in url:
        return None
    after = url.split(marker, 1)[1]  # "bucket/path..."
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
            # no "upsert" (unique path)
        },
    )
    return client.storage.from_(BUCKET_NAME).get_public_url(object_path)

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

# ---------- Compose job text for embeddings ----------
def _compose_job_text(db: Session, job: models.CompanyJob) -> str:
    skill_names = [
        s.preferred_label for s in db.query(models.Skill.preferred_label)
        .join(models.JobSkill, models.JobSkill.skill_id == models.Skill.skill_id)
        .filter(models.JobSkill.job_id == job.job_id)
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
# CREATE COMPANY PROFILE
# ---------------------------
@router.post(
    "/profile",
    response_model=schemas.CompanyProfileRead,
    summary="Create your company profile",
    description="Uses the authenticated user's ID; optional logo upload (png/jpg/jpeg/gif/webp) stored in Supabase.",
    responses={400: {"description": "Already exists / invalid role"}, 404: {"description": "User not found"}},
)
async def create_company_profile(
    company_name: str = Form(...),
    photo: Optional[UploadFile] = File(None, description="optional company photo/logo"),
    db: Session = Depends(get_db),
    current: models.User = Depends(auth.get_current_user),
):
    uid = current.user_id
    user = db.get(models.User, uid)
    if not user:
        raise HTTPException(404, "User not found")
    if user.role and user.role != "company":
        raise HTTPException(400, "User is not a company")
    if db.get(models.CompanyProfile, uid):
        raise HTTPException(400, "Company profile already exists")

    photo_url: Optional[str] = None
    if photo:
        photo_url = await _upload_company_photo(uid, photo)

    prof = models.CompanyProfile(
        company_id=uid,
        company_name=company_name,
        photo_url=photo_url,
    )
    db.add(prof)
    db.commit()
    db.refresh(prof)
    return prof

# READ ONE (public)
@router.get(
    "/profiles/{company_id}",
    response_model=schemas.CompanyProfileRead,
    summary="Get a company profile",
    responses={404: {"description": "Company profile not found"}},
)
def get_company_profile(company_id: int, db: Session = Depends(get_db)):
    prof = db.get(models.CompanyProfile, company_id)
    if not prof:
        raise HTTPException(404, "Company profile not found")
    return prof

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
    photo: Optional[UploadFile] = File(None, description="optional new photo"),
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

    if photo:
        new_url = await _upload_company_photo(company_id, photo)
        _delete_photo_url(prof.photo_url)
        prof.photo_url = new_url
    elif remove_photo:
        _delete_photo_url(prof.photo_url)
        prof.photo_url = None

    db.commit()
    db.refresh(prof)
    return prof

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
    response_model=schemas.CompanyJobRead,
    summary="Create a job posting",
    description="Skills must be valid Skill IDs. Embedding is computed automatically.",
)
def create_job(
    job: schemas.CompanyJobCreate,
    db: Session = Depends(get_db),
    current: models.User = Depends(auth.get_current_user),
):
    cid = current.user_id
    company_job = models.CompanyJob(
        company_id=cid,
        job_title=job.job_title,
        job_description=job.job_description,
        job_category=job.job_category,
    )
    db.add(company_job)
    db.flush()

    if job.skills:
        valid_ids = [sid for (sid,) in db.execute(
            select(models.Skill.skill_id).where(models.Skill.skill_id.in_(job.skills))
        ).all()]
        for sid in valid_ids:
            db.add(models.JobSkill(job_id=company_job.job_id, skill_id=sid, required=True))

    composed = _compose_job_text(db, company_job)
    company_job.job_embedding_vector = json.dumps(embedding.get_embedding(composed))

    db.commit()
    db.refresh(company_job)
    return company_job

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
    summary="Update a job posting",
    responses={403: {"description": "Forbidden"}, 404: {"description": "Job not found"}},
)
def update_job(
    job_id: int,
    patch: schemas.CompanyJobUpdate,
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
        val = getattr(patch, f)
        if val is not None:
            setattr(job, f, val)
            if f in ("job_title", "job_description", "job_category"):
                changed = True

    if patch.skills is not None:
        db.query(models.JobSkill).filter(models.JobSkill.job_id == job_id).delete()
        if patch.skills:
            valid_ids = [sid for (sid,) in db.execute(
                select(models.Skill.skill_id).where(models.Skill.skill_id.in_(patch.skills))
            ).all()]
            for sid in valid_ids:
                db.add(models.JobSkill(job_id=job.job_id, skill_id=sid, required=True))
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
