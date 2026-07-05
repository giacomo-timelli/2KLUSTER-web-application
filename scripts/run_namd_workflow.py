#!/usr/bin/env python3

import argparse
import base64
import os
import shutil
import subprocess
import sys
import tarfile
import uuid
from pathlib import Path
from urllib.parse import urlparse

from config import (
    LOCAL_WORKDIR,
    HPC_USER,
    OIDC_AGENT,
    REMOTE_BASE_DIR,
    MINIO_ENDPOINT,
    MINIO_BUCKET,
    DEFAULT_PARTITION,
)

from slurm_template import make_remote_script
from hpc_client import run_remote_script


def run(
    cmd,
    *,
    shell=False,
    cwd=None,
    check=True,
    capture=False,
    input_text=None,
    sensitive=False,
):
    printable = cmd if isinstance(cmd, str) else " ".join(cmd)

    if sensitive:
        print("[CMD] <hidden sensitive command>")
    else:
        print(f"[CMD] {printable}")

    return subprocess.run(
        cmd,
        shell=shell,
        cwd=cwd,
        check=check,
        text=True,
        capture_output=capture,
        input=input_text,
        env=os.environ.copy(),
    )


def require_file(path: Path, message: str):
    if not path.exists():
        print(f"[ERROR] {message}: {path}")
        sys.exit(1)

    if path.is_file() and path.stat().st_size == 0:
        print(f"[ERROR] File is empty: {path}")
        sys.exit(1)


def setup_oidc_agent():
    print("[STREAMLIT POD] Starting/using oidc-agent")

    result = run(
        ["oidc-agent-service", "use"],
        capture=True,
    )

    oidc_output = result.stdout

    for part in oidc_output.replace(";", "\n").splitlines():
        part = part.strip()

        if part.startswith("export "):
            part = part.replace("export ", "", 1).strip()

        if part.startswith("OIDC_SOCK="):
            value = part.split("=", 1)[1].strip().strip('"').strip("'")
            os.environ["OIDC_SOCK"] = value

        if part.startswith("OIDCD_PID="):
            value = part.split("=", 1)[1].strip().strip('"').strip("'")
            os.environ["OIDCD_PID"] = value

    if "OIDC_SOCK" not in os.environ:
        print("[ERROR] Could not parse OIDC_SOCK from oidc-agent-service output")
        print(oidc_output)
        sys.exit(1)

    print(f"[STREAMLIT POD] OIDC_SOCK={os.environ['OIDC_SOCK']}")


def download_and_extract_dataset(molecule_url: str, input_dir: Path) -> None:
    archive_name = Path(urlparse(molecule_url).path).name

    if not archive_name:
        print("[ERROR] Could not determine archive name from molecule URL")
        sys.exit(1)

    archive_path = input_dir / archive_name

    print(f"[STREAMLIT POD] Downloading molecule dataset: {molecule_url}")
    run(["wget", "-O", str(archive_path), molecule_url])

    if archive_name.endswith((".tar.gz", ".tgz", ".tar")):
        print("[STREAMLIT POD] Extracting dataset archive")
        with tarfile.open(archive_path, "r:*") as tar:
            tar.extractall(path=input_dir)
    else:
        print("[WARNING] Dataset is not a tar archive. Keeping it as a normal file.")


def find_dataset_subdir(input_dir: Path) -> str:
    subdirs = [
        path for path in input_dir.iterdir()
        if path.is_dir()
    ]

    if len(subdirs) == 1:
        dataset_subdir = subdirs[0].name
        print(f"[STREAMLIT POD] Detected dataset directory: {dataset_subdir}")
        print(f"VISUALIZATION_INPUT_SUBDIR={dataset_subdir}")
        return dataset_subdir

    print("[ERROR] Could not uniquely determine extracted dataset directory.")
    print("Found subdirectories:", [path.name for path in subdirs])
    sys.exit(1)


def copy_namd_config(namd_config_path: Path, input_dir: Path, work_subdir: str) -> str:
    require_file(namd_config_path, "Uploaded NAMD config file not found")

    target_dir = input_dir / work_subdir

    if not target_dir.exists():
        print(f"[ERROR] Dataset working directory does not exist: {target_dir}")
        sys.exit(1)

    target_path = target_dir / "input.namd"
    shutil.copy2(namd_config_path, target_path)

    print(f"[STREAMLIT POD] Copied custom NAMD config to: {target_path}")
    return "input.namd"


def find_first_file_name(base_dir: Path, suffix: str) -> str | None:
    files = sorted(base_dir.rglob(f"*{suffix}"))

    if files:
        return files[0].name

    return None


def parse_namd_value(namd_config_path: Path, key: str) -> str | None:
    key_lower = key.lower()

    for line in namd_config_path.read_text(errors="ignore").splitlines():
        clean = line.strip()

        if not clean or clean.startswith("#"):
            continue

        parts = clean.split()

        if len(parts) >= 2 and parts[0].lower() == key_lower:
            return parts[1]

    return None


def print_visualization_markers(
    *,
    run_id: str,
    input_dir: Path,
    work_subdir: str,
    namd_config_name: str,
) -> None:
    work_dir = input_dir / work_subdir
    namd_config_path = work_dir / namd_config_name

    pdb_file = find_first_file_name(work_dir, ".pdb")
    psf_file = find_first_file_name(work_dir, ".psf")
    dcd_file = parse_namd_value(namd_config_path, "DCDfile")

    print(f"VISUALIZATION_RUN_ID={run_id}")
    print(f"VISUALIZATION_INPUT_SUBDIR={work_subdir}")

    if pdb_file:
        print(f"VISUALIZATION_PDB={pdb_file}")

    if psf_file:
        print(f"VISUALIZATION_PSF={psf_file}")

    if dcd_file:
        print(f"VISUALIZATION_DCD={dcd_file}")


