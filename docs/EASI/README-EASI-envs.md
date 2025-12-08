# Python Environments for EASI, Jupyter & VS Code

This README explains how to manage Python environments for:

- **EASI JupyterLab** (CSIRO EASI)
- **Local development** (VS Code on your own machine)

It covers:

- Why EASI uses **`venv` + `pip`** (and not conda directly)
- How to create and use **virtual environments on EASI**
- How to use **conda locally** and mirror that environment onto EASI
- How to make your environments available in **Jupyter** and **VS Code**

---

## 1. Overview: conda vs venv on EASI

### EASI reality

On EASI:

- The JupyterLab images already run inside a **Python virtual environment (`venv`)**.
- `pip install --user` **does not work** inside EASI (this is typical for venv-based setups).
- EASI’s official docs describe how to create **additional `venv`s**, not conda environments.
- `conda` / `mamba` are **not installed** by default, and installing them in `$HOME` is possible but **unsupported and error-prone** (conflicting Pythons, large disk use, Dask mismatch, etc.).

**Recommended pattern on EASI:**

> Use **`python -m venv` + `pip`** to create a per-project environment in `~/venvs/`, and register it as a Jupyter kernel.

### Where conda fits in

- **Locally** (your laptop, VS Code), conda is great for:
  - Heavy geospatial stacks
  - GPU / compiled libraries
  - Managing multiple projects
- On **EASI**, the safest conda-related workflow is:
  1. Build and test a conda env **locally**.
  2. Export a `requirements.txt` (pip style).
  3. Recreate a **`venv` on EASI** and `pip install -r requirements.txt`.

You *can* install Miniconda on EASI, but it is advanced and not officially supported, so this README focuses on the **supported `venv` approach** on EASI and **conda locally**.

---

## 2. EASI: Creating a `venv` environment (recommended)

### 2.1 Create a new environment in an EASI JupyterLab Terminal

In EASI JupyterLab:

1. Open **Launcher → Terminal**.
2. Run:

```bash
# 1. Choose a name for your env
MYENV=eds-env    # change this per project if you like

# 2. Get the Python version string used by the EASI image
PYVERSION=$(python3 --version | awk '{print tolower($1$2)}' | sed 's/\.[0-9]*$//')

# 3. Create the venv under ~/venvs
python -m venv ~/venvs/$MYENV

# 4. Link EASI's base site-packages into your venv
#    so you still see all the default EASI packages
realpath /env/lib/$PYVERSION/site-packages > ~/venvs/$MYENV/lib/$PYVERSION/site-packages/base_venv.pth

This creates ~/venvs/eds-env and lets it “see” the base EASI packages.
```
## 2.2 Activate the environment and install extra packages

Still in the same Terminal:

```bash
# 5. Activate the new env
source ~/venvs/$MYENV/bin/activate

# 6. Optional: upgrade pip
pip install --upgrade pip

# 7. Install extra packages you need
#    (example only – adjust to your project)
pip install pystac stackstac s3fs rioxarray geopandas

# 8. Register this env as a Jupyter kernel
python -m ipykernel install --user --name=$MYENV --display-name "EASI: $MYENV"

# 9. Deactivate when done
deactivate
```

You now have a new environment and a Jupyter kernel called EASI: eds-env.

## 2.3 Using the environment in EASI JupyterLab

In a notebook:

 - Go to Kernel → Change Kernel…

 - Select EASI: eds-env (or whatever display name you used).

From now on, imports and packages you installed into eds-env will work in that notebook.

## 2.4 Later: adding or updating packages on EASI

Whenever you want to change the environment:

```bash
MYENV=eds-env
source ~/venvs/$MYENV/bin/activate

# Add or upgrade packages
pip install --upgrade somepackage

deactivate

```

You do not need to reinstall the kernel each time; kernel installation is only needed once when the env is created.

----------------------------
# 3. Local conda environments (VS Code + Jupyter), and mirroring them to EASI
## 3.1 Create and use a conda environment locally

On your local machine (where conda is installed):

```bash
# Create a new conda env
conda create -n eds-local python=3.11

# Activate it
conda activate eds-local

# Install packages
conda install xarray numpy scipy
conda install -c conda-forge rioxarray geopandas s3fs

# Optional: install ipykernel so Jupyter sees it
python -m ipykernel install --user --name=eds-local --display-name "Local: eds-local"
```

