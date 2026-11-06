"""Application adapters: pass explicit hardware, values and callbacks to domain functions."""
from measurement_control import check_abort


def sweep_with_generator(controller, name, spec, dwell):
    from cfg_calib import measure_calibration
    return _generator_sweep(measure_calibration, controller, name, spec, dwell)


def measure_test1(controller, name, spec, dwell):
    from cfg_test1 import measure_test1 as acquire
    return _generator_sweep(acquire, controller, name, spec, dwell)


def _generator_sweep(acquire, controller, name, spec, dwell):
    return acquire(controller.dev, controller.gen, spec.frequencies, spec.commands,
        name=name, target_power_dbm=spec.power_dbm, dwell_sec=dwell,
        attenuator_db=controller.prj.settings.attenuator_db,
        operator=controller.operator, temperature=controller.prj.prop_auto.calibration_temperature,
        checkpoint=controller._checkpoint, wait=controller.wait,
        on_row=lambda frequency,value:controller.record_point(name,frequency,value))


def _receiver_sweep(acquire, controller, name, spec, dwell):
    return acquire(controller.dev, spec.frequencies, spec.commands, name=name,
        dwell_sec=dwell,
        operator=controller.operator, temperature=controller.prj.prop_auto.calibration_temperature,
        checkpoint=controller._checkpoint,
        on_row=lambda frequency,value:controller.record_point(name,frequency,value))


def measure_test2(controller, name, spec, dwell):
    from cfg_test2 import measure_test2 as acquire
    return _receiver_sweep(acquire,controller,name,spec,dwell)


def measure_test3(controller, name, spec, dwell):
    from cfg_test3 import measure_test3 as acquire
    return _generator_sweep(acquire,controller,name,spec,dwell)


def measure_test4(controller, name, spec, dwell):
    from cfg_test4 import measure_test4 as acquire
    return _receiver_sweep(acquire,controller,name,spec,dwell)


def measure_spectrum(controller,name,spec,dwell):
    raise NotImplementedError('Register a spectrum handler before enabling a new IQ procedure.')


def measure_noise_density(controller,name,spec,dwell):
    from cfg_test_5_6 import measure_tests5_6
    return measure_tests5_6(controller.dev,controller.gen,spec,
        name=name,dwell_sec=dwell,fft_count=controller.prj.settings.noise_ffts,
        attenuator_db=controller.prj.settings.attenuator_db,
        operator=controller.operator,temperature=controller.prj.prop_auto.calibration_temperature,
        checkpoint=controller._checkpoint,wait=controller.wait,
        check_cancel=lambda:check_abort(controller.cancel),
        on_spectrum=lambda result:controller.density_updated(name,result),
        on_progress=controller._advance,on_status=controller.status)


def measure_ip3(controller,name,spec,dwell):
    from cfg_test_7 import measure_test7
    return measure_test7(controller.dev,controller.gen,spec,name=name,
        noise_dwell_sec=controller.prj.settings.ip3_noise_dwell_sec,
        signal_dwell_sec=controller.prj.settings.ip3_signal_dwell_sec,
        headroom_db=controller.prj.settings.ip3_headroom_db,
        attenuator_db=controller.prj.settings.ip3_attenuator_db,
        operator=controller.operator,temperature=controller.prj.prop_auto.calibration_temperature,
        checkpoint=controller._checkpoint,check_cancel=lambda:check_abort(controller.cancel),
        on_row=lambda result:controller.ip3_updated(name,result),on_progress=controller._advance)


def measure_if_spectrum(controller,name,spec,dwell):
    from cfg_test8 import measure_test8
    return measure_test8(controller.dev,spec,name=name,
        dwell_sec=dwell,
        operator=controller.operator,temperature=controller.prj.prop_auto.calibration_temperature,
        checkpoint=controller._checkpoint,wait=controller.wait,
        check_cancel=lambda:check_abort(controller.cancel),
        on_spectrum=lambda result:controller.spectrum_updated(name,result),
        on_progress=controller._advance,on_status=controller.status)


HANDLERS = {'calibration':sweep_with_generator,'test1':measure_test1,
            'test2':measure_test2,'test3':measure_test3,'test4':measure_test4,
            'noise_density':measure_noise_density,'ip3':measure_ip3,
            'generator_sweep':sweep_with_generator,'receiver_sweep':measure_test2,
            'spectrum':measure_spectrum,'if_spectrum':measure_if_spectrum}
