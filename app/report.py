"""Combine named template fields with Word sections authored in cfg_* modules."""

from docx import Document
from docx.shared import RGBColor
from project_paths import CALIB_DIR, TEST_DIR
from measurement import IFSpectrumMeasurement
from project_paths import TEMPLATE_PATH
from report_styles import copy_template_styles
from dataclasses import asdict
from pathlib import Path
from io import BytesIO
from docxtpl import DocxTemplate
from measurement import SweepMeasurement, NoiseDensityMeasurement, IP3Measurement, IP3_ARRAY_FIELDS
from verification import evaluate_verification, evaluate_test5, evaluate_test6, evaluate_test7
import cfg_calib
import cfg_test1
import cfg_test2
import cfg_test3
import cfg_test4
import cfg_test_5_6
import cfg_test_7
import cfg_test8


DEFAULT_SECTIONS = ('test1', 'test2', 'test3', 'test4', 'test5_6', 'test7', 'test8')


def default_template(path):
    """Use the supplied template, or a small built-in template when absent."""
    path = Path(path)
    if path.is_file():
        return DocxTemplate(path)
    document = Document()
    document.styles['Title'].font.color.rgb = RGBColor(0, 0, 0)
    for border in document.styles['Title'].element.xpath('.//w:pBdr'):
        border.getparent().remove(border)
    document.add_heading('Receiver verification report', level=0)
    document.add_paragraph('Project {{ project_name }}')
    document.add_paragraph('Receiver serial number {{ serial_number }}')
    document.add_paragraph('Operator {{ settings.operator }}')
    document.add_paragraph('{{p generated_report }}')
    buffer = BytesIO()
    document.save(buffer)
    buffer.seek(0)
    return DocxTemplate(buffer)


def load_measurements(project):
    """Read each saved file once. Domain report functions receive result objects."""
    def read(configs, result_class, directory):
        return [(filename, result_class.from_file(project.root/directory/filename))
                for filename in configs if (project.root/directory/filename).is_file()]
    return {
        'calibration': read({**cfg_calib.CFG_CALIB_RF1, **cfg_calib.CFG_PCALIB,
                             **cfg_calib.CFG_CALIB_RF2}, SweepMeasurement, CALIB_DIR),
        'test1': read({**cfg_test1.CFG_TEST1_RF1, **cfg_test1.CFG_TEST1_RF2}, SweepMeasurement, TEST_DIR),
        'test2': read({**cfg_test2.CFG_TEST2, **cfg_test2.CFG_TEST2_RF2}, SweepMeasurement, TEST_DIR),
        'test3': read(cfg_test3.CFG_TEST3, SweepMeasurement, TEST_DIR),
        'test4': read(cfg_test4.CFG_TEST4, SweepMeasurement, TEST_DIR),
        'test5_6': read(cfg_test_5_6.CFG_NOISE_DENSITY, NoiseDensityMeasurement, TEST_DIR),
        'test8': read(cfg_test8.CFG_TEST8, IFSpectrumMeasurement, TEST_DIR),
        'test7': read({**cfg_test_7.CFG_TEST7_RF1, **cfg_test_7.CFG_TEST7_RF2}, IP3Measurement, TEST_DIR),
    }


