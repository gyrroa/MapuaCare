# seed_realistic.py
import json
import math
import random
from datetime import datetime, timedelta

from app.database import Base, engine, SessionLocal
from app import models
from app.auth import hash_password
from app.services import embedding  # sentence-transformers
from sqlalchemy import text

# ------------------------
# Tunables (change here)
# ------------------------
RANDOM_SEED = 42
NUM_COMPANIES = 4
NUM_CANDIDATES = 40
NUM_JOBS = 30
CANDIDATE_MIN_SKILLS = 6
CANDIDATE_MAX_SKILLS = 12
JOB_MIN_SKILLS = 5
JOB_MAX_SKILLS = 8
RESET_DB_FIRST = True

random.seed(RANDOM_SEED)

# ------------------------
# Vocab / corpora
# ------------------------
PH_LOCATIONS = [
    "Makati", "Taguig", "Quezon City", "Pasig", "Mandaluyong",
    "Manila", "Cebu", "Davao", "Iloilo", "Bacolod", "Remote (PH)", "Remote (Global)"
]
JOB_CATEGORIES = ["Engineering", "Data", "Product", "Security", "Cloud", "QA", "Mobile"]

# NOTE: use plain hyphen (ASCII) to avoid encoding issues on Windows terminals
LEVELS = [
    ("Junior", "1-2"),
    ("Mid", "2-5"),
    ("Senior", "5+"),
]

SALARY_BANDS = {
    "Engineering": (60000, 200000),
    "Data": (50000, 180000),
    "Product": (70000, 220000),
    "Security": (80000, 230000),
    "Cloud": (70000, 220000),
    "QA": (45000, 140000),
    "Mobile": (60000, 190000),
}

COMPANY_NAMES = [
    "Arcadia Systems", "Bayani Tech", "Kalayaan Labs", "Narra Analytics",
    "Mabuhay Cloud", "Silverline Digital", "Tala Security", "HarborWorks"
]

# 40ish practical skills; feel free to expand
SKILL_DEFS = [
    ("urn:skill:python", "Python", "py;python3"),
    ("urn:skill:java", "Java", "jvm"),
    ("urn:skill:javascript", "JavaScript", "js;node;node.js"),
    ("urn:skill:typescript", "TypeScript", "ts"),
    ("urn:skill:react", "React", "react.js;reactjs"),
    ("urn:skill:vue", "Vue.js", "vue"),
    ("urn:skill:angular", "Angular", "angularjs"),
    ("urn:skill:html", "HTML", "html5"),
    ("urn:skill:css", "CSS", "css3"),
    ("urn:skill:sql", "SQL", "postgres;mysql;sql server"),
    ("urn:skill:nosql", "NoSQL", "mongodb;dynamodb;cosmos"),
    ("urn:skill:docker", "Docker", "containers"),
    ("urn:skill:kubernetes", "Kubernetes", "k8s"),
    ("urn:skill:aws", "AWS", "amazon web services"),
    ("urn:skill:azure", "Azure", "microsoft azure"),
    ("urn:skill:gcp", "GCP", "google cloud"),
    ("urn:skill:linux", "Linux", "ubuntu;debian;centos"),
    ("urn:skill:git", "Git", "github;gitlab"),
    ("urn:skill:ci", "CI/CD", "jenkins;github actions;gitlab ci"),
    ("urn:skill:terraform", "Terraform", "iac;infrastructure as code"),
    ("urn:skill:ansible", "Ansible", "configuration management"),
    ("urn:skill:rest", "REST APIs", "http api"),
    ("urn:skill:grpc", "gRPC", "protobuf"),
    ("urn:skill:flask", "Flask", "microservices"),
    ("urn:skill:fastapi", "FastAPI", "fast api"),
    ("urn:skill:django", "Django", "django rest"),
    ("urn:skill:pandas", "Pandas", "dataframe"),
    ("urn:skill:numpy", "NumPy", "ndarray"),
    ("urn:skill:sklearn", "scikit-learn", "sklearn"),
    ("urn:skill:pytorch", "PyTorch", "torch"),
    ("urn:skill:tensorflow", "TensorFlow", "tf"),
    ("urn:skill:etl", "ETL", "airflow;elt"),
    ("urn:skill:snowflake", "Snowflake", "dw"),
    ("urn:skill:dbt", "dbt", "data build tool"),
    ("urn:skill:product", "Product Management", "product mgr"),
    ("urn:skill:pm-sql", "Product Analytics (SQL)", "experimentation"),
    ("urn:skill:sec", "Application Security", "appsec"),
    ("urn:skill:threat", "Threat Modeling", "stride"),
    ("urn:skill:qa", "QA Testing", "manual testing"),
    ("urn:skill:mobile", "Mobile Development", "android;ios;kotlin;swift"),
]

