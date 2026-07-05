from config import (
    MINIO_ENDPOINT,
    MINIO_BUCKET,
    NAMD_SIF_MINIO_PATH,
    JOB_SCRIPT,
    NAMD_SIF,
    DEFAULT_CPUS_PER_TASK,
    DEFAULT_GPU_COUNT,
    DEFAULT_PARTITION,
)


def make_slurm_script(
    *,
    job_name: str,
    run_id: str,
    namd_config_name: str,
    work_subdir: str,
    hpc_workdir: str,
    cpus: str = DEFAULT_CPUS_PER_TASK,
    gpus: str = DEFAULT_GPU_COUNT,
    partition: str = DEFAULT_PARTITION,
) -> str:
    return f"""#!/bin/bash
#SBATCH --job-name={job_name}
#SBATCH --partition={partition}
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task={cpus}
#SBATCH --gres=gpu:{gpus}
#SBATCH --time=02:00:00
#SBATCH --output=namd_cuda_%j.out
#SBATCH --error=namd_cuda_%j.err

set -uo pipefail

MINIO_ENDPOINT="{MINIO_ENDPOINT}"
MINIO_BUCKET="{MINIO_BUCKET}"
RUN_ID="{run_id}"
NAMD_CONFIG="{namd_config_name}"
WORK_SUBDIR="{work_subdir}"
NAMD_SIF="{NAMD_SIF}"
HPC_WORKDIR="{hpc_workdir}"
CPUS="{cpus}"
GPUS="{gpus}"

JOB_ID="${{SLURM_JOB_ID}}"
RUN_PREFIX="runs/${{RUN_ID}}/slurm_${{JOB_ID}}"

LOCAL_BASE="${{TMPDIR:-/tmp}}/namd_cuda_${{JOB_ID}}"
INPUT_DIR="${{LOCAL_BASE}}/input"
WORK_DIR="${{INPUT_DIR}}/${{WORK_SUBDIR}}"
OUTPUT_DIR="${{LOCAL_BASE}}/outputs"
LOG_DIR="${{LOCAL_BASE}}/logs"
META_DIR="${{LOCAL_BASE}}/metadata"

mkdir -p "$INPUT_DIR" "$OUTPUT_DIR" "$LOG_DIR" "$META_DIR"

AWS_BIN="$(command -v aws || true)"

if [ -z "$AWS_BIN" ]; then
  if [ -x "$HOME/bin/aws" ]; then
    AWS_BIN="$HOME/bin/aws"
  elif [ -x "$HOME/aws-cli/v2/current/bin/aws" ]; then
    AWS_BIN="$HOME/aws-cli/v2/current/bin/aws"
  else
    echo "[ERROR] aws command not found" | tee "$LOG_DIR/aws_error.log"
    exit 1
  fi
fi

export AWS_CONFIG_FILE="$LOCAL_BASE/aws_config"
cat > "$AWS_CONFIG_FILE" << AWS_CONFIG_EOF
[default]
s3 =
    multipart_threshold = 5GB
    multipart_chunksize = 64MB
AWS_CONFIG_EOF

upload_results() {{
  EXIT_CODE="$?"

  echo "$EXIT_CODE" > "$META_DIR/exit_code.txt"

  cat > "$META_DIR/metadata.json" << META_EOF
{{
  "job_id": "${{JOB_ID}}",
  "job_name": "${{SLURM_JOB_NAME}}",
  "run_id": "${{RUN_ID}}",
  "work_subdir": "${{WORK_SUBDIR}}",
  "node": "$(hostname)",
  "cpus": "${{CPUS}}",
  "gpus": "${{GPUS}}",
  "namd_config": "${{NAMD_CONFIG}}",
  "exit_code": "${{EXIT_CODE}}",
  "minio_input": "s3://${{MINIO_BUCKET}}/inputs/${{RUN_ID}}/",
  "minio_run_prefix": "s3://${{MINIO_BUCKET}}/${{RUN_PREFIX}}/"
}}
META_EOF

  echo "[JOB] Uploading logs, outputs and metadata to MinIO"
  "$AWS_BIN" --endpoint-url "$MINIO_ENDPOINT" s3 cp --recursive "$LOG_DIR/" "s3://$MINIO_BUCKET/$RUN_PREFIX/logs/" || true
  "$AWS_BIN" --endpoint-url "$MINIO_ENDPOINT" s3 cp --recursive "$OUTPUT_DIR/" "s3://$MINIO_BUCKET/$RUN_PREFIX/outputs/" || true
  "$AWS_BIN" --endpoint-url "$MINIO_ENDPOINT" s3 cp --recursive "$META_DIR/" "s3://$MINIO_BUCKET/$RUN_PREFIX/metadata/" || true

  rm -rf "$LOCAL_BASE" || true
  exit "$EXIT_CODE"
}}

trap upload_results EXIT

echo "[JOB] Running on: $(hostname)" | tee "$LOG_DIR/job.log"
date | tee -a "$LOG_DIR/job.log"

echo "[JOB] Loading temporary AWS/MinIO credentials" | tee -a "$LOG_DIR/job.log"
source "$HPC_WORKDIR/sts_credentials.env"

echo "[JOB] Checking credential variables" | tee -a "$LOG_DIR/job.log"
echo "AWS_ACCESS_KEY_ID length: ${{#AWS_ACCESS_KEY_ID}}" | tee -a "$LOG_DIR/job.log"
echo "AWS_SESSION_TOKEN length: ${{#AWS_SESSION_TOKEN}}" | tee -a "$LOG_DIR/job.log"

echo "[JOB] Using AWS_BIN=$AWS_BIN" | tee -a "$LOG_DIR/job.log"
"$AWS_BIN" --version | tee "$LOG_DIR/aws_version.log"

echo "[JOB] Downloading input files from MinIO" | tee -a "$LOG_DIR/job.log"
"$AWS_BIN" --endpoint-url "$MINIO_ENDPOINT" s3 cp --recursive \\
  "s3://$MINIO_BUCKET/inputs/$RUN_ID/" \\
  "$INPUT_DIR/" | tee "$LOG_DIR/download.log"

echo "[JOB] Input files:" | tee -a "$LOG_DIR/job.log"
find "$INPUT_DIR" -maxdepth 4 -type f | sort | tee "$LOG_DIR/input_files.log"

echo "[JOB] Checking dataset working directory" | tee -a "$LOG_DIR/job.log"
if [ ! -d "$WORK_DIR" ]; then
  echo "[ERROR] Dataset working directory not found: $WORK_DIR" | tee -a "$LOG_DIR/job.log"
  exit 1
fi

echo "[JOB] Checking NAMD config" | tee -a "$LOG_DIR/job.log"
if [ ! -f "$WORK_DIR/$NAMD_CONFIG" ]; then
  echo "[ERROR] NAMD config not found: $WORK_DIR/$NAMD_CONFIG" | tee -a "$LOG_DIR/job.log"
  exit 1
fi

echo "[JOB] Checking NAMD SIF" | tee -a "$LOG_DIR/job.log"
ls -lh "$NAMD_SIF" | tee "$LOG_DIR/namd_sif.log"

echo "[JOB] GPU info" | tee -a "$LOG_DIR/job.log"
nvidia-smi | tee "$LOG_DIR/nvidia_smi.log"

echo "[JOB] Starting NAMD CUDA run" | tee -a "$LOG_DIR/job.log"
cd "$WORK_DIR"

env -u LD_PRELOAD apptainer run --nv "$NAMD_SIF" \\
  +p"$CPUS" +devices 0 "$NAMD_CONFIG" \\
  > "$LOG_DIR/namd.log" 2> "$LOG_DIR/namd.err"

echo "[JOB] NAMD finished successfully" | tee -a "$LOG_DIR/job.log"

echo "[JOB] Collecting output files" | tee -a "$LOG_DIR/job.log"

find "$INPUT_DIR" -maxdepth 2 -type f \
  \( -name "*.dcd" -o -name "*.coor" -o -name "*.vel" -o -name "*.xsc" -o -name "*.restart*" -o -name "*out*" -o -name "*.log" \) \
  -exec cp -v {{}} "$OUTPUT_DIR/" \; | tee "$LOG_DIR/collect_outputs.log"

echo "[JOB] Detecting visualization files" | tee -a "$LOG_DIR/job.log"

PDB_FILE="$(find "$INPUT_DIR" -type f -name "*.pdb" | head -n 1 || true)"
PSF_FILE="$(find "$INPUT_DIR" -type f -name "*.psf" | head -n 1 || true)"
DCD_FILE="$(find "$OUTPUT_DIR" -type f -name "*.dcd" | head -n 1 || true)"

if [ -n "$PDB_FILE" ]; then
  echo "VISUALIZATION_PDB=$(basename "$PDB_FILE")" | tee -a "$LOG_DIR/job.log"
fi

if [ -n "$PSF_FILE" ]; then
  echo "VISUALIZATION_PSF=$(basename "$PSF_FILE")" | tee -a "$LOG_DIR/job.log"
fi

if [ -n "$DCD_FILE" ]; then
  echo "VISUALIZATION_DCD=$(basename "$DCD_FILE")" | tee -a "$LOG_DIR/job.log"
fi

echo "VISUALIZATION_RUN_ID=$RUN_ID" | tee -a "$LOG_DIR/job.log"
echo "VISUALIZATION_JOB_ID=$JOB_ID" | tee -a "$LOG_DIR/job.log"

echo "[JOB] Done" | tee -a "$LOG_DIR/job.log"
date | tee -a "$LOG_DIR/job.log"
"""


