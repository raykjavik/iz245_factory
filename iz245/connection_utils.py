from socket import socket, AF_INET, SOCK_STREAM 

MAIN_SCPI_PORT = 5025
AUX1_SCPI_PORT = 5031  # aux only
AUX2_SCPI_PORT = 5032  #
MAIN_CAPTURE_PORT = 40007

MAIN_IQSTREAM_PORT = 4007  # port 1
AUX1_IQSTREAM_PORT = 4011  # port 1
AUX2_IQSTREAM_PORT = 4012  # port 2AUX1_SCPI_PORT = 5031  # aux only

PPSYNC_SCPI_PORT = 5020  # GNSS_SCPI_PORT
LOGSERVER_PORT = 5010  # GNSS_LOGS

PPSYNC_SCPI_PORT = 5020

TIMEOUT_SCPI = 5
TIMEOUT_DATA = 5


def connect_tcp_ip(ip, port, timeout):
    sock = socket(AF_INET, SOCK_STREAM)
    sock.settimeout(timeout)
    sock.connect((ip, port))

    return sock

def connect_main_scpi(ip):
    return connect_tcp_ip(ip,port=MAIN_SCPI_PORT,timeout=TIMEOUT_SCPI)

def connect_main_capture(ip):
    return connect_tcp_ip(ip, port=MAIN_CAPTURE_PORT,timeout=TIMEOUT_DATA)

def connect_aux1_scpi(ip):
    return connect_tcp_ip(ip,port=AUX1_SCPI_PORT,timeout=TIMEOUT_SCPI)

def connect_aux2_scpi(ip):
    return connect_tcp_ip(ip,port=AUX2_SCPI_PORT,timeout=TIMEOUT_SCPI)

def connect_main_iq_stream(ip):
    return connect_tcp_ip(ip,port=MAIN_IQSTREAM_PORT,timeout=TIMEOUT_DATA)

def connect_aux1_iq_stream(ip):
    return connect_tcp_ip(ip,port=AUX1_IQSTREAM_PORT,timeout=TIMEOUT_DATA)

def connect_aux2_iq_stream(ip):
    return connect_tcp_ip(ip,port=AUX2_IQSTREAM_PORT,timeout=TIMEOUT_DATA)

def connect_gps_scpi(ip):
    return connect_tcp_ip(ip,port=PPSYNC_SCPI_PORT,timeout=TIMEOUT_SCPI)

