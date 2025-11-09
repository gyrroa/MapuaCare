from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form
from sqlalchemy.orm import Session, joinedload, subqueryload
from sqlalchemy import select, func, or_, delete, insert
from typing import Optional, Tuple, Any 
from .. import models, schemas, database, auth
from ..services import embedding, cv_parser, skill_extractor
import json
import os
import uuid
import mimetypes

# Supabase (Python v2)  ->  pip install supabase
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
FOLDER_CANDIDATE_RESUMES = os.getenv("SUPABASE_FOLDER_CANDIDATE_RESUMES", "candidate_resumes")

PHOTO_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
RESUME_EXTS = {".pdf", ".doc", ".docx"}

def _split_public_url(url: str) -> Optional[Tuple[str, str]]:
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

async def _upload_file_sb(
    user_id: int, 
    folder: str, 
    allowed_exts: set, 
    upload: UploadFile
) -> str:
    ext = os.path.splitext(upload.filename or "")[-1].lower()
    if ext not in allowed_exts:
        raise HTTPException(400, f"Unsupported file type. Allowed: {', '.join(sorted(allowed_exts))}")
    content_type = upload.content_type or mimetypes.guess_type(upload.filename or "")[0] or "application/octet-stream"
    object_path = f"{folder}/{user_id}/{uuid.uuid4().hex}{ext}"

    client = _sb()
    content = await upload.read()
    if not content:
        raise HTTPException(400, "Empty upload")

    client.storage.from_(BUCKET_NAME).upload(
        object_path,
        content,
        {
            "contentType": content_type,
            "cacheControl": "31536000",
            "upsert": "true" # Overwrite if path somehow exists
        },
    )
    return client.storage.from_(BUCKET_NAME).get_public_url(object_path)

def _delete_file_url(file_url: Optional[str]):
    if not file_url:
        return
    parsed = _split_public_url(file_url)
    if not parsed:
        return
    bucket, path = parsed
    try:
        _sb().storage.from_(bucket).remove([path])
    except Exception:
        pass

# --- MODIFIED: to include email in response ---
def _map_profile_to_read(prof: models.CandidateProfile, email: str) -> schemas.CandidateProfileRead:
    """Helper to map model to read schema, including email."""
    # This helper now assumes the 'skills' relationship has been loaded
    # in the endpoint before this function is called.
        
    return schemas.CandidateProfileRead(
        candidate_id=prof.candidate_id,
        email=email,
        full_name=prof.full_name,
        contact_number=prof.contact_number,
        college_program=prof.college_program,
        batch_year=prof.batch_year,
        resume_text=prof.resume_text,
        photo_url=prof.photo_url,
        resume_file_url=prof.resume_file_url,
        skill_names=[s.preferred_label for s in prof.skills]
    )


# ---------- Compose candidate text for embeddings (Unchanged) ----------
def _compose_candidate_text(db: Session, prof: models.CandidateProfile) -> str:
    skill_names = [
        s.preferred_label for s in db.query(models.Skill.preferred_label)
        .join(models.candidate_skills, models.candidate_skills.c.skill_id == models.Skill.skill_id)
        .filter(models.candidate_skills.c.candidate_id == prof.candidate_id)
        .limit(10).all() # Get up to 10 skills
    ]
    skill_names = [sn[0] if isinstance(sn, tuple) else sn for sn in skill_names]
    parts = [
        (prof.full_name or "").strip().lower(),
        (f"program: {prof.college_program}" if prof.college_program else "").lower(),
        (f"skills: {', '.join(skill_names)}" if skill_names else ""),
        (prof.resume_text or "").strip().lower()
    ]
    return "\n".join([p for p in parts if p])

