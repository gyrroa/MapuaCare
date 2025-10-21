from fastapi import APIRouter, Depends, UploadFile, File, HTTPException, Query, Form
from sqlalchemy.orm import Session
from sqlalchemy import select, func, or_
from typing import Optional, List, Tuple
from .. import models, schemas, database, auth
from ..services import cv_parser, embedding, skill_extractor
import json
import os
import mimetypes
import tempfile
import uuid

# Supabase (Python v2)  ->  pip install supabase
from supabase import create_client, Client

router = APIRouter(prefix="/candidate", tags=["candidates"])

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
FOLDER_CANDIDATE_PHOTOS = os.getenv("SUPABASE_FOLDER_CANDIDATE_PHOTOS", "candidate_photos")
FOLDER_CV = os.getenv("SUPABASE_FOLDER_CV", "cv")

PHOTO_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
CV_EXTS = {".pdf", ".docx"}

def _split_public_url(url: str) -> Optional[Tuple[str, str]]:
    """
    Convert a public URL like:
      https://<ref>.supabase.co/storage/v1/object/public/<bucket>/<path>
    -> (bucket, path)
    """
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

async def _upload_to_supabase(object_path: str, file: UploadFile) -> str:
    content = await file.read()
    if not content:
        raise HTTPException(400, "Empty file upload")
    ctype = file.content_type or mimetypes.guess_type(file.filename or "")[0] or "application/octet-stream"

    client = _sb()
    client.storage.from_(BUCKET_NAME).upload(
        object_path,
        content,
        {
            "contentType": ctype,
            "cacheControl": "31536000",  # 1 year
            # no "upsert" (we use unique object paths)
        },
    )
    return client.storage.from_(BUCKET_NAME).get_public_url(object_path)

def _delete_public_url(url: Optional[str]):
    if not url:
        return
    parsed = _split_public_url(url)
    if not parsed:
        return
    bucket, path = parsed
    try:
        _sb().storage.from_(bucket).remove([path])
    except Exception:
        # best-effort only
        pass

# ---------- helpers ----------
def _slug(s: str) -> str:
    return "-".join("".join(ch for ch in (s or "").lower().strip() if ch.isalnum() or ch.isspace()).split())

def _get_or_create_skill_by_name(db: Session, name: str) -> int:
    name = (name or "").strip()
    if not name:
        raise HTTPException(400, "Skill name cannot be empty")
    skill = db.query(models.Skill).filter(models.Skill.preferred_label.ilike(name)).first()
    if skill:
        return skill.skill_id
    concept_uri = f"local:{_slug(name)}"
    skill = models.Skill(concept_uri=concept_uri, preferred_label=name, alt_labels=None)
    db.add(skill)
    db.flush()
    return skill.skill_id

def _link_candidate_skills_from_names(db: Session, candidate_id: int, names: Optional[List[str]]):
    if names is None:
        return
    db.query(models.CandidateSkill).filter(models.CandidateSkill.candidate_id == candidate_id).delete()
    for name in names or []:
        sid = _get_or_create_skill_by_name(db, name)
        db.add(models.CandidateSkill(candidate_id=candidate_id, skill_id=sid))

def _skill_names_for_candidate(db: Session, candidate_id: int) -> list[str]:
    rows = (
        db.query(models.Skill.preferred_label)
        .join(models.CandidateSkill, models.CandidateSkill.skill_id == models.Skill.skill_id)
        .filter(models.CandidateSkill.candidate_id == candidate_id)
        .all()
    )
    return [r[0] for r in rows]

def _parse_skills_form(skills_raw: Optional[str]) -> Optional[List[str]]:
    if skills_raw is None or skills_raw == "":
        return None
    try:
        data = json.loads(skills_raw)
        if isinstance(data, list):
            return [str(x) for x in data]
    except Exception:
        pass
    # fallback: comma-separated
    return [p.strip() for p in str(skills_raw).split(",") if p.strip()]

# ---------- endpoints ----------

# 1) CV Upload (extract only)
@router.post(
    "/upload_cv",
    summary="Upload CV (PDF/DOCX) and extract text + naive skills",
    description="Returns raw text and a simple skill hit list based on ESCO labels.",
)
async def upload_cv(file: UploadFile = File(...)):
    ext = os.path.splitext(file.filename or "")[-1].lower()
    if ext not in CV_EXTS:
        raise HTTPException(400, "Unsupported file type (pdf/docx only)")

    with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name
    try:
        if ext == ".pdf":
            text = cv_parser.extract_text_from_pdf(tmp_path)
        else:
            text = cv_parser.extract_text_from_docx(tmp_path)
    finally:
        try:
            os.remove(tmp_path)
        except Exception:
            pass
    skills = skill_extractor.extract_skills_from_text(text)
    return {"resume_text": text, "skills_found": skills}

