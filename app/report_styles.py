"""Copy Word styles from the selected template, including generated subdocuments."""

from docx import Document
from project_paths import TEMPLATE_PATH
from copy import deepcopy
from docx.oxml.ns import qn


def copy_template_styles(source, target, *, replace=True):
    source_styles, target_styles = source.styles.element, target.styles.element
    # docxtpl's generated subdocument can share the template's document part.
    if source_styles is target_styles:
        return
    existing = {style.get(qn('w:styleId')):style for style in target_styles}
    for style in source_styles:
        if style.tag != qn('w:style'):
            continue
        key = style.get(qn('w:styleId'))
        previous = existing.get(key)
        if previous is not None:
            if not replace:
                continue
            target_styles.remove(previous)
        target_styles.append(deepcopy(style))


def ensure_template_styles(document, names):
    if any(name not in document.styles for name in names):
        copy_template_styles(Document(TEMPLATE_PATH),document,replace=False)