# ---------------------------
# CREATE CANDIDATE PROFILE
# ---------------------------
@router.post(
    "/profile",
    response_model=schemas.CandidateProfileRead,
    summary="Create your candidate profile",
    description="Uses the authenticated user's ID; optional photo upload (png/jpg/jpeg/gif/webp) stored in Supabase. Only requires name and optional fields.",
    responses={400: {"description": "Already exists / invalid role"}, 404: {"description": "User not found"}},
)
async def create_candidate_profile(
    full_name: str = Form(...),
    contact_number: Optional[str] = Form(None),
    college_program: Optional[str] = Form(None),
    batch_year: Optional[int] = Form(None),
    photo: Any = File(None, description="optional profile photo"),
    db: Session = Depends(get_db),
    current: models.User = Depends(auth.get_current_user),
):
    uid = current.user_id
    user = db.get(models.User, uid)
    if not user:
        raise HTTPException(404, "User not found")
    if user.role and user.role != "candidate":
        raise HTTPException(400, "User is not a candidate")
    if db.get(models.CandidateProfile, uid):
        raise HTTPException(400, "Candidate profile already exists")

    photo_url: Optional[str] = None
    
    if isinstance(photo, UploadFile) and photo.filename:
        photo_url = await _upload_file_sb(uid, FOLDER_CANDIDATE_PHOTOS, PHOTO_EXTS, photo)

    prof = models.CandidateProfile(
        candidate_id=uid,
        full_name=full_name,
        contact_number=contact_number,
        college_program=college_program,
        batch_year=batch_year,
        photo_url=photo_url,
    )
    db.add(prof)
    db.commit()
    db.refresh(prof)
    
    # We must also refresh the (empty) skills relationship
    db.refresh(prof, ["skills"])
    
    return _map_profile_to_read(prof, current.email)


# ---------------------------
# CV UPLOAD (STEP 1)
# ---------------------------
@router.post(
    "/cv",
    response_model=schemas.CVUploadResponse,
    summary="Upload your CV (Step 1: Suggest Skills)",
    description="Upload a CV (pdf/doc/docx). It will be parsed, and suggested skills from the CSV will be returned for review. The candidate embedding is NOT calculated in this step.",
    responses={400: {"description": "Invalid file type"}, 404: {"description": "Profile not found"}},
)
async def upload_cv(
    cv_file: UploadFile = File(..., description="CV in pdf, doc, or docx format"),
    db: Session = Depends(get_db),
    current: models.User = Depends(auth.get_current_user),
):
    uid = current.user_id
    prof = db.get(models.CandidateProfile, uid)
    if not prof:
        raise HTTPException(404, "Candidate profile not found. Please create one first.")

    # 1. Upload CV to Supabase
    new_url = await _upload_file_sb(uid, FOLDER_CANDIDATE_RESUMES, RESUME_EXTS, cv_file)
    # Rewind file for parsing
    await cv_file.seek(0)
    
    # 2. Parse text from CV
    try:
        resume_text = cv_parser.parse_cv(cv_file.file, cv_file.content_type)
    except Exception as e:
        raise HTTPException(400, f"Failed to parse CV: {str(e)}")
    if not resume_text:
        raise HTTPException(400, "CV appears to be empty or unparseable")

    # 3. Save text and URL to profile
    _delete_file_url(prof.resume_file_url) # Delete old one
    prof.resume_file_url = new_url
    prof.resume_text = resume_text
    
    db.commit() 
    db.refresh(prof)

    # 4. Extract suggested skills
    suggested_skills = skill_extractor.extract_skills_with_details(resume_text)

    # 5. Return the new response
    return schemas.CVUploadResponse(
        candidate_id=prof.candidate_id,
        resume_file_url=prof.resume_file_url,
        resume_text=prof.resume_text,
        suggested_skills=suggested_skills
    )