# 2) Create profile — multipart + Supabase uploads
@router.post(
    "/profile",
    response_model=schemas.CandidateProfileRead,
    summary="Create your candidate profile (optional photo & CV to Supabase)",
    description="Uses the authenticated user's ID; submit as multipart/form-data.",
    responses={400: {"description": "Profile already exists"}, 404: {"description": "User not found"}},
)
async def create_profile(
    full_name: str = Form(...),
    contact_number: Optional[str] = Form(None),
    college_program: Optional[str] = Form(None),
    batch_year: Optional[int] = Form(None),
    resume_text: Optional[str] = Form(None),
    skills: Optional[str] = Form(None, description='JSON list or comma-separated, e.g. ["Python","FastAPI"] or "Python, FastAPI"'),
    photo: Optional[UploadFile] = File(None, description="jpg/jpeg/png/webp"),
    cv_file: Optional[UploadFile] = File(None, description="pdf/docx"),
    db: Session = Depends(get_db),
    current: models.User = Depends(auth.get_current_user),
):
    uid = current.user_id
    if not db.get(models.User, uid):
        raise HTTPException(404, "User not found")
    if db.get(models.CandidateProfile, uid):
        raise HTTPException(400, "Candidate profile already exists")

    # If CV uploaded, extract text first
    extracted_text = None
    if cv_file:
        ext = (os.path.splitext(cv_file.filename or "")[-1] or "").lower()
        if ext not in CV_EXTS:
            raise HTTPException(400, "Unsupported CV file type (pdf/docx only)")
        with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
            cv_file.file.seek(0)
            tmp.write(cv_file.file.read())
            tmp_path = tmp.name
        try:
            extracted_text = cv_parser.extract_text_from_pdf(tmp_path) if ext == ".pdf" else cv_parser.extract_text_from_docx(tmp_path)
        finally:
            try:
                os.remove(tmp_path)
            except Exception:
                pass

    final_resume_text = extracted_text or resume_text

    candidate = models.CandidateProfile(
        candidate_id=uid,
        full_name=full_name,
        contact_number=contact_number,
        college_program=college_program,
        batch_year=batch_year,
        resume_text=final_resume_text,
        embedding_vector=json.dumps(embedding.get_embedding(final_resume_text)) if final_resume_text else None,
    )
    db.add(candidate)
    db.flush()  # ensure candidate row exists

    # Upload photo
    if photo:
        ext = os.path.splitext(photo.filename or "")[-1].lower()
        if ext not in PHOTO_EXTS:
            raise HTTPException(400, "Unsupported image type")
        object_path = f"{FOLDER_CANDIDATE_PHOTOS}/{uid}/{uuid.uuid4().hex}{ext}"
        candidate.photo_url = await _upload_to_supabase(object_path, photo)

    # Upload original CV file
    if cv_file:
        ext = os.path.splitext(cv_file.filename or "")[-1].lower()
        cv_file.file.seek(0)
        object_path = f"{FOLDER_CV}/{uid}/{uuid.uuid4().hex}{ext}"
        candidate.resume_file_url = await _upload_to_supabase(object_path, cv_file)

    # Skills
    parsed_skills = _parse_skills_form(skills)
    if parsed_skills:
        _link_candidate_skills_from_names(db, uid, parsed_skills)

    db.commit()
    db.refresh(candidate)

    return schemas.CandidateProfileRead(
        candidate_id=candidate.candidate_id,
        full_name=candidate.full_name,
        contact_number=candidate.contact_number,
        college_program=candidate.college_program,
        batch_year=candidate.batch_year,
        resume_text=candidate.resume_text,
        photo_url=candidate.photo_url,
        resume_file_url=candidate.resume_file_url,
        skill_names=_skill_names_for_candidate(db, candidate.candidate_id),
    )

