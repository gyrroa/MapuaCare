import os
import sys
import pandas as pd
import re
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

# --- Add the project's root directory to the system path ---
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(project_root)

# Now, we import the components we need directly
from app.database import Base
from app.models import Skill
from app.config import settings

# --- RE-CREATE DB CONNECTION LOCALLY ---
engine = create_engine(settings.DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
# --- END OF RE-CREATION ---


def format_alt_labels(alt_labels_str: str) -> str:
    """
    Cleans and formats alt_labels from CSV.
    """
    if not alt_labels_str or pd.isna(alt_labels_str):
        return None
    
    # Split by newline or semicolon
    labels = re.split(r'[\n;]', alt_labels_str)
    # Clean, lowercase, and remove duplicates
    cleaned_labels = {label.strip().lower() for label in labels if label and label.strip()}
    
    if not cleaned_labels:
        return None
    
    # --- THIS IS THE FIX ---
    # Return in the format ;label1;label2;
    # (It now correctly joins with a semicolon ';')
    return f";{';'.join(sorted(cleaned_labels))};"
    # --- END OF BUG FIX ---

def seed_skills(test_rows: int = None): # <-- Added parameter
    """
    Reads skills_esco.csv and populates the skills table in the database.
    """
    # Get the path to the CSV file
    base_dir = os.path.dirname(os.path.abspath(__file__))
    skills_path = os.path.join(base_dir, "data", "skills_esco.csv")

    if not os.path.exists(skills_path):
        print(f"Error: Could not find skills_esco.csv at {skills_path}")
        return

    print("Connecting to database...")
    db = SessionLocal()
    
    try:
        # --- MODIFIED FOR TESTING ---
        if test_rows:
            print(f"--- RUNNING IN TEST MODE: Processing only {test_rows} rows. ---")
        else:
            # Check if skills are already seeded in non-test mode
            existing_skill_count = db.query(Skill).count()
            if existing_skill_count > 0:
                print(f"Database already has {existing_skill_count} skills. Seed script will not run.")
                print("To re-run, please manually clear the 'skills' table in your database.")
                return
        # --- END OF MODIFICATION ---

        print(f"Reading {skills_path}...")
        # --- MODIFIED FOR TESTING ---
        df = pd.read_csv(skills_path, nrows=test_rows) # <-- Use nrows
        # --- END OF MODIFICATION ---

        # Add a progress indicator
        total_skills = len(df)
        print(f"Found {total_skills} total skills to process. Starting...")
        
        new_skills = 0
        skipped_skills = 0
        
        for index, row in df.iterrows():
        
            if (index + 1) % 100 == 0: # Print every 100 in case test_rows is large
                sys.stdout.write(f"  ... Processed {index + 1} / {total_skills} skills\r")
                sys.stdout.flush()

            if pd.isna(row.get('conceptUri')) or pd.isna(row.get('preferredLabel')):
                continue

            # Check if this skill already exists (by conceptUri)
            exists = db.scalar(
                select(Skill).where(Skill.concept_uri == row['conceptUri'])
            )
            
            if not exists:
                # Format alt_labels correctly
                alt_labels = format_alt_labels(row.get('altLabels'))
                
                new_skill = Skill(
                    concept_uri=row['conceptUri'],
                    preferred_label=row['preferredLabel'],
                    alt_labels=alt_labels
                )
                db.add(new_skill)
                new_skills += 1
            else:
                skipped_skills += 1
        
        # Print a final newline to clear the progress bar
        print(f"\nFinished processing. Found {new_skills} new skills to add.")
        if skipped_skills > 0:
            print(f"Skipped {skipped_skills} skills that already exist in the database.")
        
        if new_skills > 0:
            print(f"Committing {new_skills} new skills to the database...")
            db.commit()
            print("Database seeding complete!")
        else:
            print("No new skills to add.")

    except Exception as e:
        print(f"An error occurred: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    print("Starting skill database seeding...")
    
    # Check if a command-line argument for test rows was passed
    test_mode_rows = None
    if len(sys.argv) > 1:
        try:
            test_mode_rows = int(sys.argv[1])
            if test_mode_rows <= 0:
                test_mode_rows = None
        except ValueError:
            print(f"Usage: python app/seed_db.py [number_of_rows_to_test]")
            print("Running in full mode (will not run if DB is populated)...")
    
    # We must create the tables first if they don't exist
    Base.metadata.create_all(bind=engine)
    
    seed_skills(test_rows=test_mode_rows) # <-- Pass the number of rows