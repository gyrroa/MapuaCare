# seed.py

import requests
import random
import time

# --- Configuration ---
# !!! REPLACE WITH THE ACTUAL BASE URL OF YOUR API !!!
API_BASE_URL = "http://localhost:8000" 

# --- Realistic Hardcoded Data Sets (Philippines Context) ---

# Skill IDs and Names (for readability, map the names to the required IDs 1-10)
SKILLS_MAP = {
    1: "Excellent English Communication", 
    2: "Technical Troubleshooting", 
    3: "CRM Management (Salesforce/Zendesk)",
    4: "SQL/Database Querying", 
    5: "Python Development", 
    6: "Financial Accounting/Audit",
    7: "Digital Marketing (SEO/SEM)", 
    8: "Team Leadership/Supervision", 
    9: "Data Analysis (Excel/Tableau)",
    10: "Cloud Computing (AWS/Azure)"
}
skill_ids_pool = list(SKILLS_MAP.keys())

# 1. Candidate Data (10)
candidate_data = [
    {
        "email": "m.delacruz@candidateph.com",
        "password": "StrongPass!234",
        "full_name": "Maria Elena Dela Cruz",
        "contact_number": "09175551001",
        "college_program": "BS in Accountancy",
        "batch_year": 2021,
        "resume_text": "CPA board passer with 2 years of experience in accounts payable and financial reconciliation. Proficient in SAP and Excel.",
        "skills": [SKILLS_MAP[6], SKILLS_MAP[9], SKILLS_MAP[1]]
    },
    {
        "email": "j.santos@candidateph.com",
        "password": "StrongPass!234",
        "full_name": "Jose Paolo Santos",
        "contact_number": "09988882002",
        "college_program": "BS in Information Technology",
        "batch_year": 2023,
        "resume_text": "Fresh graduate focused on backend development. Strong foundation in Python and Django. Completed several cloud computing certifications.",
        "skills": [SKILLS_MAP[5], SKILLS_MAP[4], SKILLS_MAP[10], SKILLS_MAP[2]]
    },
    {
        "email": "carmela.reyes@candidateph.com",
        "password": "StrongPass!234",
        "full_name": "Carmela S. Reyes",
        "contact_number": "09227773003",
        "college_program": "AB in Communication Arts",
        "batch_year": 2020,
        "resume_text": "Experienced Customer Service Representative specializing in inbound voice accounts. Excellent communication and conflict resolution skills.",
        "skills": [SKILLS_MAP[1], SKILLS_MAP[3], SKILLS_MAP[2]]
    },
    {
        "email": "k.lopez@candidateph.com",
        "password": "StrongPass!234",
        "full_name": "Kenneth John Lopez",
        "contact_number": "09394444004",
        "college_program": "BS in Electronics Engineering",
        "batch_year": 2018,
        "resume_text": "Seasoned Technical Support Engineer, Tier 2 level. Highly skilled in network troubleshooting and cloud environment maintenance.",
        "skills": [SKILLS_MAP[2], SKILLS_MAP[10], SKILLS_MAP[8], SKILLS_MAP[1]]
    },
    {
        "email": "p.garcia@candidateph.com",
        "password": "StrongPass!234",
        "full_name": "Patricia Ann Garcia",
        "contact_number": "09081115005",
        "college_program": "BS in Psychology",
        "batch_year": 2019,
        "resume_text": "HR professional with expertise in recruitment and employee relations in the BPO sector. Proficient with HRIS systems and data management.",
        "skills": [SKILLS_MAP[8], SKILLS_MAP[1], SKILLS_MAP[9]]
    },
    {
        "email": "m.lim@candidateph.com",
        "password": "StrongPass!234",
        "full_name": "Mark Anthony Lim",
        "contact_number": "09772226006",
        "college_program": "BS in Computer Science",
        "batch_year": 2022,
        "resume_text": "Full-stack developer with projects in React and Node.js. Eager to transition to a pure backend role using Python/Go.",
        "skills": [SKILLS_MAP[5], SKILLS_MAP[4], SKILLS_MAP[10]]
    },
    {
        "email": "d.ramirez@candidateph.com",
        "password": "StrongPass!234",
        "full_name": "Danica Joy Ramirez",
        "contact_number": "09663337007",
        "college_program": "BS in Business Administration (Management)",
        "batch_year": 2020,
        "resume_text": "Digital Marketing Specialist with 3 years focusing on content creation, social media strategy, and Google Ads management.",
        "skills": [SKILLS_MAP[7], SKILLS_MAP[9], SKILLS_MAP[1]]
    },
    {
        "email": "r.cruz@candidateph.com",
        "password": "StrongPass!234",
        "full_name": "Ricardo M. Cruz",
        "contact_number": "09176668008",
        "college_program": "BS in Data Science",
        "batch_year": 2024,
        "resume_text": "Recent Data Science graduate. Highly skilled in data visualization, statistical analysis, and Python for ML tasks.",
        "skills": [SKILLS_MAP[9], SKILLS_MAP[5], SKILLS_MAP[4]]
    },
    {
        "email": "j.mendoza@candidateph.com",
        "password": "StrongPass!234",
        "full_name": "Jennifer Rose Mendoza",
        "contact_number": "09099999009",
        "college_program": "BA in English Studies",
        "batch_year": 2017,
        "resume_text": "Virtual Assistant with a specialization in administrative tasks, email management, and HubSpot CRM maintenance for US executives.",
        "skills": [SKILLS_MAP[3], SKILLS_MAP[1], SKILLS_MAP[7]]
    },
    {
        "email": "ryan.t@candidateph.com",
        "password": "StrongPass!234",
        "full_name": "Ryan Christopher Torres",
        "contact_number": "09551234567",
        "college_program": "BS in Computer Science",
        "batch_year": 2018,
        "resume_text": "Software development team lead experienced in agile methodologies and managing small to medium-sized IT teams.",
        "skills": [SKILLS_MAP[8], SKILLS_MAP[5], SKILLS_MAP[10], SKILLS_MAP[4]]
    }
]