# 3) Get one (returns skill_names + urls)
@router.get(
    "/profiles/{candidate_id}",
    response_model=schemas.CandidateProfileRead,
    summary="Get a candidate profile",
    description="Public read.",
    responses={404: {"description": "Candidate not found"}},
)
def get_profile(candidate_id: int, db: Session = Depends(get_db)):
    c = db.get(models.CandidateProfile, candidate_id)
    if not c:
        raise HTTPException(404, "Candidate not found")
    return schemas.CandidateProfileRead(
        candidate_id=c.candidate_id,
        full_name=c.full_name,
        contact_number=c.contact_number,
        college_program=c.college_program,
        batch_year=c.batch_year,
        resume_text=c.resume_text,
        photo_url=c.photo_url,
        resume_file_url=c.resume_file_url,
        skill_names=_skill_names_for_candidate(db, c.candidate_id),
    )

# 4) List with search/pagination
@router.get(
    "/profiles",
    response_model=schemas.PageCandidate,
    summary="List candidate profiles",
    description="Search in name/resume with `q`. Returns skill names and file URLs for each candidate.",
)
def list_profiles(
    db: Session = Depends(get_db),
    q: Optional[str] = Query(None, description="search in name/resume"),
    page: int = Query(1, ge=1),
    per_page: int = Query(10, ge=1, le=100),
):
    stmt = select(models.CandidateProfile)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(
            models.CandidateProfile.full_name.ilike(like),
            models.CandidateProfile.resume_text.ilike(like)
        ))
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    raw_items = db.execute(
        stmt.order_by(models.CandidateProfile.candidate_id.desc())
            .offset((page - 1) * per_page)
            .limit(per_page)
    ).scalars().all()

    items = [
        schemas.CandidateProfileRead(
            candidate_id=c.candidate_id,
            full_name=c.full_name,
            contact_number=c.contact_number,
            college_program=c.college_program,
            batch_year=c.batch_year,
            resume_text=c.resume_text,
            photo_url=c.photo_url,
            resume_file_url=c.resume_file_url,
            skill_names=_skill_names_for_candidate(db, c.candidate_id),
        ) for c in raw_items
    ]

    return schemas.PageCandidate(
        meta=schemas.PageMeta(page=page, per_page=per_page, total=total or 0),
        items=items,
    )

# 5) Update (auth: owner only) — multipart + Supabase
@router.put(
    "/profiles/{candidate_id}",
    response_model=schemas.CandidateProfileRead,
    summary="Update your candidate profile (optional photo & CV to Supabase)",
    responses={403: {"description": "Forbidden"}, 404: {"description": "Candidate not found"}},
)
async def update_profile(
    candidate_id: int,
    full_name: Optional[str] = Form(None),
    contact_number: Optional[str] = Form(None),
    college_program: Optional[str] = Form(None),
    batch_year: Optional[int] = Form(None),
    resume_text: Optional[str] = Form(None),
    skills: Optional[str] = Form(None, description="JSON list or comma-separated"),
    photo: Optional[UploadFile] = File(None),
    cv_file: Optional[UploadFile] = File(None),
    remove_photo: Optional[bool] = Form(False),
    remove_cv: Optional[bool] = Form(False),
    db: Session = Depends(get_db),
    current: models.User = Depends(auth.get_current_user),
):
    if current.user_id != candidate_id:
        raise HTTPException(403, "You can only update your own profile")
    c = db.get(models.CandidateProfile, candidate_id)
    if not c:
        raise HTTPException(404, "Candidate not found")

    changed_resume = False

    # Update scalars
    for field, val in [
        ("full_name", full_name),
        ("contact_number", contact_number),
        ("college_program", college_program),
        ("batch_year", batch_year),
        ("resume_text", resume_text),
    ]:
        if val is not None:
            setattr(c, field, val)
            if field == "resume_text":
                changed_resume = True

    # New CV uploaded? parse + upload original
    if cv_file:
        ext = os.path.splitext(cv_file.filename or "")[-1].lower()
        if ext not in CV_EXTS:
            raise HTTPException(400, "Unsupported CV file type (pdf/docx only)")

        # Upload original to Supabase
        cv_file.file.seek(0)
        object_path = f"{FOLDER_CV}/{candidate_id}/{uuid.uuid4().hex}{ext}"
        new_cv_url = await _upload_to_supabase(object_path, cv_file)

        # Extract text to replace resume_text
        with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
            cv_file.file.seek(0)
            tmp.write(cv_file.file.read())
            tmp_path = tmp.name
        try:
            extracted_text = cv_parser.extract_text_from_pdf(tmp_path) if ext == ".pdf" else cv_parser.extract_text_from_docx(tmp_path)
        finally:
            try:
                os.remove(tmp_path)
            except Exception:
                pass

        if c.resume_file_url:
            _delete_public_url(c.resume_file_url)
        c.resume_file_url = new_cv_url
        c.resume_text = extracted_text
        changed_resume = True
    elif remove_cv and c.resume_file_url:
        _delete_public_url(c.resume_file_url)
        c.resume_file_url = None

    # Photo
    if photo:
        ext = os.path.splitext(photo.filename or "")[-1].lower()
        if ext not in PHOTO_EXTS:
            raise HTTPException(400, "Unsupported image type")
        object_path = f"{FOLDER_CANDIDATE_PHOTOS}/{candidate_id}/{uuid.uuid4().hex}{ext}"
        new_photo_url = await _upload_to_supabase(object_path, photo)
        if c.photo_url:
            _delete_public_url(c.photo_url)
        c.photo_url = new_photo_url
    elif remove_photo and c.photo_url:
        _delete_public_url(c.photo_url)
        c.photo_url = None

    # Recompute embedding if resume changed
    if changed_resume:
        c.embedding_vector = json.dumps(embedding.get_embedding(c.resume_text)) if c.resume_text else None

    # Skills
    if skills is not None:
        names = _parse_skills_form(skills)
        _link_candidate_skills_from_names(db, candidate_id, names or [])

    db.commit()
    db.refresh(c)
    return schemas.CandidateProfileRead(
        candidate_id=c.candidate_id,
        full_name=c.full_name,
        contact_number=c.contact_number,
        college_program=c.college_program,
        batch_year=c.batch_year,
        resume_text=c.resume_text,
        photo_url=c.photo_url,
        resume_file_url=c.resume_file_url,
        skill_names=_skill_names_for_candidate(db, c.candidate_id),
    )

