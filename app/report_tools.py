"""Small Word/plot helpers. Domain modules decide content and presentation."""

from docx.shared import RGBColor
from report_styles import ensure_template_styles
from docx.shared import Pt
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from matplotlib.figure import Figure
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.ticker import EngFormatter, MaxNLocator
from docx.shared import Inches
from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from report_styles import copy_template_styles
from matplotlib.ticker import LogLocator
from matplotlib.ticker import FixedLocator
from project_paths import TEMPLATE_PATH
from io import BytesIO
import numpy as np
from chart_style import result_color, LIMIT_COLOR
from chart_ranges import data_x_range, clipped_x_range, visible_y_range, Y_MARGIN

REPORT_AXIS_LABEL_FONT_SIZE = 9
REPORT_TICK_FONT_SIZE = 8
REPORT_LEGEND_FONT_SIZE = 7


def add_test_heading(document, title, description):
    for name in ('Heading 2', 'Heading 3'):
        document.styles[name].font.color.rgb = RGBColor(0, 0, 0)
    document.add_heading(title, level=2)
    paragraph = document.add_paragraph(description)
    paragraph.paragraph_format.keep_with_next = True


def add_measurement_heading(document, measurement, *, title=None, passed=None):
    title = title or measurement.name.replace('_', ' ')
    document.add_heading(title, level=3)
    state = 'Passed' if passed is True else 'Failed' if passed is False else 'Not evaluated'
    stamp = measurement.datetime or 'not recorded'
    ensure_template_styles(document,('Sweep Metadata',))
    paragraph = document.add_paragraph(f'{state} | UTC {stamp}', style='Sweep Metadata')
    paragraph.paragraph_format.keep_with_next = True


def add_table(document, headers, rows, *, style=None, text_style=None, header_style=None):
    if style is not None:
        return _add_template_table(document,headers,rows,style,text_style,header_style)
    if document.paragraphs:
        document.paragraphs[-1].paragraph_format.keep_with_next = True
    table = document.add_table(rows=1, cols=len(headers))
    table.autofit = False
    section = document.sections[-1]
    width = (section.page_width-section.left_margin-section.right_margin) / len(headers)
    for cell, header in zip(table.rows[0].cells, headers):
        cell.text = str(header)
    repeat = OxmlElement('w:tblHeader')
    table.rows[0]._tr.get_or_add_trPr().append(repeat)
    for values in rows:
        cells = table.add_row().cells
        for cell, value in zip(cells, values):
            cell.text = f'{value:.6g}' if isinstance(value, (float, np.floating)) else str(value)
    for row_index, row in enumerate(table.rows):
        for cell in row.cells:
            cell.width = int(width)
            cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
            properties = cell._tc.get_or_add_tcPr()
            borders = OxmlElement('w:tcBorders')
            for edge in ('top', 'left', 'bottom', 'right'):
                border = OxmlElement(f'w:{edge}')
                for key, value in (('val','single'), ('sz','4'), ('color','D9D9D9')):
                    border.set(qn('w:'+key), value)
                borders.append(border)
            properties.append(borders)
            if row_index == 0:
                shading = OxmlElement('w:shd')
                shading.set(qn('w:fill'), 'DCE6F1')
                properties.append(shading)
            for paragraph in cell.paragraphs:
                paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
                paragraph.paragraph_format.space_before = Pt(4)
                paragraph.paragraph_format.space_after = Pt(4)
                for run in paragraph.runs:
                    run.font.size = Pt(9)
                    run.bold = row_index == 0
    document.add_paragraph()
    return table


