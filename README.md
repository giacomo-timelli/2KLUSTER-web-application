# 2KLUSTER-web-application

This repository contains the source code and workflow scripts of the **2KLUSTER web application**, developed as part of a Proof-of-Concept platform for integrating Cloud-native services with High Performance Computing resources.

The application provides a simplified interface for submitting molecular dynamics jobs from a Kubernetes-based environment to an external Slurm-based HPC backend. It supports user interaction through a Streamlit web interface, object storage access through MinIO, OIDC-based authentication through INDIGO-IAM, and job execution on HPC using Slurm and Apptainer.

The deployment manifests and infrastructure configuration of the complete 2KLUSTER platform are maintained in the main repository:

[2KLUSTER deployment repository](https://github.com/giacomo-timelli/2KLUSTER)

## Overview

The 2KLUSTER web application acts as the user-facing layer of the platform.

Its main responsibilities are:

* collecting user authentication data and workflow parameters;
* validating OIDC and SSH-based access;
* downloading and preparing molecular dynamics input datasets;
* uploading input files to MinIO object storage;
* generating a Slurm job script dynamically;
* submitting the workload to the HPC backend through a bridge VM;
* executing NAMD with CUDA support inside an Apptainer container;
* uploading logs, metadata and output files back to MinIO;
* providing visualization URLs that can be used with Mol*.

The application was designed for a molecular dynamics use case based on NAMD, but the general structure can be adapted to other scientific workflows requiring Cloud-to-HPC offloading.

## Application workflow

![Job path](job_path.png)

## Scripts overview

### `streamlit_app.py`

Main entry point of the web application.

It defines the Streamlit user interface used to:

* insert the HPC username;
* insert the OIDC account shortname and password;
* optionally create a new OIDC account;
* validate authentication;
* upload a custom `.namd` configuration file;
* provide the molecular dataset URL;
* configure basic Slurm parameters such as CPUs, GPUs and job name;
* submit the workflow;
* display live logs;
* generate output URLs for Mol* visualization.

### `config.py`

Centralized configuration file.

It reads the required environment variables used by the application, including:

* HPC username;
* OIDC account information;
* bridge VM connection parameters;
* HPC login node hostname;
* MinIO endpoint and bucket;
* remote HPC working directory;
* NAMD Apptainer image path;
* default Slurm parameters.

If a required environment variable is missing, the script raises an error to prevent the workflow from running with incomplete configuration.

### `check_auth.py`

Authentication validation script.

It verifies that the user can correctly access both the identity and HPC layers of the platform.

The script checks:

* initialization of `oidc-agent`;
* loading of the selected OIDC account;
* generation of an OIDC token;
* SSH connectivity to the HPC login node through the bridge VM.

This script is executed before allowing the user to submit a workflow.

### `create_oidc_account.py`

Helper script for creating a new OIDC account inside the application workflow.

It uses `oidc-agent` and `oidc-gen` to guide the user through the device authorization flow with INDIGO-IAM. The generated account can then be used by the application to request OIDC tokens.

### `run_namd_workflow.py`

Main workflow orchestration script.

It coordinates the complete execution flow from the Streamlit container to the HPC backend.

Its responsibilities include:

* creating a unique `run_id`;
* initializing `oidc-agent`;
* generating temporary S3-compatible credentials;
* downloading and extracting the molecular dataset;
* copying the uploaded NAMD configuration file into the dataset directory;
* detecting relevant visualization files, such as `.pdb`, `.psf` and `.dcd`;
* uploading input files to MinIO;
* generating the remote Slurm workflow;
* sending the remote script to the HPC login node through the bridge VM.

### `hpc_client.py`

SSH communication module.

It handles the connection from the application container to the HPC login node through the bridge VM.

The connection uses SSH with a `ProxyCommand`, allowing the workflow to reach the HPC backend while preserving the separation between the Kubernetes environment and the HPC infrastructure.

The script also includes retry logic to make the remote execution more robust.

### `slurm_template.py`

Slurm script generation module.

It dynamically creates the Slurm job script used to execute the molecular dynamics workload on the HPC backend.

The generated Slurm script:

* requests CPU and GPU resources;
* prepares temporary working directories on the compute node;
* loads temporary MinIO/S3 credentials;
* downloads input files from MinIO;
* checks the NAMD Apptainer image;
* runs NAMD with CUDA support using Apptainer;
* collects output files, logs and metadata;
* uploads results back to MinIO.

### `login_sts.py`

Placeholder for the OIDC-to-STS credential generation step.

In the complete workflow, this component is responsible for obtaining temporary S3-compatible credentials starting from an OIDC-authenticated session.

The original implementation is not included in the public repository.

### `submit_namd_cuda_workflow.sh`

Sanitized shell version of the workflow.

This script represents an earlier or standalone version of the Cloud-to-HPC workflow. It shows the same general logic implemented by the Python application:

```text
OIDC authentication → temporary S3 credentials → bridge VM → HPC login node → Slurm job → NAMD CUDA → MinIO upload
```

Before being used, placeholder values must be replaced with infrastructure-specific configuration.

### `requirements.txt`

Python dependencies required by the web application.

```text
streamlit
requests
```

Additional packages, such as `pexpect`, are installed directly inside the Dockerfile.

## Required environment variables

The application expects several environment variables to be provided at runtime.

Main variables include:

```text
HPC_USER
OIDC_AGENT
OIDC_PASSWORD

BRIDGE_USER
BRIDGE_HOST
HPC_LOGIN

MINIO_CLIENT_ID
MINIO_ENDPOINT
MINIO_BUCKET

REMOTE_BASE_DIR
```

## Run locally

A local execution requires the same environment variables expected in the Kubernetes deployment.

Example:

```bash
export HPC_USER="<HPC_USERNAME>"
export OIDC_AGENT="<OIDC_AGENT_SHORTNAME>"
export OIDC_PASSWORD="<OIDC_PASSWORD>"

export BRIDGE_USER="<BRIDGE_USER>"
export BRIDGE_HOST="<BRIDGE_HOST>"
export HPC_LOGIN="<HPC_LOGIN_NODE>"

export MINIO_CLIENT_ID="<MINIO_CLIENT_ID>"
export MINIO_ENDPOINT="<MINIO_ENDPOINT>"
export MINIO_BUCKET="<MINIO_BUCKET>"

export REMOTE_BASE_DIR="<REMOTE_HPC_BASE_DIR>"

streamlit run streamlit_app.py
```

For a container-based execution:

```bash
docker run --rm -p 8501:8501 \
  -e HPC_USER="<HPC_USERNAME>" \
  -e OIDC_AGENT="<OIDC_AGENT_SHORTNAME>" \
  -e OIDC_PASSWORD="<OIDC_PASSWORD>" \
  -e BRIDGE_USER="<BRIDGE_USER>" \
  -e BRIDGE_HOST="<BRIDGE_HOST>" \
  -e HPC_LOGIN="<HPC_LOGIN_NODE>" \
  -e MINIO_CLIENT_ID="<MINIO_CLIENT_ID>" \
  -e MINIO_ENDPOINT="<MINIO_ENDPOINT>" \
  -e MINIO_BUCKET="<MINIO_BUCKET>" \
  -e REMOTE_BASE_DIR="<REMOTE_HPC_BASE_DIR>" \
  2kluster-web-application
```

Depending on the target environment, SSH keys and additional secrets must also be mounted inside the container.

## Input data

The application expects:

* a molecular dataset URL, for example a `.tar.gz` archive;
* a custom NAMD configuration file with `.namd` extension.

During execution, the dataset is downloaded and extracted inside the application container. The uploaded NAMD configuration is copied into the dataset directory and used as the input configuration for the remote NAMD execution.

## Output organization

The workflow organizes files in MinIO using a unique run identifier.

A simplified structure is:

```text
inputs/<run_id>/
runs/<run_id>/slurm_<job_id>/
├── logs/
├── outputs/
├── metadata/
└── login_logs/
```

The output directory contains the simulation results produced by NAMD, while logs and metadata are stored separately to make debugging and workflow tracking easier.

## Visualization

After a successful run, the application extracts information from the workflow logs and generates URLs for files useful for visualization, such as:

* `.pdb`;
* `.psf`;
* `.dcd`.

These URLs can be used with Mol* to inspect molecular structures and simulation trajectories from the browser.

## Runtime and configuration parameters

The application uses two main types of parameters:

- **Fixed configuration parameters**, defined at deployment time through environment variables;
- **User-provided parameters**, inserted through the Streamlit web interface when submitting a workflow.

### Fixed configuration parameters

These parameters are infrastructure-dependent and are normally populated through the Kubernetes deployment manifests.

| Variable | Type | Description | Example / Placeholder |
| --- | --- | --- | --- |
| `BRIDGE_USER` | Fixed configuration | Username used to access the bridge virtual machine. | `<BRIDGE_USER>` |
| `BRIDGE_HOST` | Fixed configuration | Hostname or IP address of the bridge virtual machine. | `<BRIDGE_HOST>` |
| `HPC_LOGIN` | Fixed configuration | Hostname of the HPC login node reached through the bridge VM. | `<HPC_LOGIN_NODE>` |
| `MINIO_CLIENT_ID` | Fixed configuration | Client ID used for the OIDC/STS interaction with MinIO. | `<MINIO_CLIENT_ID>` |
| `MINIO_ENDPOINT` | Fixed configuration | S3-compatible endpoint of the MinIO service. | `<MINIO_ENDPOINT>` |
| `MINIO_BUCKET` | Fixed configuration | Name of the MinIO bucket used to store inputs, outputs, logs and metadata. | `<MINIO_BUCKET>` |
| `REMOTE_BASE_DIR` | Fixed configuration | Base working directory used on the remote HPC environment. | `<REMOTE_HPC_BASE_DIR>` |
| `LOCAL_WORKDIR` | Fixed configuration | Local working directory inside the application container. | `/tmp/2kluster` |
| `NAMD_SIF` | Fixed configuration | Path of the NAMD Apptainer image on the HPC system. | `<NAMD_SIF_PATH>` |
| `NAMD_SIF_MINIO_PATH` | Fixed configuration | Optional MinIO path used to retrieve the NAMD Apptainer image. | `<NAMD_SIF_MINIO_PATH>` |
| `JOB_SCRIPT` | Fixed configuration | Name of the Slurm job script generated by the workflow. | `submit_namd_cuda_workflow.sh` |

### User-provided workflow parameters

These parameters are inserted by the user through the web interface before submitting a job.

| Parameter | Type | Description |
| --- | --- | --- |
| HPC username | User-provided parameter | Username used for the remote HPC execution. |
| OIDC account shortname | User-provided parameter | Name of the OIDC account configured through `oidc-agent`. |
| OIDC password | User-provided parameter | Password used to unlock the selected OIDC account. |
| Dataset URL | User-provided parameter | URL of the molecular dynamics input dataset. |
| NAMD configuration file | User-provided parameter | Custom `.namd` configuration file uploaded by the user. |
| Job name | User-provided parameter | Name assigned to the Slurm job and to the workflow run. |
| CPUs per task | User-provided parameter | Number of CPU cores requested for the Slurm job. |
| GPU count | User-provided parameter | Number of GPUs requested for the Slurm job. |
| Slurm partition | User-provided parameter | Partition where the job is submitted. |

### Default workflow parameters

Some workflow values can be preconfigured as defaults and then adjusted by the user through the interface.

| Variable | Type | Description | Default / Placeholder |
| --- | --- | --- | --- |
| `DEFAULT_CPUS_PER_TASK` | Default parameter | Default number of CPU cores requested for each Slurm task. | `4` |
| `DEFAULT_GPU_COUNT` | Default parameter | Default number of GPUs requested for the job. | `1` |
| `DEFAULT_PARTITION` | Default parameter | Default Slurm partition used for job submission. | `<SLURM_PARTITION>` |

## Security notes

This repository contains a public and sanitized version of the application workflow.

Before using it in a real deployment, consider the following aspects:

* do not commit passwords, client secrets, access keys or private SSH keys;
* mount SSH keys through Kubernetes Secrets or another secure mechanism;
* rotate exposed or temporary credentials;
* restrict MinIO policies according to the principle of least privilege;
* ensure that OIDC tokens are issued by the expected INDIGO-IAM provider;
* avoid exposing internal infrastructure hostnames in public configuration files;
* replace placeholder values before deployment;
* review the STS credential generation component before production usage.

## Status

This repository is part of an academic Proof-of-Concept and is not intended to be used as a production-ready application without further hardening.

The current version demonstrates the integration between:

* Kubernetes;
* Streamlit;
* INDIGO-IAM;
* MinIO;
* SSH bridge access;
* Slurm;
* Apptainer;
* NAMD CUDA;
* Mol* visualization.

## License

This project is licensed under the Apache License 2.0. See the `LICENSE` file for details.
