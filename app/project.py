"""Manual template fields, DUT properties, project persistence, and reports."""
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from collections.abc import Mapping
import json
from docxtpl import DocxTemplate
from cfg_test3 import PRESELECTOR_POWER_DBM
import numpy as np
def read_cable_calibration(path):
    from iz245.cable_calibration import read_cable_calibration as read
    return read(path)

CALIB_DIR = "calib"
TEST_DIR = "tests"
TEMPLATE_PATH = Path(__file__).parent / "template.docx"
MANUAL_KEYS_PREFIX = "prj_"
PROJECT_SUFFIX = ".prj"
# Set your usual .prj path here, or None to disable startup loading.
DEFAULT_PROJECT_PATH: Path | None = Path(__file__).resolve().parent.parent / "iz245_first_d" / "iz245_1stD.prj"


def default_template():
    from report import default_template as create_template
    return create_template(TEMPLATE_PATH)


def manual_keys():
    return sorted(f for f in default_template().get_undeclared_template_variables()
                  if f.startswith((MANUAL_KEYS_PREFIX, "pjr_")))


def format_manual_key(key):
    for prefix in (MANUAL_KEYS_PREFIX, "pjr_"):
        if key.startswith(prefix):
            key = key[len(prefix):]
            break
    return key.replace("_", " ").capitalize()


@dataclass
class AutoProps:
    dut_ip: str = "10.0.1.245"
    serial_number: str = ""
    calibration_temperature: str = ""
    ver_hw: str = ""
    ver_hw_rf: str = ""
    ver_hw_fpga: str = ""
    ver_fpga: str = ""
    ver_fw: str = ""
    cable_calib_path: Path | None = None
    operator: str = "VHU"

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, Mapping):
            raise ValueError("Automatic properties must be an object.")
        allowed = {f.name for f in fields(cls)}
        unknown = set(data) - allowed
        if unknown:
            raise ValueError(f"Unknown automatic properties: {', '.join(sorted(unknown))}")
        values = {key: "" if value is None else str(value) for key, value in data.items()
                  if key != 'cable_calib_path'}
        cable_path = data.get('cable_calib_path')
        values['cable_calib_path'] = Path(cable_path) if cable_path else None
        return cls(**values)

    def to_dict(self):
        data = asdict(self)
        data['cable_calib_path'] = str(self.cable_calib_path) if self.cable_calib_path is not None else None
        return data


def default_test8_ffts():
    from cfg_test8 import CFG_TEST8
    return {spec.filter_label:spec.ffts for spec in CFG_TEST8.values()}


@dataclass
class MeasurementSettings:
    operator: str = 'VHU'
    dut_ip: str = '10.0.1.245'
    generator_ip: str = '10.0.1.54'
    generator_port: int = 5025
    ip3_generator_ip: str = ''
    ip3_generator_port: int = 5025
    ip3_headroom_db: float = 3.01029995664
    ip3_noise_dwell_sec: float = 1.0
    ip3_signal_dwell_sec: float = 0.1
    ip3_attenuator_db: float = 0.0
    cable_calib_path: str = ''
    attenuator_db: float = 0.0
    noise_ffts: int = 50
    test8_ffts: dict[str,int] = field(default_factory=default_test8_ffts)
    calibration_power_dbm: float = -40.0
    verification_power_dbm: float = -50.0
    preselector_power_dbm: float = PRESELECTOR_POWER_DBM
    calibration_dwell_sec: float = 0.1
    verification_dwell_sec: float = 0.1

    @classmethod
    def from_dict(cls, data):
        defaults = cls()
        for name in ('operator', 'dut_ip', 'generator_ip', 'ip3_generator_ip', 'cable_calib_path'):
            if name in data:
                setattr(defaults, name, str(data[name]))
        defaults.generator_port = int(data.get('generator_port', defaults.generator_port))
        defaults.ip3_generator_port = int(data.get('ip3_generator_port', defaults.ip3_generator_port))
        defaults.noise_ffts = int(data.get('noise_ffts',defaults.noise_ffts))
        averages=data.get('test8_ffts',defaults.test8_ffts)
        if isinstance(averages,Mapping):
            defaults.test8_ffts.update({label:int(count) for label,count in averages.items()})
        else:
            defaults.test8_ffts={label:int(averages) for label in defaults.test8_ffts}
        for name in ('calibration_dwell_sec', 'verification_dwell_sec',
                     'ip3_headroom_db', 'ip3_noise_dwell_sec', 'ip3_signal_dwell_sec',
                     'ip3_attenuator_db', 'attenuator_db', 'calibration_power_dbm', 'verification_power_dbm', 'preselector_power_dbm'):
            setattr(defaults, name, float(data.get(name, getattr(defaults, name))))
        return defaults


