#!/usr/bin/env python3
"""Wait until a TCP port accepts connections (used by run.bat).

Usage: python tools/wait_port.py HOST PORT [TIMEOUT_SECONDS]

Exits 0 as soon as the port answers, 1 after the timeout. Standard library only,
so it works with the bundled portable interpreter and with a plain pip install.
"""

import socket
import sys
import time


def main() -> int:
    host = sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1"
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 8080
    timeout = float(sys.argv[3]) if len(sys.argv) > 3 else 120.0

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=2):
                print(f"port {host}:{port} is up")
                return 0
        except OSError:
            time.sleep(2)

    print(f"timeout: {host}:{port} not reachable within {timeout:.0f} s")
    return 1


if __name__ == "__main__":
    sys.exit(main())
