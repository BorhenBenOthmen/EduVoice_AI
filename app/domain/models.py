from pydantic import BaseModel
from typing import List

class Student(BaseModel):
    name: str = "Student"
    grade_level: str = "primary_6"
    course_names: List[str] = []