@dataclass
class FactoryProject:
    name: str
    prop_manual: dict
    root: Path
    prop_auto: AutoProps = field(default_factory=AutoProps)
    settings: MeasurementSettings = field(default_factory=MeasurementSettings)
    cable_calib: tuple[np.ndarray, np.ndarray] | None = field(default=None, init=False, repr=False)
    cable_calib_error: str = field(default='', init=False)

    def load_cable_calibration(self):
        self.cable_calib = None
        self.cable_calib_error = ''
        path = self.settings.cable_calib_path
        if not path:
            return
        path = Path(path).expanduser()
        if not path.is_absolute():
            path = self.root / path
        self.settings.cable_calib_path = str(path.resolve())
        self.prop_auto.cable_calib_path = path.resolve()
        try:
            self.cable_calib = read_cable_calibration(path)
        except (OSError, ValueError, ImportError) as exc:
            self.cable_calib_error = str(exc)

    def set_cable_calibration(self, path: Path | None):
        # Validate before replacing a previously valid selection.
        resolved = Path(path).expanduser().resolve() if path is not None else None
        data = read_cable_calibration(resolved) if resolved is not None else None
        self.settings.cable_calib_path = str(resolved) if resolved is not None else ''
        self.prop_auto.cable_calib_path = resolved
        self.cable_calib = data
        self.cable_calib_error = ''


    @property
    def file(self):
        return self.root / f"{self.name}{PROJECT_SUFFIX}"

    @property
    def report_file(self):
        return self.root / f"{self.name}.docx"

    @classmethod
    def new_project(cls, file: Path):
        file = Path(file)
        root = file.parent
        (root / CALIB_DIR).mkdir(parents=True, exist_ok=True)
        (root / TEST_DIR).mkdir(parents=True, exist_ok=True)
        import connection_cfg
        setup = MeasurementSettings(generator_ip=connection_cfg.GENERATOR_IP,
                                    generator_port=connection_cfg.GENERATOR_PORT)
        return cls(file.stem, {}, root, settings=setup)

    @classmethod
    def open_project(cls, file: Path):
        file = Path(file)
        data = json.loads(file.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("Project JSON must be an object.")
        version = data.get("schema_version")
        if version not in (None, 1, 2, 3, 4):
            raise ValueError(f"Unsupported project schema version: {version}")
        if version in (2, 3, 4) or (version == 1 and "prop_manual" in data):
            # Also read files written by the supplied revision with version 1.
            manual = data.get("prop_manual", {})
            automatic = data.get("prop_auto", {})
        elif version == 1:
            manual = data.get("properties", {})
            automatic = data.get("hardware", {})
        else:
            manual, automatic = data, {}
        if not isinstance(manual, dict):
            raise ValueError("Manual properties must be an object.")
        auto = AutoProps.from_dict(automatic)
        # Validate before creating any project directories.
        project = cls.new_project(file)
        project.prop_manual = {key: "" if value is None else str(value)
                               for key, value in manual.items()}
        project.prop_auto = auto
        import connection_cfg
        initial = dict(operator=auto.operator, dut_ip=auto.dut_ip,
                       cable_calib_path=str(auto.cable_calib_path) if auto.cable_calib_path else '',
                       generator_ip=connection_cfg.GENERATOR_IP,
                       generator_port=connection_cfg.GENERATOR_PORT)
        initial.update(data.get('settings', {}))
        project.settings = MeasurementSettings.from_dict(initial)
        project.sync_settings()
        project.load_cable_calibration()
        return project

    def sync_settings(self):
        self.prop_auto.dut_ip = self.settings.dut_ip
        self.prop_auto.operator = self.settings.operator
        self.prop_auto.cable_calib_path = Path(self.settings.cable_calib_path) if self.settings.cable_calib_path else None

    def save(self):
        self.sync_settings()
        payload = {"schema_version": 4, "prop_manual": self.prop_manual,
                   "prop_auto": self.prop_auto.to_dict(), "settings": asdict(self.settings)}
        self.root.mkdir(parents=True, exist_ok=True)
        temporary = self.file.with_suffix(".prj.tmp")
        temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        temporary.replace(self.file)

    @property
    def properties(self):
        """Compatibility with the previous manual-properties attribute."""
        return self.prop_manual

    @properties.setter
    def properties(self, value):
        self.prop_manual = value

    properies = properties


FasctoryProject = FactoryProject


def render_reports(prj: FactoryProject):
    """Compatibility entry point. Report generation is owned by report.py."""
    from report import render_reports as generate
    return generate(prj, template=default_template())