def add_chart(document, x, series, *, ylabel, xlabel='Frequency (Hz)', log_x=True, limits=None, colors=None, y_padding=None, passed=None, x_limits=None, vertical_limits=None, x_ticks=None):
    """series maps legend labels to arrays. Export a static plot, not Qt widgets."""
    figure = Figure(figsize=(6.2, 2.8), dpi=180, layout='constrained')
    FigureCanvasAgg(figure)
    axis = figure.add_subplot()
    x = np.asarray(x)
    plotted_curves = []
    for name, values in series.items():
        values = np.asarray(values)
        mask = np.isfinite(x) & np.isfinite(values)
        if log_x:
            mask &= x > 0
        indices = np.flatnonzero(mask)
        if len(indices) > 5000:
            indices = indices[np.linspace(0,len(indices)-1,5000,dtype=int)]
        axis.plot(x[indices], values[indices], label=name, linewidth=1.1,
                  color=result_color(passed))
        plotted_curves.append((x[indices], values[indices]))
    if log_x:
        axis.set_xscale('log')
    else:
        axis.xaxis.set_major_locator(MaxNLocator(6))
    axis.xaxis.set_major_formatter(EngFormatter(sep=''))
    axis.yaxis.set_major_locator(MaxNLocator(6))
    axis.set_xlabel(xlabel, fontsize=REPORT_AXIS_LABEL_FONT_SIZE)
    axis.set_ylabel(ylabel, fontsize=REPORT_AXIS_LABEL_FONT_SIZE)
    axis.tick_params(axis='both', which='both', labelsize=REPORT_TICK_FONT_SIZE)
    axis.xaxis.get_offset_text().set_fontsize(REPORT_TICK_FONT_SIZE)
    axis.yaxis.get_offset_text().set_fontsize(REPORT_TICK_FONT_SIZE)
    axis.grid(True, which='both', alpha=.22)
    if limits is not None:
        for bound in limits:
            axis.axhline(bound, color=LIMIT_COLOR, linestyle='--', linewidth=.8)
    for position in vertical_limits or ():
        axis.axvline(position,color=LIMIT_COLOR,linestyle='--',linewidth=.8)
    if x_limits is not None:
        if log_x:
            axis.xaxis.set_major_locator(LogLocator(base=10,subs=(1.,)))
        axis.xaxis.set_major_formatter(EngFormatter(unit='Hz',sep=''))
    bounds = clipped_x_range(data_x_range(plotted_curves, log_x=log_x), x_limits)
    if bounds is not None:
        if bounds[0] < bounds[1]:
            axis.set_xlim(*bounds)
        y_bounds = visible_y_range(plotted_curves, *bounds, log_x=log_x,
                                   limits=limits if limits is not None else ())
        if y_bounds is not None:
            low, high = y_bounds
            padding = Y_MARGIN if y_padding is None else y_padding
            margin = (high-low)*padding
            axis.set_ylim(low-margin, high+margin)
    if x_ticks is not None:
        # Set the locator after the data bounds; set_xticks would expand xlim.
        low, high = axis.get_xlim()
        visible_ticks = [tick for tick in x_ticks if low <= tick <= high]
        if visible_ticks:
            axis.xaxis.set_major_locator(FixedLocator(visible_ticks))
            axis.xaxis.set_major_formatter(EngFormatter(sep=''))
    if len(series) > 1:
        axis.legend(fontsize=REPORT_LEGEND_FONT_SIZE)
    buffer = BytesIO()
    figure.savefig(buffer, format='png')
    buffer.seek(0)
    section = document.sections[-1]
    width = min(Inches(6.2), section.page_width-section.left_margin-section.right_margin)
    if document.paragraphs:
        document.paragraphs[-1].paragraph_format.keep_with_next = True
    picture = document.add_picture(buffer, width=width)
    picture._inline.docPr.set('descr', f'{ylabel} versus {xlabel}')
    document.paragraphs[-1].paragraph_format.space_after = Pt(12)
    return buffer


def no_measurements(document):
    document.add_heading('Results', level=3)
    document.add_paragraph('No saved measurements are available for this test.')


def _add_template_table(document, headers, rows, style, text_style, header_style):
    """Typography, colors, borders and cell padding come only from template styles."""
    if any(name not in document.styles for name in (style,text_style,header_style)):
        copy_template_styles(Document(TEMPLATE_PATH), document, replace=False)
    table = document.add_table(rows=1,cols=len(headers))
    table.style = style
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    section = document.sections[-1]
    width = section.page_width-section.left_margin-section.right_margin
    weights = [1] + [1.05]*(len(headers)-1)
    for column,weight in zip(table.columns,weights):
        column.width = int(width*weight/sum(weights))
    repeat = OxmlElement('w:tblHeader')
    table.rows[0]._tr.get_or_add_trPr().append(repeat)
    for cell,header in zip(table.rows[0].cells,headers):
        cell.text = str(header)
        cell.paragraphs[0].style = header_style
    for values in rows:
        for cell,value in zip(table.add_row().cells,values):
            cell.text = str(value)
            cell.paragraphs[0].style = text_style
    for row in table.rows:
        row._tr.get_or_add_trPr().append(OxmlElement('w:cantSplit'))
        for cell,column in zip(row.cells,table.columns):
            cell.width = column.width
    document.add_paragraph()
    return table
