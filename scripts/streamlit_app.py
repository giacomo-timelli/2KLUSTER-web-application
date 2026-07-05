import os
import re
import subprocess
import tempfile
from urllib.parse import quote

import streamlit as st


MINIO_PUBLIC_BASE_URL = "<MINIO_PUBLIC_BASE_URL>"
MOLSTAR_URL = "<MOLSTAR_URL>"
GPU_PARTITION = "<GPU_PARTITION>"
WORKFLOW_PUBLIC_KEY = "<WORKFLOW_PUBLIC_KEY>"


def should_hide_log_line(line):
    hidden_patterns = [
        "..........",
        "Saving to:",
        "Length:",
        "Resolving ",
        "Connecting to ",
        "HTTP request sent",
        "Completed ",
        "upload:",
        "download:",
    ]
    return any(pattern in line for pattern in hidden_patterns)


def run_command_live(command, env):
    log_box = st.empty()
    logs = ""

    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        env=env,
    )

    for line in process.stdout:
        logs += line

        if not should_hide_log_line(line):
            visible_logs = "\n".join(
                log_line for log_line in logs.splitlines()
                if not should_hide_log_line(log_line)
            )
            log_box.code(visible_logs)

    process.wait()
    return process.returncode, logs


def extract_visualization_value(logs, key):
    match = re.search(rf"{key}=([^\n\r]+)", logs)
    if match:
        return match.group(1).strip()
    return None


def extract_job_id(logs):
    marker_job_id = extract_visualization_value(logs, "VISUALIZATION_JOB_ID")
    if marker_job_id:
        return marker_job_id

    match = re.search(r"Job ID:\s*([0-9]+)", logs)
    if match:
        return match.group(1)

    match = re.search(r"Job submitted:\s*([0-9]+)", logs)
    if match:
        return match.group(1)

    return None


def build_visualization_url(bucket, object_path):
    encoded_object_path = quote(object_path, safe="")
    return f"{MINIO_PUBLIC_BASE_URL}/{bucket}/{encoded_object_path}"


def show_visualization_links(logs):
    bucket = os.getenv("MINIO_BUCKET", "<BUCKET_NAME>")

    run_id = extract_visualization_value(logs, "VISUALIZATION_RUN_ID")
    input_subdir = extract_visualization_value(logs, "VISUALIZATION_INPUT_SUBDIR")
    job_id = extract_job_id(logs)

    pdb_file = extract_visualization_value(logs, "VISUALIZATION_PDB")
    psf_file = extract_visualization_value(logs, "VISUALIZATION_PSF")
    dcd_file = extract_visualization_value(logs, "VISUALIZATION_DCD")

    if not run_id:
        st.warning("Could not detect the run ID for visualization links.")
        return

    if not input_subdir:
        st.warning("Could not detect the input dataset directory for visualization links.")
        return

    if not job_id:
        st.warning("Could not detect the Slurm job ID for visualization links.")
        return

    st.subheader("Visualization")

    st.markdown(f"[Open MolStar]({MOLSTAR_URL})")

    st.info(
        "Open MolStar and use the URLs below in the download section "
        "to visualize the simulation."
    )

    if pdb_file:
        pdb_object = f"inputs/{run_id}/{input_subdir}/{pdb_file}"
        pdb_url = build_visualization_url(bucket, pdb_object)
        st.write("PDB URL")
        st.code(pdb_url, language=None)
    else:
        st.warning("No PDB file was detected from the input files.")

    if psf_file:
        psf_object = f"inputs/{run_id}/{input_subdir}/{psf_file}"
        psf_url = build_visualization_url(bucket, psf_object)
        st.write("PSF URL")
        st.code(psf_url, language=None)
    else:
        st.warning("No PSF file was detected from the input files.")

    if dcd_file:
        dcd_object = f"runs/{run_id}/slurm_{job_id}/outputs/{dcd_file}"
        dcd_url = build_visualization_url(bucket, dcd_object)
        st.write("DCD URL")
        st.code(dcd_url, language=None)
    else:
        st.warning("No DCD file was detected from the NAMD configuration.")

    st.caption(
        f"Run ID: `{run_id}` | Slurm Job ID: `{job_id}` | Dataset directory: `{input_subdir}`"
    )


st.set_page_config(page_title="NAMD Workflow Launcher", layout="centered")

st.title("NAMD Workflow Launcher")
st.write("Simple interface for launching CUDA-enabled NAMD workflows on Slurm.")


if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

if "auth_env" not in st.session_state:
    st.session_state.auth_env = {}


st.header("Authentication")

hpc_user = st.text_input("HPC username", key="auth_hpc_user")
oidc_agent = st.text_input("OIDC agent shortname", key="auth_oidc_agent")
oidc_password = st.text_input("OIDC password", type="password", key="auth_oidc_password")


st.subheader("First-time HPC SSH setup")

show_ssh_setup = st.checkbox(
    "I have not added the workflow SSH key to my HPC account yet",
    key="show_ssh_setup",
)

if show_ssh_setup:
    st.info(
        "If this is your first time using the workflow, connect once to the HPC login node "
        "with your normal HPC password and run the command below. After that, "
        "come back here and click Validate Authentication."
    )

    setup_command = (
        "mkdir -p ~/.ssh && chmod 700 ~/.ssh && "
        "touch ~/.ssh/authorized_keys && "
        f"grep -qxF '{WORKFLOW_PUBLIC_KEY}' ~/.ssh/authorized_keys || "
        f"echo '{WORKFLOW_PUBLIC_KEY}' >> ~/.ssh/authorized_keys && "
        "chmod 600 ~/.ssh/authorized_keys"
    )

    st.write("Run this command on the HPC login node:")
    st.code(setup_command, language="bash")


