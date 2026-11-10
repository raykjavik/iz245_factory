"""SCPI socket transport shared by the sweep and two-tone generators."""
import socket
from iz245.device import RSGenerator


def default_generator_factory(ip, port):
    class ConfiguredGenerator(RSGenerator):
        def open(self, tdoa_setting=False):
            # The supplied RSGenerator.open ignores self.port.
            with self.scpi_lock:
                self.close()
                try:
                    self.main_scpi = socket.create_connection((self.ip, self.port), timeout=10)
                    self.connected = True
                    return True
                except OSError:
                    self.close()
                    return False
    return ConfiguredGenerator(ip, port=port)