# 2. Company Data (10)
# NOTE: The description, industry, and address fields have been consolidated into 'location'
company_data = [
    {
        "email": "hr@synergyglobalph.com",
        "password": "StrongPass!234",
        "company_name": "Synergy Global Solutions",
        "location": "Ortigas Center, Pasig City, Philippines (BPO & Customer Experience)"
    },
    {
        "email": "jobs@manilatechinnov.com",
        "password": "StrongPass!234",
        "company_name": "Manila Tech Innovators",
        "location": "Ayala Triangle, Makati City, Philippines (Software Development)"
    },
    {
        "email": "careers@vantageph.com",
        "password": "StrongPass!234",
        "company_name": "Vantage Financial Services PH",
        "location": "Cebu IT Park, Cebu City, Philippines (Financial & Accounting KPO)"
    },
    {
        "email": "recruitment@pinnacletalent.com",
        "password": "StrongPass!234",
        "company_name": "Pinnacle Talent Group",
        "location": "Bonifacio Global City, Taguig, Philippines (Human Resources Outsourcing)"
    },
    {
        "email": "secure@cyberedgeph.com",
        "password": "StrongPass!234",
        "company_name": "CyberEdge Philippines",
        "location": "Alabang Business District, Muntinlupa City, Philippines (IT Security & Cloud Services)"
    },
    {
        "email": "digital@manilamarketing.com",
        "password": "StrongPass!234",
        "company_name": "Digital Manila Marketing",
        "location": "Mandaue City, Cebu, Philippines (Digital Marketing)"
    },
    {
        "email": "data@metrodatahub.com",
        "password": "StrongPass!234",
        "company_name": "Metro Data Analytics Hub",
        "location": "Pasay City, Metro Manila, Philippines (Data Science & BI)"
    },
    {
        "email": "techsupport@focuscx.com",
        "password": "StrongPass!234",
        "company_name": "Focus CX Outsourcing Inc.",
        "location": "Iloilo Business Park, Iloilo City, Philippines (Technical Support BPO)"
    },
    {
        "email": "product@pilipinasstartup.com",
        "password": "StrongPass!234",
        "company_name": "The Pilipinas Startup Hub",
        "location": "Makati City, Metro Manila, Philippines (FinTech)"
    },
    {
        "email": "ops@globalprocessdel.com",
        "password": "StrongPass!234",
        "company_name": "Global Process Delivery Co.",
        "location": "Taguig City, Metro Manila, Philippines (KPO & Back Office)"
    }
]

