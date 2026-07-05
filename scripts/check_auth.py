#!/usr/bin/env python3

import os
import subprocess
import sys

from config import HPC_USER, HPC_HOST, BRIDGE_USER, BRIDGE_HOST, OIDC_AGENT, OIDC_PASSWORD, MINIO_CLIENT_ID


def run(cmd, *, input_text=None, check=True, show_output=True, sensitive=False):
    printable = " ".join(cmd)
    if sensitive:
        print("[CHECK] <hidden sensitive command>")
    else:
        print(f"[CHECK] {printable}")

    result = subprocess.run(
        cmd,
        input=input_text,
        text=True,
        capture_output=True,
        env=os.environ.copy(),
    )

    if show_output and result.stdout:
        print(result.stdout)

    if show_output and result.stderr:
        print(result.stderr, file=sys.stderr)

    if check and result.returncode != 0:
        if sensitive:
            raise RuntimeError("Sensitive command failed")
        else:
            raise RuntimeError(f"Command failed: {printable}")

    return result


def setup_oidc_agent():
    result = run(["oidc-agent-service", "use"])

    for part in result.stdout.replace(";", "\n").splitlines():
        part = part.strip()

        if part.startswith("export "):
            part = part.replace("export ", "", 1).strip()

        if part.startswith("OIDC_SOCK="):
            os.environ["OIDC_SOCK"] = part.split("=", 1)[1].strip().strip('"').strip("'")

        if part.startswith("OIDCD_PID="):
            os.environ["OIDCD_PID"] = part.split("=", 1)[1].strip().strip('"').strip("'")

    if "OIDC_SOCK" not in os.environ:
        raise RuntimeError("Could not start or parse oidc-agent-service output")


def main():
    print("[CHECK] Starting authentication check")

    setup_oidc_agent()

    print("[CHECK] Loading OIDC account")
    run([
    "oidc-add",
    "--pw-env=OIDC_PASSWORD",
    OIDC_AGENT,
],sensitive=True)

    print("[CHECK] Testing OIDC token")
    run(["oidc-token", OIDC_AGENT, "--aud", MINIO_CLIENT_ID], show_output=False)

    print("[CHECK] Testing SSH access to HPC through bridge")
    run([
        "ssh",
        "-i", "/secrets/ssh/id_rsa",
        "-o", "IdentitiesOnly=yes",
        "-o", "BatchMode=yes",
        "-o", "StrictHostKeyChecking=accept-new",
        "-o", "ConnectTimeout=20",
        "-o", (
                f"ProxyCommand=ssh -i /secrets/ssh/id_rsa "
                f"-o IdentitiesOnly=yes "
                f"-o StrictHostKeyChecking=accept-new "
                f"-W %h:%p {BRIDGE_USER}@{BRIDGE_HOST}"
    ),
         f"{HPC_USER}@{HPC_HOST}",
         "echo '[CHECK] SSH OK on HPC login node'"
    ], sensitive=True)

    print("[CHECK] Authentication check completed successfully")


if __name__ == "__main__":
    main()