# 6) Delete (auth: owner only) — also purge Storage files (best effort)
@router.delete(
    "/profiles/{candidate_id}",
    status_code=204,
    summary="Delete your candidate profile",
    responses={403: {"description": "Forbidden"}, 404: {"description": "Candidate not found"}},
)
def delete_profile(
    candidate_id: int,
    db: Session = Depends(get_db),
    current: models.User = Depends(auth.get_current_user),
):
    if current.user_id != candidate_id:
        raise HTTPException(403, "You can only delete your own profile")
    c = db.get(models.CandidateProfile, candidate_id)
    if not c:
        raise HTTPException(404, "Candidate not found")

    _delete_public_url(c.photo_url)
    _delete_public_url(c.resume_file_url)

    db.delete(c)
    db.commit()

# NEW: Endpoint to allow candidates to apply or unapply to a job
@router.post(
    "/apply_job/{job_id}",
    summary="Apply or unapply to a job",
    description="A candidate can apply or unapply to a job. Returns status if applied or unapplied.",
)
async def apply_job(
    job_id: int,
    db: Session = Depends(get_db),
    current: models.User = Depends(auth.get_current_user),
):
    # Get the candidate profile
    candidate_profile = db.get(models.CandidateProfile, current.user_id)
    if not candidate_profile:
        raise HTTPException(404, "Candidate profile not found")

    # Check if the candidate is already applied to the job
    application = db.query(models.JobApplication).filter(
        models.JobApplication.candidate_id == candidate_profile.candidate_id,
        models.JobApplication.job_id == job_id,
    ).first()

    if application:
        # If already applied, unapply by deleting the application
        db.delete(application)
        db.commit()
        return {"status": "unapplied"}
    else:
        # If not applied yet, apply to the job by creating a new application
        new_application = models.JobApplication(
            candidate_id=candidate_profile.candidate_id,
            job_id=job_id,
        )
        db.add(new_application)
        db.commit()
        return {"status": "applied"}
    
# NEW: Endpoint to list the jobs the candidate has applied to
@router.get(
    "/my_applied_jobs",
    response_model=schemas.PageJob,
    summary="List jobs the candidate has applied to",
    description="Returns the jobs a candidate has applied to.",
)
def get_applied_jobs(
    db: Session = Depends(get_db),
    current: models.User = Depends(auth.get_current_user),
    page: int = Query(1, ge=1),
    per_page: int = Query(10, ge=1, le=100),
):
    # Get the candidate profile
    candidate_profile = db.get(models.CandidateProfile, current.user_id)
    if not candidate_profile:
        raise HTTPException(404, "Candidate profile not found")

    # Query jobs applied to by the candidate
    stmt = select(models.CompanyJob).join(
        models.JobApplication, models.JobApplication.job_id == models.CompanyJob.job_id
    ).where(models.JobApplication.candidate_id == candidate_profile.candidate_id)

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