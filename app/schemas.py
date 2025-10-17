from pydantic import BaseModel, EmailStr, Field, constr
from typing import List, Optional

# ---------- Users ----------
class UserCreate(BaseModel):
    email: EmailStr
    password: constr(min_length=8)
    role: constr(strip_whitespace=True)

class UserRead(BaseModel):
    user_id: int
    email: EmailStr
    role: str
    class Config:
        from_attributes = True

# ---------- Candidates ----------
class CandidateProfileCore(BaseModel):
    contact_number: Optional[str] = None
    college_program: Optional[str] = None
    batch_year: Optional[int] = Field(None, ge=1900, le=2100)
    resume_text: Optional[str] = None
    # For create/update only: names; backend will auto-create missing skills
    skills: Optional[List[str]] = None

class CandidateProfileCreate(CandidateProfileCore):
    user_id: int
    full_name: str

class CandidateProfileUpdate(CandidateProfileCore):
    full_name: Optional[str] = None

# Read model does NOT include raw skills links; we expose names explicitly
class CandidateProfileRead(BaseModel):
    candidate_id: int
    full_name: str
    contact_number: Optional[str] = None
    college_program: Optional[str] = None
    batch_year: Optional[int] = None
    resume_text: Optional[str] = None
    skill_names: List[str] = []
    class Config:
        from_attributes = True

# ---------- Companies ----------
class CompanyProfileRead(BaseModel):
    company_id: int
    company_name: str
    photo_url: Optional[str] = None
    class Config:
        from_attributes = True

# ---------- Jobs ----------
class CompanyJobCreate(BaseModel):
    job_title: str
    job_description: str
    job_category: Optional[str] = None
    skills: Optional[List[int]] = None

class CompanyJobUpdate(BaseModel):
    job_title: Optional[str] = None
    job_description: Optional[str] = None
    job_category: Optional[str] = None
    skills: Optional[List[int]] = None

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
    concept_uri: str
    preferred_label: str
    alt_labels: Optional[str] = None

class SkillUpdate(BaseModel):
    preferred_label: Optional[str] = None
    alt_labels: Optional[str] = None

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

class PageSkill(BaseModel):
    meta: PageMeta
    items: List[SkillRead]