create_oidc = st.checkbox(
    "I do not have an OIDC account yet",
    key="show_create_oidc",
)

if create_oidc:
    st.subheader("Create New OIDC Account")

    new_oidc_shortname = st.text_input(
        "New OIDC shortname",
        key="new_oidc_shortname",
    )

    new_oidc_password = st.text_input(
        "New OIDC encryption password",
        type="password",
        key="new_oidc_password",
    )

    new_oidc_password_confirm = st.text_input(
        "Confirm OIDC encryption password",
        type="password",
        key="new_oidc_password_confirm",
    )

    if st.button("Create OIDC Account", key="create_oidc_button"):
        if not new_oidc_shortname:
            st.error("Please provide a new OIDC shortname.")
            st.stop()

        if not new_oidc_password:
            st.error("Please provide an encryption password.")
            st.stop()

        if new_oidc_password != new_oidc_password_confirm:
            st.error("Passwords do not match.")
            st.stop()

        st.info(
            "A device authorization link and code will appear below. "
            "Open the link, log in, enter the code, approve the device, "
            "and then wait until the process completes."
        )

        env = os.environ.copy()
        env["OIDC_NEW_PASSWORD"] = new_oidc_password

        command = [
            "python3",
            "-u",
            "create_oidc_account.py",
            "--shortname",
            new_oidc_shortname,
        ]

        returncode, logs = run_command_live(command, env)

        if returncode == 0:
            st.success(
                "OIDC account created successfully. "
                "You can now enter this shortname and password above, "
                "then click Validate Authentication."
            )
        else:
            st.error("OIDC account creation failed.")


if st.button("Validate Authentication", key="validate_auth_button"):
    if not hpc_user or not oidc_agent or not oidc_password:
        st.error("Please fill in all authentication fields.")
        st.stop()

    env = os.environ.copy()
    env["HPC_USER"] = hpc_user
    env["OIDC_AGENT"] = oidc_agent
    env["OIDC_PASSWORD"] = oidc_password

    result = subprocess.run(
        ["python3", "-u", "check_auth.py"],
        env=env,
        capture_output=True,
        text=True,
    )

    if result.returncode == 0:
        st.session_state.authenticated = True
        st.session_state.auth_env = {
            "HPC_USER": hpc_user,
            "OIDC_AGENT": oidc_agent,
            "OIDC_PASSWORD": oidc_password,
        }
        st.success("Authentication successful.")
        st.code(result.stdout)
    else:
        st.session_state.authenticated = False
        st.session_state.auth_env = {}
        st.error("Authentication failed.")
        st.code(result.stdout + "\n" + result.stderr)


if st.session_state.authenticated:
    st.divider()

    st.header("Workflow Parameters")

    molecule_url = st.text_input(
        "Molecule dataset URL",
        placeholder="https://www.ks.uiuc.edu/Research/namd/utilities/apoa1.tar.gz",
        key="molecule_url",
    )

    st.caption(
        "Example: https://www.ks.uiuc.edu/Research/namd/utilities/apoa1.tar.gz"
    )

    namd_file = st.file_uploader(
        "Upload your custom .namd configuration file",
        type=["namd"],
        key="namd_file",
    )

    st.text_input(
        "Slurm partition",
        value=GPU_PARTITION,
        disabled=True,
        key="slurm_partition",
    )

    gpus = st.number_input("GPUs", min_value=1, max_value=4, value=1, key="gpus")
    cpus = st.number_input("CPUs", min_value=1, max_value=192, value=64, key="cpus")

    job_name = st.text_input("Job name", value="namd_cuda_run", key="job_name")

    st.header("Submit")

    dry_run = st.checkbox("Dry run only", value=True, key="dry_run")

    if st.button("Submit Job", key="submit_job_button"):
        if not molecule_url:
            st.error("Please provide a molecule dataset URL.")
            st.stop()

        if namd_file is None:
            st.error("Please upload a custom .namd file.")
            st.stop()

        env = os.environ.copy()
        env.update(st.session_state.auth_env)

        env["MINIO_BUCKET"] = os.getenv("MINIO_BUCKET", "<BUCKET_NAME>")

        st.info(
            "You can follow the live workflow logs below while the job is running. "
            "After the workflow finishes, scroll down to access the MolStar link "
            "and the generated output URLs for visualizing your simulation."
        )

        with tempfile.NamedTemporaryFile(delete=False, suffix=".namd") as tmp:
            tmp.write(namd_file.getbuffer())
            local_namd_path = tmp.name

        command = [
            "python3",
            "-u",
            "run_namd_workflow.py",
            "--molecule-url",
            molecule_url,
            "--namd-config",
            local_namd_path,
            "--partition",
            GPU_PARTITION,
            "--gpus",
            str(gpus),
            "--cpus",
            str(cpus),
            "--job-name",
            job_name,
            "--overwrite-inputs",
        ]

        st.subheader("Live Workflow Log")

        if dry_run:
            st.info("Dry run enabled. The workflow command was not executed.")
            st.code(" ".join(command))
        else:
            returncode, logs = run_command_live(command, env)

            if returncode == 0:
                st.success("Workflow completed successfully.")
                show_visualization_links(logs)
            else:
                st.error("Workflow failed.")
