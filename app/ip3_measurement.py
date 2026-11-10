"""SMATE200A two-RF-path transport."""
from generator_connection import default_generator_factory

class TwoToneGenerator:
    """Legacy adapter for caller-supplied two-tone SCPI command templates."""
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
    # SMATE200A uses the same RSGenerator SCPI socket transport. Its model-specific
    # reference and two-path commands live in the Qt-free cfg_test_7 procedure.
    return default_generator_factory(ip, port)
