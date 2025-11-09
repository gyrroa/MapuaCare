import pandas as pd
import os
import re
from typing import List, Dict, Set

base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
skills_path = os.path.join(base_dir, "data", "skills_esco.csv")

# --- MODIFIED: Load dataframe and prepare it for matching ---
skills_df = pd.DataFrame(columns=["conceptUri", "preferredLabel", "altLabels"])
skill_lookup: List[Dict] = []

def load_skills():
    """
    Loads skills from CSV and preprocesses them into a lookup
    structure for faster matching.
    """
    global skills_df, skill_lookup
    if not os.path.exists(skills_path):
        print(f"Warning: Skills file not found at {skills_path}")
        return

    skills_df = pd.read_csv(skills_path)
    # Fill NaN values to prevent errors
    skills_df['preferredLabel'] = skills_df['preferredLabel'].fillna('')
    skills_df['altLabels'] = skills_df['altLabels'].fillna('')
    
    temp_lookup = []
    for _, row in skills_df.iterrows():
        skill_id = row["conceptUri"]
        pref_label = row["preferredLabel"]
        
        labels_to_check = set()
        if pref_label:
            labels_to_check.add(pref_label.lower().strip())
        
        # Normalize newline-separated altLabels to semicolon
        alt_labels_raw = str(row["altLabels"])
        alt_labels_normalized = alt_labels_raw.replace("\n", ";")
        alt_labels_list = alt_labels_normalized.split(";")
        
        for alt in alt_labels_list:
            if alt:
                labels_to_check.add(alt.lower().strip())

        # Build a more robust regex pattern
        patterns_for_this_skill = []
        for label in labels_to_check:
            if not label:
                continue
            
            pattern = re.escape(label)
            
            # Add \b (word boundary) ONLY if the label starts/ends
            # with an alphanumeric character.
            prefix = r'\b' if label[0].isalnum() else r''
            suffix = r'\b' if label[-1].isalnum() else r''
            
            patterns_for_this_skill.append(f"{prefix}{pattern}{suffix}")

        if patterns_for_this_skill:
            pattern_text = "|".join(patterns_for_this_skill)
            
            temp_lookup.append({
                "id": skill_id,
                "name": pref_label, 
                "pattern": re.compile(pattern_text, re.IGNORECASE)
            })
    
    skill_lookup = temp_lookup

def _preprocess_text(text: str) -> str:
    """
    Cleans text to make skill extraction more reliable.
    - Splits camelCase: "PythonJava" -> "Python Java"
    - Adds spaces around punctuation: "FastAPI." -> "FastAPI . "
    - Merges multiple spaces
    """
    if not text:
        return ""
    # 1. Add space before uppercase letter (camelCase)
    text = re.sub(r'([a-z])([A-Z])', r'\1 \2', text)
    # 2. Add spaces around punctuation
    text = re.sub(r'([.,!?;:])', r' \1 ', text)
    # 3. Consolidate multiple spaces into one
    text = re.sub(r'\s+', ' ', text)
    return text

# --- MODIFIED: Kept original name, but returns IDs ---
def extract_skills_from_text(text: str) -> List[str]:
    """
    Extracts all unique skill IDs (conceptUri) found in a given text.
    """
    if not skill_lookup:
        load_skills()
        
    found_ids: Set[str] = set()
    if not text:
        return []

    # --- THIS IS THE FIX ---
    # Preprocess the text before searching
    processed_text = _preprocess_text(text)
    # --- END OF FIX ---

    for skill in skill_lookup:
        if skill["pattern"].search(processed_text):
            found_ids.add(skill["id"])
            
    return sorted(list(found_ids))

# --- ADDED: New function to get details for your API response ---
def extract_skills_with_details(text: str) -> List[Dict[str, str]]:
    """
    Extracts skills and returns a list of dicts with 'id' and 'name'.
    Used for the `POST /company/jobs` response.
    """
    if not skill_lookup:
        load_skills()
        
    found_details: Dict[str, str] = {} # Use dict to store id -> name
    if not text:
        return []

    # --- THIS IS THE FIX ---
    # Preprocess the text before searching
    processed_text = _preprocess_text(text)
    # --- END OF FIX ---

    for skill in skill_lookup:
        if skill["id"] not in found_details:
            if skill["pattern"].search(processed_text):
                found_details[skill["id"]] = skill["name"]
    
    # Convert dict to list of dicts
    return [{"id": k, "name": v} for k, v in found_details.items()]


load_skills()