# ---------------------------
# FINALIZE SKILLS (STEP 2)
# ---------------------------
@router.put(
    "/skills",
    response_model=schemas.CandidateProfileRead, # Return the full profile
    summary="Finalize candidate skills (Step 2: Save, Create, & Embed)",
    description="Provide the final, human-reviewed list of skill NAMES. This will search for existing skills or CREATE new ones if they don't exist. It then overwrites previous skills and triggers the candidate's embedding calculation.",
    responses={403: {"description": "Forbidden"}, 404: {"description": "Profile not found"}},
)
def update_candidate_skills(
    skills_data: schemas.CandidateSkillUpdate,
    db: Session = Depends(get_db),
    current: models.User = Depends(auth.get_current_user),
):
    uid = current.user_id
    prof = db.get(models.CandidateProfile, uid)
    if not prof:
        raise HTTPException(404, "Candidate profile not found")
    if not prof.resume_text:
        raise HTTPException(400, "You must upload a CV before you can finalize skills")

    # 1. Prepare Data: Get unique, lower-cased names
    submitted_skill_names = set(s.strip() for s in skills_data.skill_names if s)
    submitted_skill_names_lower = {name.lower() for name in submitted_skill_names}
    
    # 2. Clear old skills (Required as the first step in the transaction)
    delete_stmt = delete(models.candidate_skills).where(
        models.candidate_skills.c.candidate_id == uid
    )
    db.execute(delete_stmt)
    
    # --- PERFORMANCE FIX START ---

    # 3. Bulk Check Existing Skills (1 QUERY)
    # Check both preferred_label and alt_labels for existing matches
    existing_skills_results = db.query(models.Skill).filter(
        or_(
            func.lower(models.Skill.preferred_label).in_(submitted_skill_names_lower),
            # The alt_labels check is complex in SQL; we fetch everything and process in Python
        )
    ).all()

    existing_skill_ids = []
    found_names_lower = set()
    
    # Process existing results to build the list of found skills
    for skill in existing_skills_results:
        # Check if the existing skill matches any submitted name (accounting for alt_labels)
        if func.lower(skill.preferred_label).in_(submitted_skill_names_lower) or any(
            alt_label.strip().lower() in submitted_skill_names_lower
            for alt_label in (skill.alt_labels or "").split(";")
        ):
            existing_skill_ids.append(skill.skill_id)
            found_names_lower.add(skill.preferred_label.lower())
    
    # 4. Identify new skills
    new_skill_names = [
        name for name in submitted_skill_names 
        if name.lower() not in found_names_lower
    ]

    # 5. Bulk Insert New Skills (1 QUERY)
    new_skill_objects = []
    for skill_name in new_skill_names:
        skill_name_lower = skill_name.lower().strip()
        
        # Use .title() for cleaner, multi-word skill formatting
        new_skill_objects.append(models.Skill(
            preferred_label=skill_name.strip().title(), 
            concept_uri=f"local:{skill_name_lower.replace(' ', '-')}",
            alt_labels=f";{skill_name_lower};"
        ))
    
    # Use bulk_save_objects for a single INSERT operation
    db.bulk_save_objects(new_skill_objects, return_defaults=True)
    
    # Collect IDs from newly created skills
    new_skill_ids = [s.skill_id for s in new_skill_objects]
    
    # --- PERFORMANCE FIX END ---
    
    final_skill_ids = existing_skill_ids + new_skill_ids

    # 6. Add all the final, normalized skill links (1 QUERY)
    if final_skill_ids:
        insert_values = [
            {"candidate_id": uid, "skill_id": sid} for sid in set(final_skill_ids)
        ]
        insert_stmt = insert(models.candidate_skills).values(insert_values)
        db.execute(insert_stmt)

    # 7. (Re)calculate and save embedding
    composed = _compose_candidate_text(db, prof)
    prof.embedding_vector = json.dumps(embedding.get_embedding(composed))

    # 8. Commit everything
    db.commit()
    db.refresh(prof)
    db.refresh(prof, ["skills"]) # Eager load skills
    return _map_profile_to_read(prof, current.email)

# ---------------------------
# READ/UPDATE/DELETE PROFILE
# ---------------------------

# READ ONE (public)
@router.get(
    "/profiles/{candidate_id}",
    response_model=schemas.CandidateProfileRead,
    summary="Get a candidate profile",
    responses={404: {"description": "Candidate profile not found"}},
)
def get_candidate_profile(candidate_id: int, db: Session = Depends(get_db)):
    # --- THIS IS THE FIX ---
    # The import is now at the top of the file
    result = db.query(models.CandidateProfile, models.User.email).join(
        models.User, models.User.user_id == models.CandidateProfile.candidate_id
    ).options(
        joinedload(models.CandidateProfile.skills)
    ).filter(models.CandidateProfile.candidate_id == candidate_id).first()
    # --- END OF FIX ---

    if not result:
        raise HTTPException(404, "Candidate profile not found")
        
    prof, email = result
    
    # db.refresh(prof, ["skills"]) # No longer needed due to joinedload
    
    return _map_profile_to_read(prof, email)

