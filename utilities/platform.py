import sys
import os

def checkEnv() -> str:
    platform = sys.platform
    n_cpus = os.cpu_count()
    conda_env = os.getenv("CONDA_DEFAULT_ENV", None)
    venv = os.getenv("VIRTUAL_ENV", None)
    if conda_env is None and venv is None:
        print(">>> Warning: No virtual environment detected. It's recommended to use a virtual environment to avoid dependency conflicts.")
    python_version = sys.version.split()[0]
    print(">>> System Information")
    print("Platform :", platform)
    if conda_env:
        print("Conda    :", conda_env)
    if venv:
        print("VENV     :", venv)
    print("Python   :", python_version)
    print("CPUs     :", n_cpus)
    print("Current  :", os.getcwd())