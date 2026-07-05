import os
from pathlib import Path


def require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def optional_env(name: str, default: str) -> str:
    return os.getenv(name, default)


# Local temporary working directory inside the Streamlit/container runtime
LOCAL_WORKDIR = Path(optional_env("LOCAL_WORKDIR", "/tmp/hpc_job"))


# Runtime/user-specific values
HPC_USER = require_env("HPC_USER")
OIDC_AGENT = require_env("OIDC_AGENT")
OIDC_PASSWORD = require_env("OIDC_PASSWORD")


# Infrastructure configuration
BRIDGE_USER = require_env("BRIDGE_USER")
BRIDGE_HOST = require_env("BRIDGE_HOST")

HPC_HOST = require_env("HPC_LOGIN")

MINIO_CLIENT_ID = require_env("MINIO_CLIENT_ID")
MINIO_ENDPOINT = require_env("MINIO_ENDPOINT")
MINIO_BUCKET = require_env("MINIO_BUCKET")


# HPC-side paths
REMOTE_BASE_DIR = require_env("REMOTE_BASE_DIR")

REMOTE_CONTAINERS_DIR = f"{REMOTE_BASE_DIR}/containers"

NAMD_SIF = optional_env(
    "NAMD_SIF",
    f"{REMOTE_CONTAINERS_DIR}/namd3_cuda.sif",
)

NAMD_SIF_MINIO_PATH = optional_env(
    "NAMD_SIF_MINIO_PATH",
    f"s3://{MINIO_BUCKET}/containers/namd3_cuda.sif",
)


# Job/script names
JOB_SCRIPT = optional_env("JOB_SCRIPT", "namd_cuda_minio.job")


# Defaults used only if CLI arguments are not provided
DEFAULT_CPUS_PER_TASK = optional_env("DEFAULT_CPUS_PER_TASK", "64")
DEFAULT_GPU_COUNT = optional_env("DEFAULT_GPU_COUNT", "1")
DEFAULT_PARTITION = optional_env("DEFAULT_PARTITION", "<gpu-partition>")
