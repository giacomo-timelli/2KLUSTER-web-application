#!/usr/bin/env python3

import argparse
import os
import re
import subprocess
import sys

import pexpect


OIDC_SCOPES = "openid profile email offline_access"
IAM_DEMO_REGEX = r"https://<oidc-provider>/"


def setup_oidc_agent():
    result = subprocess.run(
        ["oidc-agent-service", "use"],
        capture_output=True,
        text=True,
        check=True,
    )

    for part in result.stdout.replace(";", "\n").splitlines():
        part = part.strip()

        if part.startswith("export "):
            part = part.replace("export ", "", 1).strip()

        if part.startswith("OIDC_SOCK="):
            os.environ["OIDC_SOCK"] = (
                part.split("=", 1)[1]
                .strip()
                .strip('"')
                .strip("'")
            )

        if part.startswith("OIDCD_PID="):
            os.environ["OIDCD_PID"] = (
                part.split("=", 1)[1]
                .strip()
                .strip('"')
                .strip("'")
            )

    if "OIDC_SOCK" not in os.environ:
        print("[OIDC ERROR] Could not initialize oidc-agent.", flush=True)
        sys.exit(1)


def wait_for_encryption_prompt(child):
    while True:
        index = child.expect(
            [
                r"(?i)enter.*encryption.*password.*:",
                r"(?i)encryption.*password.*:",
                r"(?i)the device has been approved",
                r"(?i)accepted",
                r"(?i)unknown cjson type",
                pexpect.EOF,
                pexpect.TIMEOUT,
            ],
            timeout=900,
        )

        if index in [0, 1]:
            return

        if index in [2, 3, 4]:
            continue

        if index == 5:
            print("[OIDC ERROR] oidc-gen ended before asking for encryption password.", flush=True)
            sys.exit(1)

        if index == 6:
            print("[OIDC ERROR] Timed out while waiting for encryption password prompt.", flush=True)
            sys.exit(1)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--shortname", required=True)
    args = parser.parse_args()

    password = os.environ.get("OIDC_NEW_PASSWORD")

    if not password:
        print("[OIDC ERROR] Missing encryption password.", flush=True)
        sys.exit(1)

    setup_oidc_agent()

    child = pexpect.spawn(
        "oidc-gen",
        [args.shortname],
        encoding="utf-8",
        timeout=900,
        env=os.environ.copy(),
    )

    child.delaybeforesend = 0.5

    try:
        print("[OIDC] Starting OIDC account creation", flush=True)

        child.expect(IAM_DEMO_REGEX, timeout=60)

        issuer_output = child.before + child.after

        match = re.search(
            r"\[(\d+)\]\s+https://iam-demo\.cloud\.cnaf\.infn\.it/",
            issuer_output,
        )

        if not match:
            print(
                "[OIDC ERROR] IAM-demo was found, but its menu index could not be parsed.",
                flush=True,
            )
            child.close(force=True)
            sys.exit(1)

        iam_demo_index = match.group(1)

        print(f"[OIDC] Selected IAM-demo issuer option: {iam_demo_index}", flush=True)
        child.sendline(iam_demo_index)

        child.expect(r"(?i)scopes", timeout=60)
        child.sendline(OIDC_SCOPES)

        child.expect(r"Using a browser on any device, visit:\s*(\S+)", timeout=120)
        device_url = child.match.group(1).strip()

        child.expect(r"And enter the code:\s*([A-Za-z0-9_-]+)", timeout=60)
        device_code = child.match.group(1).strip()

        print(f"OIDC_DEVICE_URL={device_url}", flush=True)
        print(f"OIDC_DEVICE_CODE={device_code}", flush=True)
        print(
            "[OIDC] Open the link above, log in, enter the code, and approve the device.",
            flush=True,
        )
        print("[OIDC] Waiting for approval...", flush=True)

        wait_for_encryption_prompt(child)

        child.sendline(password)

        child.expect(r"(?i).*confirm.*encryption.*password.*:", timeout=60)
        child.sendline(password)

        child.expect(
            [
                r"Everything setup correctly!",
                r"(?i)account.*created",
                pexpect.EOF,
            ],
            timeout=120,
        )

        print("[OIDC] Account created successfully.", flush=True)

    except pexpect.TIMEOUT:
        print("[OIDC ERROR] Timed out while waiting for oidc-gen.", flush=True)
        child.close(force=True)
        sys.exit(1)

    except Exception as exc:
        print(f"[OIDC ERROR] {exc}", flush=True)
        child.close(force=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
