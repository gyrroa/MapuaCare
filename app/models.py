from sqlalchemy import Column, Integer, String, ForeignKey, Text, DateTime, Boolean, Table, func, event
from sqlalchemy.orm import relationship
from .database import Base
import datetime
import re # Make sure 're' is imported at the top

# --- Association Table for Job <-> Skill ---
job_skills = Table(
    "job_skills",
    Base.metadata,
    Column("job_id", Integer, ForeignKey("company_jobs.job_id"), primary_key=True),
    Column("skill_id", Integer, ForeignKey("skills.skill_id"), primary_key=True),
    Column("required", Boolean, default=True),
)

# --- Association Table for Candidate <-> Skill ---
candidate_skills = Table(
    "candidate_skills",
    Base.metadata,
    Column("candidate_id", Integer, ForeignKey("candidate_profiles.candidate_id"), primary_key=True),
    Column("skill_id", Integer, ForeignKey("skills.skill_id"), primary_key=True),
)

# --- 1. USER MODEL ---
class User(Base):
    __tablename__ = "users"

    user_id = Column(Integer, primary_key=True)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    role = Column(String, nullable=False) # "candidate" or "company"
    created_at = Column(DateTime, default=datetime.datetime.now(datetime.timezone.utc))

    # Relationships
    candidate_profile = relationship("CandidateProfile", back_populates="user", uselist=False, cascade="all, delete-orphan")
    company_profile = relationship("CompanyProfile", back_populates="user", uselist=False, cascade="all, delete-orphan")
    refresh_tokens = relationship("RefreshToken", back_populates="user", cascade="all, delete-orphan")

# --- 2. PROFILE MODELS ---
class CandidateProfile(Base):
    __tablename__ = "candidate_profiles"

    candidate_id = Column(Integer, ForeignKey("users.user_id"), primary_key=True)
    full_name = Column(String, index=True)
    contact_number = Column(String, nullable=True)
    college_program = Column(String, nullable=True)
    batch_year = Column(Integer, nullable=True)
    
    photo_url = Column(String, nullable=True)
    resume_file_url = Column(String, nullable=True)
    resume_text = Column(Text, nullable=True)
    
    embedding_vector = Column(Text, nullable=True) # Stored as JSON string

    # Relationships
    user = relationship("User", back_populates="candidate_profile")
    skills = relationship(
        "Skill", 
        secondary=candidate_skills, 
        back_populates="candidates"
    )
    applications = relationship("JobApplication", back_populates="candidate", cascade="all, delete-orphan")

class CompanyProfile(Base):
    __tablename__ = "company_profiles"

    company_id = Column(Integer, ForeignKey("users.user_id"), primary_key=True)
    company_name = Column(String, index=True)
    location = Column(String, nullable=True)
    photo_url = Column(String, nullable=True)

    # Relationships
    user = relationship("User", back_populates="company_profile")
    jobs = relationship("CompanyJob", back_populates="company", cascade="all, delete-orphan")

# --- 3. JOB & SKILL MODELS ---
class CompanyJob(Base):
    __tablename__ = "company_jobs"

    job_id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("company_profiles.company_id"), nullable=False)
    job_title = Column(String, index=True, nullable=False)
    job_description = Column(Text, nullable=True)
    job_category = Column(String, index=True, nullable=True)
    
    job_embedding_vector = Column(Text, nullable=True) # Stored as JSON string

    # Relationships
    company = relationship("CompanyProfile", back_populates="jobs")
    skills = relationship(
        "Skill", 
        secondary=job_skills, 
        back_populates="jobs"
    )
    applications = relationship("JobApplication", back_populates="job", cascade="all, delete-orphan")

class Skill(Base):
    __tablename__ = "skills"

    skill_id = Column(Integer, primary_key=True)
    concept_uri = Column(String, unique=True, index=True, nullable=False)
    preferred_label = Column(String, index=True, nullable=False)
    alt_labels = Column(Text, nullable=True) # Stored as ;label1;label2;

    # Relationships
    jobs = relationship(
        "CompanyJob", 
        secondary=job_skills, 
        back_populates="skills"
    )
    candidates = relationship(
        "CandidateProfile", 
        secondary=candidate_skills, 
        back_populates="skills"
    )

# --- THIS IS THE FIX ---
# This helper function automatically formats alt_labels
def format_alt_labels(mapper, connection, target):
    if target.alt_labels:
        # Clean up: split by newline or semicolon, strip whitespace, remove empty
        labels = re.split(r'[\n;]', target.alt_labels)
        cleaned_labels = {label.strip().lower() for label in labels if label and label.strip()}
        
        if cleaned_labels:
            # --- THIS IS THE BUG FIX ---
            # It now correctly joins with a semicolon ';'
            target.alt_labels = f";{';'.join(sorted(cleaned_labels))};"
            # --- END OF BUG FIX ---
        else:
            target.alt_labels = None
    elif target.alt_labels is None:
        # Ensure it's not an empty string
        target.alt_labels = None

# Listen for 'before_insert' and 'before_update' events on the Skill model
event.listen(Skill, 'before_insert', format_alt_labels)
event.listen(Skill, 'before_update', format_alt_labels, propagate=True)
# --- END OF FIX ---


# --- 4. JOB APPLICATION MODEL ---
class JobApplication(Base):
    __tablename__ = "job_applications"
    
    application_id = Column(Integer, primary_key=True)
    job_id = Column(Integer, ForeignKey("company_jobs.job_id"), nullable=False)
    candidate_id = Column(Integer, ForeignKey("candidate_profiles.candidate_id"), nullable=False)
    applied_at = Column(DateTime, default=datetime.datetime.now(datetime.timezone.utc))

    # Relationships
    job = relationship("CompanyJob", back_populates="applications")
    candidate = relationship("CandidateProfile", back_populates="applications")

# --- 5. REFRESH TOKEN MODEL ---
class RefreshToken(Base):
    __tablename__ = "refresh_tokens"
    
    token_id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.user_id"), nullable=False, index=True)
    token = Column(String, nullable=False, unique=True, index=True)
    expires_at = Column(DateTime, nullable=False)
    
    user = relationship("User", back_populates="refresh_tokens")