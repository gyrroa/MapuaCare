from pydantic import BaseModel, EmailStr, Field, constr
from typing import List, Optional
from datetime import datetime

# ---------- Users ----------
class UserCreate(BaseModel):
    email: EmailStr = Field(..., description="Unique email for login", example="user@example.com")
    password: constr(min_length=8) = Field(..., description="Min 8 characters", example="StrongPass!234")
    role: constr(strip_whitespace=True) = Field(..., description="Either 'candidate' or 'company'", example="candidate")

class UserRead(BaseModel):
    user_id: int
    email: EmailStr
    role: str
    class Config:
        from_attributes = True

# NEW: auth payloads
class RefreshRequest(BaseModel):
    refresh_token: str = Field(..., description="Refresh JWT")

class LogoutRequest(BaseModel):
    refresh_token: str = Field(..., description="Refresh JWT to revoke")

# ---------- Candidates ----------
class CandidateProfileCore(BaseModel):
    contact_number: Optional[str] = Field(None, example="+63 900 000 0000")
    college_program: Optional[str] = Field(None, example="BS Computer Science")
    batch_year: Optional[int] = Field(None, ge=1900, le=2100, example=2026)
    resume_text: Optional[str] = Field(None, example="Experienced in Python and FastAPI...")
    skills: Optional[List[str]] = Field(None, description="Skill names; auto-creates if missing", example=["Python", "FastAPI"])

class CandidateProfileCreate(CandidateProfileCore):
    full_name: str = Field(..., example="Alex Rivera")

class CandidateProfileUpdate(CandidateProfileCore):
    full_name: Optional[str] = Field(None, example="Alex J. Rivera")

class CandidateProfileRead(BaseModel):
    candidate_id: int
    full_name: str
    contact_number: Optional[str] = None
    college_program: Optional[str] = None
    batch_year: Optional[int] = None
    resume_text: Optional[str] = None
    photo_url: Optional[str] = None          
    resume_file_url: Optional[str] = None   
    skill_names: List[str] = []

    class Config:
        from_attributes = True

# ---------- Companies ----------
class CompanyProfileRead(BaseModel):
    company_id: int
    company_name: str
    location: Optional[str] = None
    photo_url: Optional[str] = None
    class Config:
        from_attributes = True

# ---------- Jobs ----------
class CompanyJobCreate(BaseModel):
    job_title: str = Field(..., example="Backend Engineer")
    job_description: str = Field(..., example="Build and maintain REST APIs with FastAPI.")
    job_category: Optional[str] = Field(None, example="Software Engineering")
    skills: Optional[List[int]] = Field(None, description="Skill IDs from /skills", example=[1, 5, 42])

class CompanyJobUpdate(BaseModel):
    job_title: Optional[str] = Field(None, example="Senior Backend Engineer")
    job_description: Optional[str] = Field(None, example="Own services and improve performance.")
    job_category: Optional[str] = Field(None, example="Software Engineering")
    skills: Optional[List[int]] = Field(None, example=[1, 5, 42])

class CompanyJobRead(BaseModel):
    job_id: int
    company_id: int
    job_title: str
    job_description: str
    job_category: Optional[str]
    class Config:
        from_attributes = True

# ---------- Skills ----------
class SkillCreate(BaseModel):
    concept_uri: str = Field(..., example="local:python")
    preferred_label: str = Field(..., example="Python")
    alt_labels: Optional[str] = Field(None, example="py; python3")

class SkillUpdate(BaseModel):
    preferred_label: Optional[str] = Field(None, example="Python")
    alt_labels: Optional[str] = Field(None, example="py; python3")

class SkillRead(BaseModel):
    skill_id: int
    concept_uri: str
    preferred_label: str
    alt_labels: Optional[str]
    class Config:
        from_attributes = True

# ---------- Matching / evidence ----------
class Evidence(BaseModel):
    job_mentions: List[str] = []
    resume_mentions: List[str] = []

class MatchResponse(BaseModel):
    job_id: int
    fit_score: float
    summary_text: str
    sim_score: Optional[float] = None
    coverage_score: Optional[float] = None
    matched_skills: List[str] = []
    missing_skills: List[str] = []
    evidence: Evidence = Evidence()

# ---------- Recommendations ----------
class JobRecommendation(BaseModel):
    job_id: int
    job_title: str
    job_category: Optional[str] = None
    fit_score: float
    sim_score: float
    coverage_score: float

class CandidateRecommendation(BaseModel):
    candidate_id: int
    full_name: str
    fit_score: float
    sim_score: float
    coverage_score: float

# ---------- Pagination ----------
class PageMeta(BaseModel):
    page: int
    per_page: int
    total: int

class PageJob(BaseModel):
    meta: PageMeta
    items: List[CompanyJobRead]

class PageCandidate(BaseModel):
    meta: PageMeta
    items: List[CandidateProfileRead]

class PageCompany(BaseModel):
    meta: PageMeta
    items: List[CompanyProfileRead]

class PageSkill(BaseModel):
    meta: PageMeta
    items: List[SkillRead]

# NEW: Schema for job application details
class JobApplicationRead(BaseModel):
    application_id: int  # Application ID
    candidate_id: int  # Candidate ID
    job_id: int  # Job ID
    applied_at: datetime  # When the application was made

    class Config:
        from_attributes = True

# NEW: Schema for job application data shown to the candidate
class CandidateJobApplicationRead(BaseModel):
    candidate_id: int  # Candidate ID
    job_id: int  # Job ID
    applied_at: datetime  # Date and time the application was made

# NEW: Pagination schema for job applications
class PageJobApplication(BaseModel):
    meta: PageMeta  # Pagination metadata
    items: List[JobApplicationRead]  # List of job application records