# READ ALL (public)
@router.get(
    "/profiles",
    response_model=schemas.PageCandidate,
    summary="List candidate profiles",
    description="Search in name, college program, or resume text with `q`.",
)
def list_candidate_profiles(
    db: Session = Depends(get_db),
    q: Optional[str] = Query(None, description="search in name/program/resume text"),
    page: int = Query(1, ge=1),
    per_page: int = Query(10, ge=1, le=100),
):
    # --- THIS IS THE FIX ---
    # The import is now at the top of the file
    stmt = select(models.CandidateProfile, models.User.email).join(
        models.User, models.User.user_id == models.CandidateProfile.candidate_id
    ).options(
        subqueryload(models.CandidateProfile.skills)
    )
    # --- END OF FIX ---
    
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(
            models.CandidateProfile.full_name.ilike(like),
            models.CandidateProfile.college_program.ilike(like),
            models.CandidateProfile.resume_text.ilike(like),
        ))
    
    total_stmt = select(func.count()).select_from(stmt.with_only_columns(models.CandidateProfile.candidate_id).subquery())
    total = db.scalar(total_stmt)

    results = db.execute(
        stmt.order_by(models.CandidateProfile.candidate_id.desc())
             .offset((page - 1) * per_page)
             .limit(per_page)
    ).all()

    items_with_skills = []
    for prof, email in results:
        # db.refresh(prof, ["skills"]) # No longer needed due to subqueryload
        items_with_skills.append(_map_profile_to_read(prof, email))

    return schemas.PageCandidate(
        meta=schemas.PageMeta(page=page, per_page=per_page, total=total or 0),
        items=items_with_skills,
    )

# UPDATE CANDIDATE PROFILE (TEXT FIELDS)
@router.put(
    "/profile",
    response_model=schemas.CandidateProfileRead,
    summary="Update your candidate profile",
    description="Update text fields. To update skills, use `PUT /candidate/skills`. To update CV, use `POST /candidate/cv`.",
    responses={403: {"description": "Forbidden"}, 404: {"description": "Candidate profile not found"}},
)
async def update_candidate_profile(
    full_name: Optional[str] = Form(None),
    contact_number: Optional[str] = Form(None),
    college_program: Optional[str] = Form(None),
    batch_year: Optional[int] = Form(None),
    photo: Any = File(None, description="optional new photo"),
    remove_photo: Optional[bool] = Form(False),
    db: Session = Depends(get_db),
    current: models.User = Depends(auth.get_current_user),
):
    uid = current.user_id
    prof = db.get(models.CandidateProfile, uid)
    if not prof:
        raise HTTPException(404, "Candidate profile not found")

    changed = False
    if full_name is not None:
        prof.full_name = full_name
        changed = True
    if contact_number is not None:
        prof.contact_number = contact_number
    if college_program is not None:
        prof.college_program = college_program
        changed = True
    if batch_year is not None:
        prof.batch_year = batch_year

    if isinstance(photo, UploadFile) and photo.filename:
        new_url = await _upload_file_sb(uid, FOLDER_CANDIDATE_PHOTOS, PHOTO_EXTS, photo)
        _delete_file_url(prof.photo_url)
        prof.photo_url = new_url
    elif remove_photo:
        _delete_file_url(prof.photo_url)
        prof.photo_url = None

    # If text fields changed, re-calculate embedding
    if changed and prof.embedding_vector:
        composed = _compose_candidate_text(db, prof)
        prof.embedding_vector = json.dumps(embedding.get_embedding(composed))

    db.commit()
    db.refresh(prof)
    db.refresh(prof, ["skills"]) # Eager load skills
    
    return _map_profile_to_read(prof, current.email)

# DELETE CANDIDATE PROFILE
@router.delete(
    "/profile",
    status_code=204,
    summary="Delete your candidate profile",
    responses={403: {"description": "Forbidden"}, 404: {"description": "Candidate profile not found"}},
)
def delete_candidate_profile(
    db: Session = Depends(get_db),
    current: models.User = Depends(auth.get_current_user),
):
    uid = current.user_id
    prof = db.get(models.CandidateProfile, uid)
    if not prof:
        raise HTTPException(404, "Candidate profile not found")
    
    _delete_file_url(prof.photo_url)
    _delete_file_url(prof.resume_file_url)
    
    db.delete(prof)
    db.commit()