def _verification_context(groups):
    """Legacy field-based template variables remain available."""
    sweeps = []
    for group in ('test1', 'test2', 'test3', 'test4'):
        for filename, result in groups[group]:
            points = [] if result.limit_dB is None else [
                dict(frequency_hz=float(f), value=float(v)) for f,v in zip(result.freq_hz,result.limit_dB)]
            sweeps.append(dict(name=result.name,filename=filename,unit=result.unit,
                datetime=result.datetime,operator=result.operator,temperature=result.temperature,
                reference_dbm=result.reference_dbm,dwell_sec=result.dwell_sec,
                bandwidth_hz=result.bandwidth_hz,passed=evaluate_verification(result),points=points))
    density = []
    for filename,result in groups['test5_6']:
        density.append(dict(name=result.name,filename=filename,carrier_hz=result.carrier_hz,
            unit=result.unit,datetime=result.datetime,operator=result.operator,ffts=result.ffts,
            sample_rate_hz=result.sample_rate_hz,window_samples=result.window_samples,
            overlap=result.overlap,reference_dbm=result.reference_dbm,
            phase_passed=evaluate_test5(result),amplitude_passed=evaluate_test6(result),
            offset_hz=result.offset_hz,phase_noise=result.phase_noise,amplitude_noise=result.amplitude_noise))
    ip3 = []
    for filename,result in groups['test7']:
        points = [dict(zip(IP3_ARRAY_FIELDS,map(float,values))) for values in zip(
            *(getattr(result,field) for field in IP3_ARRAY_FIELDS))]
        ip3.append(dict(name=result.name,filename=filename,datetime=result.datetime,
            operator=result.operator,temperature=result.temperature,passed=evaluate_test7(result),
            tone_spacing_hz=result.tone_spacing_hz,noise_bandwidth_db=result.noise_bandwidth_db,
            per_tone_headroom_db=result.per_tone_headroom_db,points=points))
    if_spectra = [dict(name=result.name,filename=filename,unit=result.unit,
        datetime=result.datetime,operator=result.operator,carrier_hz=result.carrier_hz,
        if_bandwidth_hz=result.if_bandwidth_hz,sample_rate_hz=result.sample_rate_hz,
        window_samples=result.window_samples,overlap=result.overlap,ffts=result.ffts,
        passed=cfg_test8.evaluate_test8(result),offset_hz=result.offset_hz,power_db=result.power_db)
        for filename,result in groups['test8']]
    return dict(if_spectrum_measurements=if_spectra,
        if_spectrum_by_name={Path(item['filename']).stem:item for item in if_spectra},
        verification_measurements=sweeps,
        verification_by_name={Path(item['filename']).stem:item for item in sweeps},
        noise_density_measurements=density,
        noise_density_by_name={Path(item['filename']).stem:item for item in density},
        ip3_measurements=ip3,ip3_by_name={Path(item['filename']).stem:item for item in ip3})


def verification_context(project):
    return _verification_context(load_measurements(project))


def add_generated_sections(document, groups, sections):
    """The order is explicit; content is owned by each domain module."""
    if 'test1' in sections:
        cfg_test1.add_report(document, [result for _,result in groups['test1']])
    if 'test2' in sections:
        cfg_test2.add_report(document, [result for _,result in groups['test2']])
    if 'test3' in sections:
        cfg_test3.add_report(document, [result for _,result in groups['test3']])
    if 'test4' in sections:
        cfg_test4.add_report(document, [result for _,result in groups['test4']])
    if 'test5_6' in sections:
        cfg_test_5_6.add_report(document, [result for _,result in groups['test5_6']])
    if 'test7' in sections:
        cfg_test_7.add_report(document, [result for _,result in groups['test7']])
    if 'test8' in sections:
        cfg_test8.add_report(document, [result for _,result in groups['test8']])


def render_reports(project, *, template=None, template_path=None, output_path=None, sections=None):
    """Fill {{ fields }} and generate Word sections, then atomically save .docx.

    {{p generated_report }} in its own template paragraph selects insertion.
    Without that tag, generated sections are appended after template rendering.
    """
    template = template if template is not None else default_template(template_path or TEMPLATE_PATH)
    groups = load_measurements(project)
    if sections is None:
        sections = DEFAULT_SECTIONS
    else:
        sections = tuple(sections)
    unknown = set(sections)-{'calibration',*DEFAULT_SECTIONS}
    if unknown:
        raise ValueError('Unknown report sections: '+', '.join(sorted(unknown)))
    automatic = project.prop_auto.to_dict()
    context = {**project.prop_manual, **automatic, 'prop_auto':automatic,
               'settings':asdict(project.settings), 'project_name':project.name}
    context.update(_verification_context(groups))
    has_anchor = 'generated_report' in template.get_undeclared_template_variables()
    if has_anchor:
        subdocument = template.new_subdoc()
        # Size generated charts/tables for the destination template's page.
        source = template.docx.sections[-1]
        target = subdocument.sections[-1]
        for attribute in ('page_width', 'page_height', 'left_margin', 'right_margin',
                          'top_margin', 'bottom_margin'):
            setattr(target, attribute, getattr(source, attribute))
        copy_template_styles(template.docx, subdocument)
        add_generated_sections(subdocument, groups, sections)
        context['generated_report'] = subdocument
    template.render(context, autoescape=True)
    if not has_anchor:
        # get_docx() reloads the original template after render in docxtpl.
        add_generated_sections(template.docx, groups, sections)
    output = Path(output_path) if output_path is not None else project.report_file
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name+'.tmp')
    try:
        template.save(temporary)
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)
    return output
