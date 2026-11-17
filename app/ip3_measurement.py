"""SMATE200A two-RF-path transport."""
from generator_connection import default_generator_factory

def default_ip3_generator_factory(ip, port):
    # SMATE200A uses the same RSGenerator SCPI socket transport. Its model-specific
    # reference and two-path commands live in the Qt-free cfg_test_7 procedure.
    return default_generator_factory(ip, port)
