import os
from app.domain.models import Student

# Define path to prompts folder
PROMPTS_DIR = os.path.join(os.path.dirname(__file__), "prompts")

# Load base prompt
with open(os.path.join(PROMPTS_DIR, "base.txt"), "r", encoding="utf-8") as f:
    BASE_PROMPT = f.read()

# Load grade blocks
with open(os.path.join(PROMPTS_DIR, "primary.txt"), "r", encoding="utf-8") as f:
    GRADE_BLOCK_PRIMARY = f.read()

with open(os.path.join(PROMPTS_DIR, "middle.txt"), "r", encoding="utf-8") as f:
    GRADE_BLOCK_MIDDLE = f.read()

with open(os.path.join(PROMPTS_DIR, "secondary_1.txt"), "r", encoding="utf-8") as f:
    GRADE_BLOCK_SEC_1_TRONC_COMMUN = f.read()

with open(os.path.join(PROMPTS_DIR, "secondary_2_3_lettres.txt"), "r", encoding="utf-8") as f:
    GRADE_BLOCK_SEC_2_3_LETTRES = f.read()

with open(os.path.join(PROMPTS_DIR, "bac.txt"), "r", encoding="utf-8") as f:
    GRADE_BLOCK_SEC_4_BAC_LETTRES = f.read()

# Grade Profile Mapping
GRADE_PROFILES = {
    # Primary
    "primary_4":            GRADE_BLOCK_PRIMARY,
    "primary_5":            GRADE_BLOCK_PRIMARY,
    "primary_6":            GRADE_BLOCK_PRIMARY,
    # Middle school
    "middle_7":             GRADE_BLOCK_MIDDLE,
    "middle_8":             GRADE_BLOCK_MIDDLE,
    "middle_9":             GRADE_BLOCK_MIDDLE,
    # Secondary — tronc commun
    "secondary_1":          GRADE_BLOCK_SEC_1_TRONC_COMMUN,
    # Secondary — Lettres track (years 2 and 3 share a profile)
    "secondary_2_lettres":  GRADE_BLOCK_SEC_2_3_LETTRES,
    "secondary_3_lettres":  GRADE_BLOCK_SEC_2_3_LETTRES,
    # Secondary — Bac Lettres (year 4, final year)
    "secondary_4_lettres":  GRADE_BLOCK_SEC_4_BAC_LETTRES,
}

# Grade Labels Mapping
GRADE_LABELS = {
    "primary_4":            {"fr": "4ème année primaire",             "ar": "السنة الرابعة ابتدائي"},
    "primary_5":            {"fr": "5ème année primaire",             "ar": "السنة الخامسة ابتدائي"},
    "primary_6":            {"fr": "6ème année primaire",             "ar": "السنة السادسة ابتدائي"},
    "middle_7":             {"fr": "7ème année de base",              "ar": "السنة السابعة أساسي"},
    "middle_8":             {"fr": "8ème année de base",              "ar": "السنة الثامنة أساسي"},
    "middle_9":             {"fr": "9ème année de base",              "ar": "التاسعة أساسي"},
    "secondary_1":          {"fr": "1ère année secondaire",           "ar": "السنة الأولى ثانوي"},
    "secondary_2_lettres":  {"fr": "2ème année secondaire — Lettres", "ar": "السنة الثانية ثانوي — شعبة الآداب"},
    "secondary_3_lettres":  {"fr": "3ème année secondaire — Lettres", "ar": "السنة الثالثة ثانوي — شعبة الآداب"},
    "secondary_4_lettres":  {"fr": "4ème année secondaire — Bac Lettres", "ar": "السنة الرابعة ثانوي — بكالوريا آداب"},
}

# Mapping from Mobile/Django names to internal keys
WEB_TO_INTERNAL_GRADE_MAP = {
    "Bac Lettres": "secondary_4_lettres",
    "Primary 4": "primary_4",
    "Primary 5": "primary_5",
    "Primary 6": "primary_6",
    "4ème année primaire": "primary_4",
    "5ème année primaire": "primary_5",
    "6ème année primaire": "primary_6",
    "1ère année secondaire": "secondary_1",
    "2ème année secondaire — Lettres": "secondary_2_lettres",
    "3ème année secondaire — Lettres": "secondary_3_lettres",
    "4ème année secondaire — Bac Lettres": "secondary_4_lettres",
}

def build_system_instruction(student: Student, curriculum_context: str = "") -> str:
    """Builds the final system prompt based on the student's persona."""
    grade = student.grade_level

    # Try to map friendly name to internal key if needed
    if grade in WEB_TO_INTERNAL_GRADE_MAP:
        grade = WEB_TO_INTERNAL_GRADE_MAP[grade]

    if grade not in GRADE_LABELS:
        grade = "primary_4"  # Fallback if unknown

    label_fr = GRADE_LABELS[grade]["fr"]
    label_ar = GRADE_LABELS[grade]["ar"]
    label = f"{label_fr} / {label_ar}"
    profile = GRADE_PROFILES.get(grade, GRADE_BLOCK_MIDDLE)
    courses = ", ".join(student.course_names) if student.course_names else "enrolled courses"

    return BASE_PROMPT.format(
        student_name=student.name,
        grade_level_label=label,
        enrolled_courses=courses,
        GRADE_PROFILE_BLOCK=profile.format(grade_level_label=label),
    )
