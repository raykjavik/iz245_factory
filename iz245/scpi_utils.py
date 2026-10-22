from socket import socket
from typing import List
import time

SCPI_PRINT_OUT = False

def scpi_query(sock: socket, query_str: str):
    if query_str[-1] != "?":
        raise ValueError('SCPI query has to end with "?"')

    if SCPI_PRINT_OUT:
        host, port = sock.getpeername()
        print(
            f"SCPI query: "
            f"{host}:{port} {query_str}"
        )

    try:
        sock.sendall(
            bytes(
                query_str + "\n",
                encoding="ascii",
            )
        )

        response = bytearray()

        while True:
            chunk = sock.recv(1000)

            # recv() == b"" means the peer closed the TCP connection.
            if not chunk:
                raise ConnectionError(
                    "SCPI socket closed while waiting for "
                    f"response to {query_str!r}"
                )

            response.extend(chunk)

            # SCPI responses are newline terminated.
            if b"\n" in response:
                break

    except TimeoutError:
        try:
            peer = sock.getpeername()
        except OSError:
            peer = "<disconnected>"

        print(
            f"SCPI timeout error: {peer}, "
            f"query: {query_str}, "
            f"timeout[sec]={sock.gettimeout()}"
        )
        raise

    # Only use the first complete line.
    line, _, _ = response.partition(b"\n")

    # Handle CRLF as well as LF.
    line = line.rstrip(b"\r")

    resp = line.decode("ascii")

    if SCPI_PRINT_OUT:
        print("Response: " + resp)

    return resp

def scpi_command(sock, cmd_str):
    if SCPI_PRINT_OUT:
        host,port = sock.getpeername()
        print("SCPI command: " + host + ":" + str(port) + " " + cmd_str)

    sock.sendall(bytes(cmd_str + "\n", encoding="ascii"))
    # print("SCPI" + str(sock.getpeername()) + " .. " + cmd_str)

def scpi_commands(sock, cmds):
    cmd = ";:".join(cmds)
    scpi_command(sock, cmd)


def scpi_queries(sock, query_list:List[str]):
    return {q: scpi_query(sock,q) for q in query_list}

def scpi_queries_tupled(sock, query_list:List[str]):
    return tuple([scpi_query(sock,q) for q in query_list])

