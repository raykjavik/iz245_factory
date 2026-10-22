from docxtpl import DocxTemplate
from pathlib import Path


TEMPLATE_PATH = Path(__file__) / "template.docx"




report = DocxTemplate("template.docx")
report.render(
    {
        "month": "October 2026",
        "revenue": "€125,000",
        "summary": "Revenue increased by 12% over September.",
    },
    autoescape=True,
)
report.save("report.docx")