# 3. Job Postings Data (10 - one for each company)
job_postings_data = [
    {
        "job_title": "Bilingual Customer Service Associate",
        "job_description": "Handle high-volume inbound calls in both English and Filipino, resolving customer billing and service issues efficiently. Must be highly empathetic and patient.",
        "job_category": "Customer Service",
        "skills": [1, 3] # English Communication, CRM
    },
    {
        "job_title": "Backend Software Engineer (Python)",
        "job_description": "Design, implement, and maintain scalable APIs using Python (FastAPI/Django) and deploy solutions on AWS. Requires strong SQL skills.",
        "job_category": "Software Engineering",
        "skills": [5, 4, 10] # Python, SQL, Cloud
    },
    {
        "job_title": "Financial Reconciliation Specialist",
        "job_description": "Responsible for daily bank and GL reconciliations. Assist in month-end closing procedures and preparation of audit reports. CPA background a plus.",
        "job_category": "Financial & Accounting",
        "skills": [6, 9, 1] # Financial Acc, Data Analysis, Comm skills
    },
    {
        "job_title": "Team Leader - Talent Acquisition",
        "job_description": "Lead a team of 5 recruiters focused on mass hiring for various BPO accounts. Must have 2+ years of leadership experience in a recruitment setting.",
        "job_category": "Human Resources",
        "skills": [8, 1, 3] # Team Leadership, English Communication, CRM (Applicant Tracking)
    },
    {
        "job_title": "Cloud Operations Engineer",
        "job_description": "Manage, monitor, and troubleshoot infrastructure deployed on AWS/Azure. Implement security best practices and ensure system uptime.",
        "job_category": "IT Operations",
        "skills": [10, 2, 4] # Cloud, Technical Troubleshooting, SQL
    },
    {
        "job_title": "SEO & Content Marketing Specialist",
        "job_description": "Develop and execute organic search strategies, including keyword research and on-page optimization. Use data analytics to measure impact.",
        "job_category": "Digital Marketing",
        "skills": [7, 9, 1] # Digital Marketing, Data Analysis, Comm skills
    },
    {
        "job_title": "Junior Business Intelligence Analyst",
        "job_description": "Build, maintain, and automate dashboards using Tableau/Power BI. Extract and transform data from various databases using advanced SQL.",
        "job_category": "Data Science & BI",
        "skills": [9, 4, 5] # Data Analysis, SQL, Python
    },
    {
        "job_title": "Tier 1 Technical Support (Non-Voice)",
        "job_description": "Provide email and chat support to end-users experiencing technical issues with software and network connectivity. Strong written English required.",
        "job_category": "Technical Support",
        "skills": [2, 1, 3] # Troubleshooting, English Communication, CRM
    },
    {
        "job_title": "Product Associate (FinTech)",
        "job_description": "Support the Product Manager in defining feature requirements, conducting user research, and analyzing market trends for our new mobile app.",
        "job_category": "FinTech/Product",
        "skills": [9, 8, 7] # Data Analysis, Team Leadership (Coordination), Digital Marketing
    },
    {
        "job_title": "Medical Claims Processor (KPO)",
        "job_description": "Process and adjudicate medical claims in compliance with US healthcare regulations. Requires high level of accuracy and attention to detail.",
        "job_category": "KPO/Back Office",
        "skills": [6, 1, 3] # Financial Acc, Comm skills, CRM
    }
]

