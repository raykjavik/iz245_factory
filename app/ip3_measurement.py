"""Two-tone generator transport adapter and compatibility acquisition entry point."""

class TwoToneGenerator:
    """Wrap the current SMA1000B transport; a later driver can implement this interface."""
    def __init__(self, transport, commands):
        if not commands:
            raise NotImplementedError(
                'Set TEST7_TWO_TONE_COMMANDS in cfg_test_7.py to the two-tone generator SCPI commands '
                '(f1_hz, f2_hz, power_dbm), or supply an IP3 generator factory.')
        self.transport = transport
        self.commands = commands

    def __getattr__(self, name):
        return getattr(self.transport, name)

    def configure_two_cw(self, f1_hz, f2_hz, power_dbm):
        for template in self.commands:
            self.transport.cmd(template.format(f1_hz=f1_hz, f2_hz=f2_hz, power_dbm=power_dbm))


def default_ip3_generator_factory(ip, port):
    # The domain now defines actual SOURCE1/SOURCE2 commands directly.
    from calib_tab import default_generator_factory
    return default_generator_factory(ip, port)


def measure_ip3(controller, name, spec, dwell):
    from measurement_handlers import measure_ip3 as acquire
    return acquire(controller, name, spec, dwell)
