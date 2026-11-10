"""Named operations and their resources; no action-plan step interpreter."""
from dataclasses import dataclass
from cfg import (CFG_CALIB_RF1,CFG_PCALIB,CFG_CALIB_RF2,CFG_TEST1_RF1,CFG_TEST1_RF2,
                 CFG_TEST2,CFG_TEST2_RF2,CFG_TEST3,CFG_TEST4,CFG_NOISE_DENSITY,MEASUREMENT_SPECS)
from measurement_specs import NoiseDensitySpec, IFSpectrumSpec
from cfg_test8 import CFG_TEST8
from cfg import CFG_TEST7_RF1, CFG_TEST7_RF2


@dataclass(frozen=True)
class MeasurementJob:
    action: str
    method: str
    names: tuple[str,...] = ()
    single_name: str | None = None
    needs_transfer: bool = False
    fixed_work: int = 0
    needs_iq: bool = False

    @property
    def needs_dut(self):
        return bool(self.names)

    @property
    def needs_generator(self):
        return any(MEASUREMENT_SPECS[name].needs_generator for name in self.names)

    @property
    def generator_role(self):
        roles = {getattr(MEASUREMENT_SPECS[name], 'generator_role', 'standard')
                 for name in self.names if MEASUREMENT_SPECS[name].needs_generator}
        if len(roles) > 1:
            raise ValueError('Run measurements requiring different generators separately.')
        return next(iter(roles), 'standard')

    @property
    def pausable(self):
        return self.needs_dut

    def execute(self,controller):
        getattr(controller,self.method)(self.single_name)


class JobFactory:
    @staticmethod
    def measure_calibrations_rf1(name=None):
        return MeasurementJob('measure_calibrations_rf1','measure_calibrations_rf1',tuple(CFG_CALIB_RF1))
    @staticmethod
    def measure_calibrations_rf2(name=None):
        return MeasurementJob('measure_calibrations_rf2','measure_calibrations_rf2',tuple(CFG_CALIB_RF2))
    @staticmethod
    def measure_preselectors(name=None):
        return MeasurementJob('measure_preselectors','measure_preselectors',tuple(CFG_PCALIB))
    @staticmethod
    def ch1(name=None):
        names=(*CFG_CALIB_RF1,*CFG_PCALIB,*CFG_TEST1_RF1,*CFG_NOISE_DENSITY)
        return MeasurementJob('ch1','run_rf1_pipeline',names,needs_transfer=True,
                              fixed_work=len(CFG_CALIB_RF1)+len(CFG_PCALIB)+2,needs_iq=True)
    @staticmethod
    def ch2(name=None):
        return MeasurementJob('ch2','run_rf2_pipeline',(*CFG_CALIB_RF2,*CFG_TEST1_RF2),
                              needs_transfer=True,fixed_work=len(CFG_CALIB_RF2)+1)
    @staticmethod
    def test1_rf1(name=None):
        return MeasurementJob('test1_rf1','run_test1_rf1',tuple(CFG_TEST1_RF1))
    @staticmethod
    def test1_rf2(name=None):
        return MeasurementJob('test1_rf2','run_test1_rf2',tuple(CFG_TEST1_RF2))
    @staticmethod
    def noise_rf1(name=None):
        return MeasurementJob('noise_rf1','run_noise_rf1',tuple(CFG_TEST2))
    @staticmethod
    def noise_rf2(name=None):
        return MeasurementJob('noise_rf2','run_noise_rf2',tuple(CFG_TEST2_RF2))
    @staticmethod
    def test3_rf1(name=None):
        return MeasurementJob('test3_rf1','run_test3_rf1',tuple(CFG_TEST3))
    @staticmethod
    def test4(name=None):
        return MeasurementJob('test4','run_test4',tuple(CFG_TEST4))
    @staticmethod
    def noise_density(name=None):
        return MeasurementJob('noise_density','run_noise_density',tuple(CFG_NOISE_DENSITY),needs_iq=True)
    @staticmethod
    def test8(name=None):
        return MeasurementJob('test8','run_test8',tuple(CFG_TEST8),needs_iq=True)
    @staticmethod
    def test7_rf1(name=None):
        return MeasurementJob('test7_rf1', 'run_test7_rf1', tuple(CFG_TEST7_RF1))
    @staticmethod
    def test7_rf2(name=None):
        return MeasurementJob('test7_rf2', 'run_test7_rf2', tuple(CFG_TEST7_RF2))
    @staticmethod
    def measure(name):
        spec=MEASUREMENT_SPECS[name]
        return MeasurementJob('measure','measure',(name,),single_name=name,
                              needs_iq=isinstance(spec,(NoiseDensitySpec,IFSpectrumSpec)))
    @staticmethod
    def upload(name):
        return MeasurementJob('upload','upload',single_name=name,needs_transfer=True,fixed_work=1)
    @staticmethod
    def upload_all(name=None):
        return MeasurementJob('upload_all','run_upload_all',needs_transfer=True,
            fixed_work=len(CFG_CALIB_RF1)+len(CFG_PCALIB)+len(CFG_CALIB_RF2))
    @staticmethod
    def download(name):
        return MeasurementJob('download','download',single_name=name,needs_transfer=True,fixed_work=1)
    @staticmethod
    def download_all(name=None):
        return MeasurementJob('download_all','run_download_all',needs_transfer=True,
                              fixed_work=len(CFG_CALIB_RF1)+len(CFG_PCALIB)+len(CFG_CALIB_RF2))


def make_job(action,name=None):
    """Legacy string entry point; UI/worker carry the resulting named job."""
    if isinstance(action,MeasurementJob):
        return action
    factory=getattr(JobFactory,action,None)
    if factory is None or action.startswith('_'):
        raise ValueError(f'Unknown measurement operation: {action}')
    return factory(name)