# --- Helper Functions ---

def api_call(method, endpoint, data=None, json_data=None, headers=None, files=None):
    """General function to handle API requests."""
    url = f"{API_BASE_URL}{endpoint}"
    try:
        if method == "POST":
            # Use 'json' for application/json payloads
            if json_data is not None:
                response = requests.post(url, json=json_data, headers=headers)
            # Use 'files' for multipart/form-data
            elif files is not None:
                response = requests.post(url, files=files, headers=headers)
            # Use 'data' for form-urlencoded (like /users/login)
            else:
                response = requests.post(url, data=data, headers=headers)
        elif method == "GET":
            response = requests.get(url, headers=headers)
        
        response.raise_for_status()
        return response.json()
    except requests.exceptions.HTTPError as errh:
        # Print error details but return None so the calling function can handle the failure
        print(f"HTTP Error for {endpoint} ({method}): {errh.response.status_code} - {errh.response.text.strip()[:100]}...")
        return None 
    except requests.exceptions.RequestException as err:
        print(f"An error occurred for {endpoint}: {err}")
        return None
    return None

def register_user(email, password, role):
    payload = {"email": email, "password": password, "role": role}
    # We let api_call handle the error logging and return None on failure
    response = api_call("POST", "/users/register", json_data=payload)
    if response:
        # Assuming successful registration returns a dict with user_id
        return response.get('user_id') 
    return None

def login_user(email, password):
    try:
        response = requests.post(
            f"{API_BASE_URL}/users/login",
            data={"username": email, "password": password}
        )
        response.raise_for_status()
        tokens = response.json()
        access_token = tokens.get("access_token")
        if access_token:
            return f"Bearer {access_token}"
    except requests.exceptions.HTTPError:
        print("    > Login failed (Check credentials or server status).")
        pass
    except Exception:
        pass
    return None

def create_company_profile(token, data):
    """
    Creates a company profile using multipart/form-data.
    FIXED to send 'location' only, as per API update.
    """
    headers = {"Authorization": token}
    
    # Package text fields as multipart form data using the (None, value) tuple format.
    form_data = {
        "company_name": (None, data["company_name"]),
        "location": (None, data["location"]),  # NEW: Sending 'location'
    }
    
    try:
        response = requests.post(
            f"{API_BASE_URL}/company/profile", 
            headers=headers, 
            files=form_data
        )
        response.raise_for_status()
        return response.json()
    except requests.exceptions.HTTPError as errh:
        print(f"HTTP Error creating company profile: {errh.response.status_code} - {errh.response.text.strip()[:100]}...")
        return None
    except Exception as e:
        print(f"An unexpected error occurred during company profile creation: {e}")
        return None

# Candidate profile creation also uses multipart, so we ensure it's robust
def create_candidate_profile(token, data):
    headers = {"Authorization": token}
    form_data = {
        "full_name": (None, data["full_name"]),
        "contact_number": (None, data["contact_number"]),
        "college_program": (None, data["college_program"]),
        "batch_year": (None, str(data["batch_year"])),
        "resume_text": (None, data["resume_text"]),
        # Convert list of skills back into a comma-separated string for form data
        "skills": (None, ", ".join(data["skills"])), 
    }
    # Use requests.post directly with files=form_data for multipart
    try:
        response = requests.post(f"{API_BASE_URL}/candidate/profile", headers=headers, files=form_data)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.HTTPError as errh:
        print(f"HTTP Error creating candidate profile: {errh.response.status_code} - {errh.response.text.strip()[:100]}...")
        return None
    except Exception as e:
        print(f"An unexpected error occurred during candidate profile creation: {e}")
        return None


