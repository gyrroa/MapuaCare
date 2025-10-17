from .users import router as users
from .candidates import router as candidates
from .companies import router as companies
from .skills import router as skills
from .matching import router as matching

__all__ = ["users", "candidates", "companies", "skills", "matching"]
