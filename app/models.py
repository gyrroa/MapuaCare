from sqlalchemy import Column, Integer, String, ForeignKey, Text, Float, Boolean, DateTime
from sqlalchemy.orm import relationship
from datetime import datetime
from .database import Base

class User(Base):
    __tablename__ = "users"
    user_id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, nullable=False)
    password_hash = Column(String, nullable=False)
    role = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    candidate_profile = relationship("CandidateProfile", uselist=False, back_populates="user")
    company_profile = relationship("CompanyProfile", uselist=False, back_populates="user")
    jobs = relationship("CompanyJob", back_populates="company")

class CandidateProfile(Base):
    __tablename__ = "candidate_profiles"
    candidate_id = Column(Integer, ForeignKey("users.user_id"), primary_key=True)
    full_name = Column(String, nullable=False)
    contact_number = Column(String, nullable=True)
    college_program = Column(String, nullable=True)
    batch_year = Column(Integer, nullable=True)
    resume_text = Column(Text, nullable=True)
    embedding_vector = Column(Text, nullable=True)  # JSON

    user = relationship("User", back_populates="candidate_profile")
    skills = relationship(
        "CandidateSkill",
        back_populates="candidate",
        cascade="all, delete-orphan"  # cascade cleanup
    )

class CompanyProfile(Base):
    __tablename__ = "company_profiles"
    company_id = Column(Integer, ForeignKey("users.user_id"), primary_key=True)
    company_name = Column(String, nullable=False)
    photo_url = Column(String, nullable=True)

    user = relationship("User", back_populates="company_profile")

class Skill(Base):
    __tablename__ = "skills"
    skill_id = Column(Integer, primary_key=True, index=True)
    concept_uri = Column(String, nullable=False)
    preferred_label = Column(String, nullable=False)
    alt_labels = Column(Text, nullable=True)
    candidate_links = relationship("CandidateSkill", back_populates="skill")
    job_links = relationship("JobSkill", back_populates="skill")

class CandidateSkill(Base):
    __tablename__ = "candidate_skills"
    candidate_id = Column(Integer, ForeignKey("candidate_profiles.candidate_id"), primary_key=True)
    skill_id = Column(Integer, ForeignKey("skills.skill_id"), primary_key=True)
    candidate = relationship("CandidateProfile", back_populates="skills")
    skill = relationship("Skill", back_populates="candidate_links")

class CompanyJob(Base):
    __tablename__ = "company_jobs"
    job_id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("users.user_id"))
    job_title = Column(String, nullable=False)
    job_description = Column(Text, nullable=False)
    location = Column(String, nullable=True)
    job_category = Column(String, nullable=True)
    job_embedding_vector = Column(Text, nullable=True)  # JSON

    company = relationship("User", back_populates="jobs")
    skills = relationship(
        "JobSkill",
        back_populates="job",
        cascade="all, delete-orphan"  # cascade cleanup
    )

class JobSkill(Base):
    __tablename__ = "job_skills"
    job_id = Column(Integer, ForeignKey("company_jobs.job_id"), primary_key=True)
    skill_id = Column(Integer, ForeignKey("skills.skill_id"), primary_key=True)
    required = Column(Boolean, default=True)
    job = relationship("CompanyJob", back_populates="skills")
    skill = relationship("Skill", back_populates="job_links")

class MatchResult(Base):
    __tablename__ = "match_results"
    match_id = Column(Integer, primary_key=True, index=True)
    candidate_id = Column(Integer, ForeignKey("candidate_profiles.candidate_id"))
    job_id = Column(Integer, ForeignKey("company_jobs.job_id"))
    similarity_score = Column(Float, nullable=False)
    coverage_score = Column(Float, nullable=False)
    fit_score = Column(Float, nullable=False)
    generated_at = Column(DateTime, default=datetime.utcnow)

class MatchExplanation(Base):
    __tablename__ = "match_explanations"
    explanation_id = Column(Integer, primary_key=True, index=True)
    match_id = Column(Integer, ForeignKey("match_results.match_id"))
    matched_skills = Column(Text)
    missing_skills = Column(Text)
    summary_text = Column(Text)