def generate_sts_credentials(sts_env_file: Path) -> None:
    script_dir = Path(__file__).resolve().parent
    sts_script = script_dir / "login_sts.py"

    require_file(sts_script, "STS script not found")

    print("[STREAMLIT POD] Getting temporary STS credentials")

    run(
        [
            "python3",
            str(sts_script),
            "--oidc",
            OIDC_AGENT,
            "--env-file",
            str(sts_env_file),
        ]
    )

    require_file(sts_env_file, "STS credentials file was not generated")


def upload_inputs_to_storage(input_dir: Path, run_id: str) -> None:
    print("[STREAMLIT POD] Uploading input files to S3-compatible storage")

    aws_config = LOCAL_WORKDIR / "aws_config"
    aws_config.write_text(
        "[default]\n"
        "s3 =\n"
        "    multipart_threshold = 5GB\n"
        "    multipart_chunksize = 64MB\n"
    )

    os.environ["AWS_CONFIG_FILE"] = str(aws_config)

    run(
        [
            "aws",
            "--endpoint-url",
            MINIO_ENDPOINT,
            "s3",
            "rm",
            "--recursive",
            f"s3://{MINIO_BUCKET}/inputs/{run_id}/",
        ],
        check=False,
    )

    run(
        [
            "aws",
            "--endpoint-url",
            MINIO_ENDPOINT,
            "s3",
            "cp",
            "--recursive",
            str(input_dir) + "/",
            f"s3://{MINIO_BUCKET}/inputs/{run_id}/",
        ]
    )


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument("--molecule-url", required=True)
    parser.add_argument("--namd-config", required=True)
    parser.add_argument("--partition", default=DEFAULT_PARTITION)
    parser.add_argument("--gpus", required=True)
    parser.add_argument("--cpus", required=True)
    parser.add_argument("--job-name", default="namd_cuda_run")
    parser.add_argument("--overwrite-inputs", action="store_true")

    args = parser.parse_args()

    run_id = f"{args.job_name}_{uuid.uuid4().hex[:8]}"

    workflow_dir = LOCAL_WORKDIR / run_id
    input_dir = workflow_dir / "input"
    sts_env_file = workflow_dir / "sts_credentials.env"

    input_dir.mkdir(parents=True, exist_ok=True)

    hpc_workdir = f"{REMOTE_BASE_DIR}/runs/{run_id}"

    print("======================================")
    print(" Streamlit / S3 / HPC / NAMD CUDA workflow")
    print("======================================")
    print(f"[STREAMLIT POD] HPC_USER={HPC_USER}")
    print(f"[STREAMLIT POD] RUN_ID={run_id}")
    print(f"[STREAMLIT POD] HPC_WORKDIR={hpc_workdir}")

    setup_oidc_agent()

    print("[STREAMLIT POD] Loading OIDC account")
    run([
        "oidc-add",
        "--pw-env=OIDC_PASSWORD",
        OIDC_AGENT,
    ], sensitive=True)

    print("[STREAMLIT POD] Testing OIDC token")
    run(["oidc-token", OIDC_AGENT], capture=True)

    generate_sts_credentials(sts_env_file)

    print("[STREAMLIT POD] Loading temporary credentials locally for upload")

    source_cmd = f"set -a && . {sts_env_file} && set +a && env"
    result = run(source_cmd, shell=True, capture=True)

    for line in result.stdout.splitlines():
        if line.startswith("AWS_ACCESS_KEY_ID="):
            os.environ["AWS_ACCESS_KEY_ID"] = line.split("=", 1)[1]
        elif line.startswith("AWS_SECRET_ACCESS_KEY="):
            os.environ["AWS_SECRET_ACCESS_KEY"] = line.split("=", 1)[1]
        elif line.startswith("AWS_SESSION_TOKEN="):
            os.environ["AWS_SESSION_TOKEN"] = line.split("=", 1)[1]
        elif line.startswith("AWS_ENDPOINT_URL="):
            os.environ["AWS_ENDPOINT_URL"] = line.split("=", 1)[1]

    download_and_extract_dataset(args.molecule_url, input_dir)

    work_subdir = find_dataset_subdir(input_dir)

    namd_config_name = copy_namd_config(
        Path(args.namd_config),
        input_dir,
        work_subdir,
    )

    print_visualization_markers(
        run_id=run_id,
        input_dir=input_dir,
        work_subdir=work_subdir,
        namd_config_name=namd_config_name,
    )

    upload_inputs_to_storage(input_dir, run_id)

    print("[STREAMLIT POD] Encoding temporary credentials for HPC login node")

    cred_b64 = base64.b64encode(
        sts_env_file.read_bytes()
    ).decode("utf-8")

    remote_script = make_remote_script(
        hpc_workdir=hpc_workdir,
        cred_b64=cred_b64,
        run_id=run_id,
        job_name=args.job_name,
        namd_config_name=namd_config_name,
        work_subdir=work_subdir,
        cpus=args.cpus,
        gpus=args.gpus,
        partition=args.partition,
    )

    run_remote_script(remote_script=remote_script)

    print("[STREAMLIT POD] Workflow completed successfully")
    print(f"[STREAMLIT POD] S3 output prefix: s3://{MINIO_BUCKET}/runs/{run_id}/")


if __name__ == "__main__":
    main()