FIRST_NAMES = [
    "Marco", "Janelle", "Ramon", "Aubrey", "Paolo", "Mika", "Jonas", "Althea",
    "Miguel", "Carla", "Diego", "Faith", "Lance", "Bea", "Noah", "Sophia",
    "Rhea", "Jasper", "Liza", "Ken", "Nina", "Andre", "Trixie", "Gino", "Iris",
]
LAST_NAMES = [
    "Santos", "Reyes", "Cruz", "Bautista", "Ocampo", "Gonzales", "Flores",
    "Navarro", "Domingo", "Valdez", "Garcia", "Chua", "Tan", "Lim", "Uy"
]
SCHOOLS = [
    "Mapúa University", "Ateneo de Manila University", "De La Salle University",
    "University of the Philippines", "University of San Carlos",
    "Polytechnic University of the Philippines"
]
DEGREES = [
    "BS Computer Science", "BS Information Technology", "BS Computer Engineering",
    "BS Data Science", "BS Information Systems", "BS Electronics Engineering"
]

RESP_TEMPLATES = [
    "- Design, build, and ship high-quality features with an emphasis on reliability.\n"
    "- Collaborate with product, design, and QA on specs and delivery.\n"
    "- Participate in code reviews and improve engineering best practices.",

    "- Own services end-to-end from design to production support.\n"
    "- Write clean, maintainable code and automated tests.\n"
    "- Monitor and improve performance, scalability, and security."
]

REQ_TEMPLATES = [
    "- {lvl} experience ({yrs} years) in {cat} or related role.\n"
    "- Strong with {core1} and {core2}.\n"
    "- Bonus: exposure to {bonus1} or {bonus2}.\n"
    "- Comfortable working in an agile environment.",
]

BENEFITS = [
    "HMO coverage + dependents", "Flexible hours", "Hybrid/Remote setup",
    "13th month pay", "Annual training budget", "Internet allowance"
]

# ------------------------
# Helpers
# ------------------------
def ensure_tables():
    Base.metadata.create_all(bind=engine)

def ensure_job_embedding_column(session):
    """
    Ensure the column exists (SQLite). No-op if already there.
    """
    cols = [r[1] for r in session.execute(text("PRAGMA table_info(company_jobs)")).all()]
    if "job_embedding_vector" not in cols:
        session.execute(text("ALTER TABLE company_jobs ADD COLUMN job_embedding_vector TEXT"))


def reset_db(session):
    session.query(models.MatchExplanation).delete()
    session.query(models.MatchResult).delete()
    session.query(models.JobSkill).delete()
    session.query(models.CompanyJob).delete()
    session.query(models.CandidateSkill).delete()
    session.query(models.CandidateProfile).delete()
    session.query(models.Skill).delete()
    session.query(models.User).delete()
    session.commit()