def make_remote_script(
    *,
    hpc_workdir: str,
    cred_b64: str,
    run_id: str,
    job_name: str,
    namd_config_name: str,
    work_subdir: str,
    cpus: str,
    gpus: str,
    partition: str = "bare-metal-GPU",
) -> str:
    slurm_script = make_slurm_script(
        job_name=job_name,
        run_id=run_id,
        namd_config_name=namd_config_name,
        work_subdir=work_subdir,
        hpc_workdir=hpc_workdir,
        cpus=cpus,
        gpus=gpus,
        partition=partition,
    )

    return f"""set -euo pipefail

echo "[HPC login] Connected successfully"
hostname
whoami
pwd

echo "[HPC login] Creating working directory"
mkdir -p "{hpc_workdir}"
cd "{hpc_workdir}"

echo "[HPC login] Writing temporary STS credentials file"
echo "{cred_b64}" | base64 -d > sts_credentials.env
chmod 600 sts_credentials.env

echo "[HPC login] Checking credentials file"
ls -lh sts_credentials.env

echo "[HPC login] Writing SLURM job script"

cat > "{JOB_SCRIPT}" << 'SLURM_EOF'
{slurm_script}
SLURM_EOF

echo "[HPC login] Submitting job"
JOB_ID="$(sbatch --parsable "{JOB_SCRIPT}")"

echo "[HPC login] Job submitted: ${{JOB_ID}}"
echo "[HPC login] Waiting for job to finish..."

while squeue -h -j "$JOB_ID" | grep -q "$JOB_ID"; do
  sleep 10
done

sleep 3

echo "[HPC login] Job finished. Uploading login-node Slurm stdout/stderr to MinIO."

source ./sts_credentials.env

AWS_BIN="$(command -v aws || true)"
if [ -z "$AWS_BIN" ]; then
  if [ -x "$HOME/bin/aws" ]; then
    AWS_BIN="$HOME/bin/aws"
  elif [ -x "$HOME/aws-cli/v2/current/bin/aws" ]; then
    AWS_BIN="$HOME/aws-cli/v2/current/bin/aws"
  else
    echo "[HPC login ERROR] aws command not found"
    exit 1
  fi
fi

echo "[HPC login] Ensuring NAMD container exists"

NAMD_SIF="{NAMD_SIF}"
NAMD_SIF_MINIO_PATH="{NAMD_SIF_MINIO_PATH}"

mkdir -p "$(dirname "$NAMD_SIF")"

if [ -f "$NAMD_SIF" ]; then
  echo "[HPC login] NAMD SIF already exists: $NAMD_SIF"
else
  echo "[HPC login] NAMD SIF not found. Downloading from MinIO..."
  "$AWS_BIN" --endpoint-url "{MINIO_ENDPOINT}" s3 cp \
    "$NAMD_SIF_MINIO_PATH" \
    "$NAMD_SIF"
  chmod 755 "$NAMD_SIF"
fi

RUN_PREFIX="runs/{run_id}/slurm_${{JOB_ID}}"

if [ -f "namd_cuda_${{JOB_ID}}.out" ]; then
  "$AWS_BIN" --endpoint-url "{MINIO_ENDPOINT}" s3 cp \\
    "namd_cuda_${{JOB_ID}}.out" \\
    "s3://{MINIO_BUCKET}/${{RUN_PREFIX}}/login_logs/namd_cuda_${{JOB_ID}}.out" || true
fi

if [ -f "namd_cuda_${{JOB_ID}}.err" ]; then
  "$AWS_BIN" --endpoint-url "{MINIO_ENDPOINT}" s3 cp \\
    "namd_cuda_${{JOB_ID}}.err" \\
    "s3://{MINIO_BUCKET}/${{RUN_PREFIX}}/login_logs/namd_cuda_${{JOB_ID}}.err" || true
fi

rm -f sts_credentials.env || true

echo
echo "======================================"
echo " Job completed"
echo " Job ID: ${{JOB_ID}}"
echo
echo " MinIO output path:"
echo " s3://{MINIO_BUCKET}/runs/{run_id}/slurm_${{JOB_ID}}/"
echo
echo " Local Slurm files:"
echo " {hpc_workdir}/namd_cuda_${{JOB_ID}}.out"
echo " {hpc_workdir}/namd_cuda_${{JOB_ID}}.err"
echo "======================================"
"""
