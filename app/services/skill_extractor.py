import pandas as pd
import os

base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
skills_path = os.path.join(base_dir, "data", "skills_esco.csv")

if os.path.exists(skills_path):
    skills_df = pd.read_csv(skills_path)
else:
    skills_df = pd.DataFrame(columns=["conceptUri", "preferredLabel", "altLabels"])

def extract_skills_from_text(text: str):
    found = []
    if skills_df.empty:
        return found
    tl = (text or "").lower()
    for _, row in skills_df.iterrows():
        labels = [row.get("preferredLabel", "")] + str(row.get("altLabels", "")).split(";")
        for label in labels:
            if label and label.lower() in tl:
                found.append(row.get("preferredLabel", ""))
                break
    return sorted(set([s for s in found if s]))