Now you can:

 - In a local Jupyter notebook: choose “Local: eds-local” as the kernel.

 - In VS Code: select the eds-local conda interpreter.

## 3.2 Export conda env → requirements.txt for EASI

To mirror your conda env onto EASI:

```bash
conda activate eds-local

# Export pip-style requirements for EASI
pip freeze > requirements.txt

```

Upload requirements.txt to EASI (drag-and-drop into JupyterLab).

On EASI, inside your venv:

```bash
MYENV=eds-env
source ~/venvs/$MYENV/bin/activate

pip install -r requirements.txt

deactivate
```

-------------------

# 4. Jupyter integration summary
## 4.1 EASI JupyterLab

Create a venv (as above), then:

```bash
python -m ipykernel install --user --name=$MYENV --display-name "EASI: $MYENV"
```
In the notebook:

Go to Kernel → Change Kernel…

Select “EASI: $MYENV”

## 4.2 Local Jupyter (conda or venv)

For a local conda env:

```bash
conda activate eds-local
python -m ipykernel install --user --name=eds-local --display-name "Local: eds-local"

```
For a local venv:

```bash
python -m venv .venv
# Linux/macOS:
source .venv/bin/activate
# Windows PowerShell:
# .venv\Scripts\Activate.ps1

pip install ipykernel
python -m ipykernel install --user --name=project-venv --display-name "Local: project-venv"

```


Then in Jupyter (or VS Code’s notebook UI), select the kernel you created.

# 5. VS Code integration summary
## 5.1 Local VS Code

For Python scripts and terminals:

1. Press Ctrl+Shift+P → Python: Select Interpreter.

2. Choose:

  - Conda: eds-local (your conda env), or

  - Python 3.x ('.venv': venv) for a local venv.

VS Code will:

 - Use that interpreter for the integrated terminal.

 - Use that interpreter when running or debugging Python files.

For notebooks:

 - Use the kernel picker in the top-right of the notebook editor.

 - Choose the matching kernel name (e.g. Local: eds-local or Local: project-venv).

## 5.2 VS Code + Remote EASI (if you ever use SSH Remote)

If you connect to the EASI Jupyter host via VS Code Remote SSH:

- VS Code runs on the remote host, so:

  - It will see venvs under ~/venvs.

  - You can select ~/venvs/eds-env/bin/python as the interpreter.

 - For notebooks, it will also list Jupyter kernels you created via ipykernel install.

Workflow:

 1. Connect to EASI with Remote SSH in VS Code.

 2. Open the project folder.

 3. Select interpreter: ~/venvs/eds-env/bin/python.

 4.  For notebooks, choose kernel: “EASI: eds-env”.

---------------------------
# 6. Managing and cleaning up environments
## 6.1 Listing available Jupyter kernels

```bash
jupyter kernelspec list
```

## 6.2 Removing a kernel

```bash
jupyter kernelspec uninstall myenv
```

## 6.3 Deleting a venv on EASI

```bash
rm -rf ~/venvs/eds-env
```

(Do this only after you’ve uninstalled the corresponding kernel.)

# 7. Common issues & tips

 - pip install --user fails on EASI

This is expected. Always create a venv in ~/venvs and pip install inside it (no --user flag).

 - Kernel appears but cells don’t run

Most common cause: the venv was created for a different Python version than the one in the current EASI image. Recreate the venv using the PYVERSION trick and realpath /env/lib/$PYVERSION/....

 - Package works locally but fails on EASI

Check whether the package is available on pip. If it’s conda-only, you may need:

  - A pip-equivalent package, or

  - To request it in the base EASI image.

 - Disk usage

Delete unused venvs and kernels:

```bash
rm -rf ~/venvs/old-env
jupyter kernelspec uninstall old-env
```

-------------

This README is designed so you can:

 - Use conda locally (and in VS Code),

 - Use venv + pip on EASI,

 - Keep the two reasonably in sync through requirements.txt,

 - And work smoothly in Jupyter on both sides.


```makefile
::contentReference[oaicite:0]{index=0}

```