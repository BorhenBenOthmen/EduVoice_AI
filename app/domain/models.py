from pydantic import BaseModel
from typing import List, Optional

class Student(BaseModel):
    name: str = "Student"
    grade_level: str = "primary_4"
    primary_language: str = "Arabic"
    course_names: List[str] = []