# --- JOB APPLICATION ENDPOINTS ---

# APPLY TO JOB
@router.post(
    "/apply/{job_id}",
    response_model=schemas.JobApplicationRead,
    summary="Apply for a job",
    description="Allows the authenticated candidate to apply for a specific job.",
)
def apply_for_job(
    job_id: int,
    db: Session = Depends(get_db),
    current: models.User = Depends(auth.get_current_user),
):
    candidate_id = current.user_id
    
    prof = db.get(models.CandidateProfile, candidate_id)
    if not prof:
        raise HTTPException(404, "Candidate profile not found. Please create one first.")
        
    if not prof.embedding_vector:
        raise HTTPException(400, "Please upload a CV and finalize your skills before applying.")

    job = db.get(models.CompanyJob, job_id)
    if not job:
        raise HTTPException(404, "Job not found")

    existing_application = db.query(models.JobApplication).filter(
        models.JobApplication.candidate_id == candidate_id,
        models.JobApplication.job_id == job_id
    ).first()
    
    if existing_application:
        raise HTTPException(400, "You have already applied for this job")

    new_application = models.JobApplication(
        candidate_id=candidate_id,
        job_id=job_id
    )
    db.add(new_application)
    db.commit()
    db.refresh(new_application)

    return new_application

# WITHDRAW APPLICATION (NEW ENDPOINT)
@router.delete(
    "/apply/{job_id}",
    status_code=204, # No Content on successful deletion
    summary="Withdraw a job application",
    description="Allows the authenticated candidate to withdraw their application for a specific job.",
    responses={404: {"description": "Application not found"}, 400: {"description": "Application cannot be withdrawn"}},
)
def withdraw_job_application(
    job_id: int,
    db: Session = Depends(get_db),
    current: models.User = Depends(auth.get_current_user),
):
    candidate_id = current.user_id
    
    # 1. Find the existing application
    application = db.query(models.JobApplication).filter(
        models.JobApplication.candidate_id == candidate_id,
        models.JobApplication.job_id == job_id
    ).first()
    
    if not application:
        raise HTTPException(404, "Application not found for this job.")

    # 2. Delete the application
    db.delete(application)
    db.commit()
    
    return # Returns 204 No Content

# LIST MY APPLICATIONS
@router.get(
    "/my-applications",
    response_model=schemas.PageJobApplication,
    summary="List my job applications",
    description="Returns a paginated list of jobs the authenticated candidate has applied to.",
)
def get_my_applications(
    db: Session = Depends(get_db),
    current: models.User = Depends(auth.get_current_user),
    page: int = Query(1, ge=1),
    per_page: int = Query(10, ge=1, le=100),
):
    candidate_id = current.user_id
    
    stmt = select(models.JobApplication).where(models.JobApplication.candidate_id == candidate_id)
    
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    items = db.execute(
        stmt.order_by(models.JobApplication.applied_at.desc())
             .offset((page - 1) * per_page)
             .limit(per_page)
    ).scalars().all()

    return schemas.PageJobApplication(
        meta=schemas.PageMeta(page=page, per_page=per_page, total=total or 0),
        items=items,
    )

# ---------- DEBUGGING ENDPOINT ----------
@router.get(
    "/debug_text/{candidate_id}",
    summary="[DEBUG] Get raw resume_text from DB"
)
def debug_get_resume_text(candidate_id: int, db: Session = Depends(get_db)):
    """
    A temporary endpoint to check exactly what is stored 
    in the resume_text column in the database.
    """
    prof = db.get(models.CandidateProfile, candidate_id)
    if not prof:
        raise HTTPException(404, "Candidate not found")
        
    # We return the raw text directly from the database
    # in a simple JSON response.
    return {"candidate_id": prof.candidate_id, "raw_resume_text": prof.resume_text}
# ---------- END DEBUGGING ENDPOINT ----------