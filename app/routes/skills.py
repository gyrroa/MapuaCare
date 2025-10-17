from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import select, func, or_
from typing import Optional
from .. import models, schemas, database

router = APIRouter(prefix="/skills", tags=["skills"])

def get_db():
    db = database.SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.post("", response_model=schemas.SkillRead)
def create_skill(skill: schemas.SkillCreate, db: Session = Depends(get_db)):
    s = models.Skill(**skill.model_dump())
    db.add(s)
    db.commit()
    db.refresh(s)
    return s

@router.get("/{skill_id}", response_model=schemas.SkillRead)
def get_skill(skill_id: int, db: Session = Depends(get_db)):
    s = db.get(models.Skill, skill_id)
    if not s:
        raise HTTPException(404, "Skill not found")
    return s

@router.get("", response_model=schemas.PageSkill)
def list_skills(
    db: Session = Depends(get_db),
    q: Optional[str] = Query(None, description="search by label"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=200),
):
    stmt = select(models.Skill)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(models.Skill.preferred_label.ilike(like),
                              models.Skill.alt_labels.ilike(like)))
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    items = db.execute(
        stmt.order_by(models.Skill.skill_id.asc())
            .offset((page - 1) * per_page)
            .limit(per_page)
    ).scalars().all()
    return schemas.PageSkill(meta=schemas.PageMeta(page=page, per_page=per_page, total=total or 0), items=items)

@router.put("/{skill_id}", response_model=schemas.SkillRead)
def update_skill(skill_id: int, patch: schemas.SkillUpdate, db: Session = Depends(get_db)):
    s = db.get(models.Skill, skill_id)
    if not s:
        raise HTTPException(404, "Skill not found")
    for f in ["preferred_label", "alt_labels"]:
        v = getattr(patch, f)
        if v is not None:
            setattr(s, f, v)
    db.commit()
    db.refresh(s)
    return s

@router.delete("/{skill_id}", status_code=204)
def delete_skill(skill_id: int, db: Session = Depends(get_db)):
    s = db.get(models.Skill, skill_id)
    if not s:
        raise HTTPException(404, "Skill not found")
    db.delete(s)
    db.commit()
