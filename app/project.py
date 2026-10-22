"""Manual template fields, DUT properties, project persistence, and reports."""
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from collections.abc import Mapping
import json
from docxtpl import DocxTemplate

CALIB_DIR = "calib"
TEST_DIR = "tests"
TEMPLATE_PATH = Path(__file__).parent / "template.docx"
MANUAL_KEYS_PREFIX = "prj_"
PROJECT_SUFFIX = ".prj"


def default_template():
    return DocxTemplate(TEMPLATE_PATH)


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

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, Mapping):
            raise ValueError("Automatic properties must be an object.")
        allowed = {f.name for f in fields(cls)}
        unknown = set(data) - allowed
        if unknown:
            raise ValueError(f"Unknown automatic properties: {', '.join(sorted(unknown))}")
        return cls(**{key: "" if value is None else str(value)
                      for key, value in data.items()})

    def to_dict(self):
        return asdict(self)


@dataclass
class FactoryProject:
    name: str
    prop_manual: dict
    root: Path
    prop_auto: AutoProps = field(default_factory=AutoProps)

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
        return cls(file.stem, {}, root)

    @classmethod
    def open_project(cls, file: Path):
        file = Path(file)
        data = json.loads(file.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("Project JSON must be an object.")
        version = data.get("schema_version")
        if version not in (None, 1, 2):
            raise ValueError(f"Unsupported project schema version: {version}")
        if version == 2 or (version == 1 and "prop_manual" in data):
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
        return project

    def save(self):
        payload = {"schema_version": 2, "prop_manual": self.prop_manual,
                   "prop_auto": self.prop_auto.to_dict()}
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
    report = default_template()
    automatic = prj.prop_auto.to_dict()
    # Supports {{ serial_number }} and {{ prop_auto.serial_number }}.
    # Manual template keys retain their prj_ / pjr_ names.
    context = {**prj.prop_manual, **automatic, "prop_auto": automatic}
    report.render(context, autoescape=True)
    report.save(prj.report_file)
    return prj.report_file
