"""
Educational templates: concept → example → summary.
Phase 4.
"""
from dataclasses import dataclass


@dataclass
class EducationalSegment:
    """One segment in an educational template."""
    label: str  # "concept" | "example" | "summary"
    suggested_text: str
    position: str = "center"
    font_size: int = 48


# Template: list of segments with suggested text patterns
EDUCATIONAL_TEMPLATES: dict[str, list[EducationalSegment]] = {
    "concept_example_summary": [
        EducationalSegment("concept", "Concept", position="top", font_size=36),
        EducationalSegment("example", "Example", position="center", font_size=42),
        EducationalSegment("summary", "Summary", position="bottom", font_size=36),
    ],
    "tutorial": [
        EducationalSegment("step", "Step 1", position="top", font_size=32),
        EducationalSegment("content", "Content", position="center", font_size=44),
    ],
    "explainer": [
        EducationalSegment("title", "Title", position="top", font_size=40),
        EducationalSegment("detail", "Detail", position="center", font_size=38),
    ],
}


def get_educational_template(
    template_name: str,
    topic: str = "",
    step: int = 1,
) -> list[EducationalSegment]:
    """
    Return educational segments for a template.
    topic: e.g. "Machine Learning"
    step: for tutorial, the step number.
    """
    tpl = EDUCATIONAL_TEMPLATES.get(template_name, EDUCATIONAL_TEMPLATES["explainer"])
    out: list[EducationalSegment] = []
    for seg in tpl:
        text = seg.suggested_text
        if topic and "Concept" in text:
            text = f"{topic}"
        elif topic and "Title" in text:
            text = f"{topic}"
        elif "Step" in text:
            text = f"Step {step}"
        out.append(
            EducationalSegment(
                label=seg.label,
                suggested_text=text or seg.suggested_text,
                position=seg.position,
                font_size=seg.font_size,
            )
        )
    return out