def create_job_posting(token, data):
    # This endpoint likely expects JSON, so we use api_call with json_data
    headers = {"Authorization": token}
    response = api_call("POST", "/company/jobs", json_data=data, headers=headers)
    return response

def apply_to_job(token, job_id):
    headers = {"Authorization": token}
    response = api_call("POST", f"/candidate/apply_job/{job_id}", headers=headers)
    return response

# --- Main Seeding Logic ---

def seed_database():
    print("--- Starting Realistic PH Database Seeding ---")

    candidate_tokens = []
    company_tokens = []
    job_ids = []

    # 1. Register and Login Candidates (10 users)
    print("\n## 1. Registering and Logging In Candidates 👤")
    for data in candidate_data:
        print(f"  > Processing {data['full_name']}...")
        token = None
        user_id = register_user(data["email"], data["password"], "candidate")
        
        # FIX: If user_id is None (registration failed, likely already exists), attempt login
        if user_id: 
            token = login_user(data["email"], data["password"])
        else: 
            token = login_user(data["email"], data["password"])
            # We cannot reliably get user_id back from registration failure, so we skip storing it 
            # here, but the token is essential.
        
        if token:
            candidate_tokens.append({"token": token, "data": data, "user_id": user_id})
        time.sleep(0.05)


    # 2. Register and Login Companies (10 users)
    print("\n## 2. Registering and Logging In Companies 🏢")
    for data in company_data:
        print(f"  > Processing {data['company_name']}...")
        token = None
        user_id = register_user(data["email"], data["password"], "company")
        
        # FIX: If user_id is None (registration failed, likely already exists), attempt login
        if user_id:
            token = login_user(data["email"], data["password"])
        else:
            token = login_user(data["email"], data["password"])

        if token:
            company_tokens.append({"token": token, "data": data, "user_id": user_id})
        time.sleep(0.05)


    # 3. Create Candidate Profiles
    print("\n## 3. Creating Candidate Profiles")
    for entry in candidate_tokens:
        print(f"  > Creating profile for {entry['data']['full_name']}...")
        create_candidate_profile(entry["token"], entry["data"])
        time.sleep(0.05)

    # 4. Create Company Profiles
    # NOTE: This step now sends 'location' instead of description/industry/address
    print("\n## 4. Creating Company Profiles (FIXED: Sending 'location' field)")
    for entry in company_tokens:
        print(f"  > Creating profile for {entry['data']['company_name']}...")
        create_company_profile(entry["token"], entry["data"])
        time.sleep(0.05)

    # 5. Create Job Postings (10 postings)
    print("\n## 5. Creating Job Postings")
    for i, job_data in enumerate(job_postings_data):
        if i < len(company_tokens):
            token = company_tokens[i]["token"]
            company_name = company_tokens[i]["data"]["company_name"]
            print(f"  > Posting '{job_data['job_title']}' at {company_name}...")
            job_response = create_job_posting(token, job_data)
            if job_response:
                job_ids.append(job_response.get("job_id")) # Use .get for safety
            time.sleep(0.05)
    
    # 6. Candidates Apply to Jobs
    print("\n## 6. Candidates Applying to Jobs (Simulating 15 applications)")
    
    if job_ids and candidate_tokens:
        # Define 15 random application pairings
        application_pairs = []
        for _ in range(15):
            candidate_entry = random.choice(candidate_tokens)
            job_id = random.choice(job_ids)
            application_pairs.append((candidate_entry, job_id))

        for i, (entry, job_id) in enumerate(application_pairs):
            candidate_token = entry["token"]
            print(f"  > Candidate {entry['data']['full_name'].split()[0]} applying to Job ID {job_id}...")
            apply_to_job(candidate_token, job_id)
            time.sleep(0.05)


    print("\n--- Database Seeding Complete! --- 🎉")

if __name__ == "__main__":
    # Ensure your API server is running before executing this script!
    seed_database()