def pick_skills(skills, kmin, kmax, bias=None):
    k = random.randint(kmin, kmax)
    if bias:
        # bias toward a category by including some preselected skills first
        chosen = random.sample(bias, min(len(bias), max(1, k // 2)))
        remaining = [s for s in skills if s.skill_id not in {x.skill_id for x in chosen}]
        chosen += random.sample(remaining, k - len(chosen))
        return chosen
    return random.sample(skills, k)

def gaussian_salary(cat):
    lo, hi = SALARY_BANDS.get(cat, (50000, 200000))
    mu = (lo + hi) / 2
    sigma = (hi - lo) / 6  # 99.7% within [lo, hi]
    # clamp to band
    val = max(lo, min(hi, int(random.gauss(mu, sigma) // 1000 * 1000)))
    return val

def paragraph_join(lines):
    return "\n".join(lines)

def build_job_description(title, cat, lvl_label, yrs, core1, core2, bonus1, bonus2, salary, benefits, location):
    resp = random.choice(RESP_TEMPLATES)
    req = random.choice(REQ_TEMPLATES).format(
        lvl=lvl_label, yrs=yrs, cat=cat, core1=core1, core2=core2, bonus1=bonus1, bonus2=bonus2
    )
    perks = "- " + "\n- ".join(random.sample(BENEFITS, 3))
    header = (
        f"**Role:** {title} ({lvl_label})\n"
        f"**Category:** {cat}\n"
        f"**Location:** {location}\n"
        f"**Compensation:** ₱{salary:,} / month (gross), depends on experience\n"
    )
    return paragraph_join([
        header,
        "### Responsibilities\n" + resp,
        "### Requirements\n" + req,
        "### Benefits\n" + perks
    ])

# ------------------------
# Seeding steps
# ------------------------
def seed_skills(session):
    skills = []
    for uri, label, alts in SKILL_DEFS:
        s = models.Skill(concept_uri=uri, preferred_label=label, alt_labels=alts)
        session.add(s)
        skills.append(s)
    session.commit()
    return skills

def seed_companies(session, n=NUM_COMPANIES):
    companies = []
    names = random.sample(COMPANY_NAMES, n)
    for i, name in enumerate(names, start=1):
        u = models.User(
            email=f"{name.lower().replace(' ', '')}@example.com",
            password_hash=hash_password("password123"),
            role="company",
            created_at=datetime.utcnow()
        )
        session.add(u)
        session.flush()
        companies.append((u, name))
    session.commit()
    return companies  # list of (user, company_name)

def seed_candidates(session, skills, n=NUM_CANDIDATES):
    candidates = []
    for i in range(n):
        fn = random.choice(FIRST_NAMES)
        ln = random.choice(LAST_NAMES)
        full = f"{fn} {ln}"
        email = f"{fn}.{ln}{i}@example.com".lower()

        u = models.User(
            email=email,
            password_hash=hash_password("password123"),
            role="candidate",
            created_at=datetime.utcnow()
        )
        session.add(u)
        session.flush()

        # bias candidate skills by rough specialty
        specialty = random.choice(JOB_CATEGORIES)
        bias_pool = [s for s in skills if
                     (specialty == "Engineering" and s.preferred_label in {"Python","Java","JavaScript","TypeScript","FastAPI","Django","React","SQL","Docker","Git","CI/CD"}) or
                     (specialty == "Data" and s.preferred_label in {"Python","Pandas","NumPy","scikit-learn","ETL","dbt","SQL","Snowflake"}) or
                     (specialty == "Product" and s.preferred_label in {"Product Management","Product Analytics (SQL)","REST APIs"}) or
                     (specialty == "Security" and s.preferred_label in {"Application Security","Threat Modeling","Linux","AWS","Kubernetes"}) or
                     (specialty == "Cloud" and s.preferred_label in {"AWS","Azure","GCP","Docker","Kubernetes","Terraform","Ansible"}) or
                     (specialty == "QA" and s.preferred_label in {"QA Testing","REST APIs","Python"}) or
                     (specialty == "Mobile" and s.preferred_label in {"Mobile Development","JavaScript","TypeScript","React"})
        ]

        cand_skills = pick_skills(skills, CANDIDATE_MIN_SKILLS, CANDIDATE_MAX_SKILLS, bias=bias_pool)

        # Construct a human-ish resume
        yrs = random.randint(1, 10)
        location = random.choice(PH_LOCATIONS)
        school = random.choice(SCHOOLS)
        degree = random.choice(DEGREES)
        highlights = ", ".join(sorted({s.preferred_label for s in cand_skills})[:8])

        resume_text = f"""
SUMMARY
{full} is a {specialty.lower()} professional with {yrs} years of experience delivering production systems and collaborating with cross-functional teams. Key skills include: {highlights}.

EXPERIENCE
- {random.choice(COMPANY_NAMES)} — {specialty} Specialist ({datetime.utcnow().year - yrs}-{datetime.utcnow().year})
  • Built services and data pipelines; reduced incidents by {random.randint(10,40)}%.
  • Worked with stakeholders to prioritize features and improvements.

EDUCATION
- {degree}, {school}

SKILLS
{", ".join(sorted({s.preferred_label for s in cand_skills}))}
        """.strip()

        emb = embedding.get_embedding(resume_text)

        cp = models.CandidateProfile(
            candidate_id=u.user_id,
            full_name=full,
            location=location,
            resume_text=resume_text,
            embedding_vector=json.dumps(emb)
        )
        session.add(cp)

        # CandidateSkill links (optional but good for analytics later)
        for s in random.sample(cand_skills, k=min(6, len(cand_skills))):
            session.add(models.CandidateSkill(candidate_id=u.user_id, skill_id=s.skill_id))

        candidates.append(cp)

    session.commit()
    return candidates

def _compose_job_text_for_embed(title, cat, skill_names, description):
    parts = [
        (title or "").strip().lower(),
        (f"category: {cat}" if cat else "").lower(),
        (f"skills: {', '.join(skill_names)}" if skill_names else ""),
        (description or "").strip().lower(),
    ]
    return "\n".join([p for p in parts if p])

def seed_jobs(session, companies, skills, n=NUM_JOBS):
    jobs = []
    for i in range(n):
        # choose a company
        company_user, company_name = random.choice(companies)
        # choose a category and level
        cat = random.choice(JOB_CATEGORIES)
        lvl_label, yrs_str = random.choice(LEVELS)
        yrs = yrs_str
        # skill picks
        bias_pool = [s for s in skills if
                     (cat == "Engineering" and s.preferred_label in {"Python","Java","JavaScript","TypeScript","FastAPI","Django","React","SQL","Docker","Git","CI/CD"}) or
                     (cat == "Data" and s.preferred_label in {"Python","Pandas","NumPy","scikit-learn","ETL","dbt","SQL","Snowflake"}) or
                     (cat == "Product" and s.preferred_label in {"Product Management","Product Analytics (SQL)","REST APIs"}) or
                     (cat == "Security" and s.preferred_label in {"Application Security","Threat Modeling","Linux","AWS","Kubernetes"}) or
                     (cat == "Cloud" and s.preferred_label in {"AWS","Azure","GCP","Docker","Kubernetes","Terraform","Ansible"}) or
                     (cat == "QA" and s.preferred_label in {"QA Testing","REST APIs","Python"}) or
                     (cat == "Mobile" and s.preferred_label in {"Mobile Development","JavaScript","TypeScript","React"})
        ]
        job_skills = pick_skills(skills, JOB_MIN_SKILLS, JOB_MAX_SKILLS, bias=bias_pool)
        core1, core2 = random.sample([s.preferred_label for s in job_skills], 2)
        bonus1, bonus2 = random.sample([s.preferred_label for s in skills if s not in job_skills], 2)

        # title from category
        title_by_cat = {
            "Engineering": ["Software Engineer", "Backend Engineer", "Fullstack Engineer"],
            "Data": ["Data Analyst", "Data Engineer", "Data Scientist"],
            "Product": ["Product Manager", "Associate Product Manager"],
            "Security": ["Application Security Engineer", "Security Analyst"],
            "Cloud": ["Cloud Engineer", "Site Reliability Engineer"],
            "QA": ["QA Engineer", "SDET"],
            "Mobile": ["Mobile Developer", "React Native Developer", "Android Developer"],
        }
        title = random.choice(title_by_cat[cat])
        # salary & location
        salary = gaussian_salary(cat)
        location = random.choice(PH_LOCATIONS)

        # job text
        description = build_job_description(
            title, cat, lvl_label, yrs, core1, core2, bonus1, bonus2, salary, BENEFITS, location
        )

        job = models.CompanyJob(
            company_id=company_user.user_id,
            job_title=f"{title}",
            job_description=description,
            location=location,
            job_category=cat
        )
        session.add(job)
        session.flush()

        # link skills
        for s in job_skills:
            session.add(models.JobSkill(job_id=job.job_id, skill_id=s.skill_id, required=True))

        # PRECOMPUTE & STORE JOB EMBEDDING (requires column)
        top_skill_names = [s.preferred_label for s in job_skills[:5]]
        composed = _compose_job_text_for_embed(title, cat, top_skill_names, description)
        job.job_embedding_vector = json.dumps(embedding.get_embedding(composed))

        jobs.append(job)

    session.commit()
    return jobs

def main():
    ensure_tables()
    session = SessionLocal()
    try:
        if RESET_DB_FIRST:
            reset_db(session)

        # make sure the extra column exists before inserting jobs
        ensure_job_embedding_column(session)

        skills = seed_skills(session)
        companies = seed_companies(session, n=NUM_COMPANIES)
        candidates = seed_candidates(session, skills, n=NUM_CANDIDATES)
        jobs = seed_jobs(session, companies, skills, n=NUM_JOBS)

        print(f"✅ Seeded {len(companies)} companies, {len(candidates)} candidates, {len(jobs)} jobs, {len(skills)} skills.")
        print("   Example company credential: email=arcadiasystems@example.com  password=password123")
        print("   Example candidate credential: email=marco.santos0@example.com  password=password123")
    finally:
        session.close()

if __name__ == "__main__":
    main()
