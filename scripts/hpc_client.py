import os
import subprocess
import sys
import time

from config import BRIDGE_USER, BRIDGE_HOST, HPC_HOST, HPC_USER


def run_remote_script(
    *,
    remote_script: str,
    max_attempts: int = 3,
    retry_sleep_seconds: int = 10,
) -> None:
    ssh_cmd = [
        "ssh",
        "-i", "/secrets/ssh/id_rsa",
        "-o", "IdentitiesOnly=yes",
        "-o", "StrictHostKeyChecking=accept-new",
        "-o", "ConnectTimeout=20",
        "-o", "ServerAliveInterval=15",
        "-o", "ServerAliveCountMax=3",
        "-o",
        (
            f"ProxyCommand=ssh -i /secrets/ssh/id_rsa "
            f"-o IdentitiesOnly=yes "
            f"-o StrictHostKeyChecking=accept-new "
            f"-W %h:%p {BRIDGE_USER}@{BRIDGE_HOST}"
        ),
        f"{HPC_USER}@{HPC_HOST}",
        "bash -s",
    ]

    for attempt in range(1, max_attempts + 1):
        print(
            f"[STREAMLIT POD] Connecting to HPC login through bridge "
            f"(attempt {attempt}/{max_attempts})",
            flush=True,
        )

        process = subprocess.Popen(
            ssh_cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env=os.environ.copy(),
            bufsize=1,
        )

        assert process.stdin is not None
        process.stdin.write(remote_script)
        process.stdin.close()

        assert process.stdout is not None
        for line in process.stdout:
            print(line, end="", flush=True)

        process.wait()

        if process.returncode == 0:
            print("[STREAMLIT POD] Remote workflow finished successfully", flush=True)
            return

        print(
            f"[WARNING] Remote workflow failed with exit code {process.returncode}",
            flush=True,
        )

        if attempt < max_attempts:
            print(
                f"[STREAMLIT POD] Retrying in {retry_sleep_seconds} seconds...",
                flush=True,
            )
            time.sleep(retry_sleep_seconds)

    print("[ERROR] Remote workflow failed after all retry attempts", flush=True)
    sys.exit(process.returncode)
