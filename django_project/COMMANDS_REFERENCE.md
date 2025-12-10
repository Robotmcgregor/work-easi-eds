# Command Reference: Old (Conda) vs New (venv)

## Side-by-Side Comparison

| Task | Old Way (Conda) ❌ | New Way (venv) ✅ |
|------|------------------|-----------------|
| **Start Server** | `.\django.bat runserver` | `.\run.bat runserver` |
| **Check Config** | `.\django.bat check` | `.\run.bat check` |
| **Run Migrations** | `.\django.bat migrate` | `.\run.bat migrate` |
| **Create User** | `.\django.bat createsuperuser` | `.\run.bat createsuperuser` |
| **Django Shell** | `.\django.bat shell` | `.\run.bat shell` |
| **Change Password** | `.\django.bat changepassword [user]` | `.\run.bat changepassword [user]` |
| **Any Command** | `.\django.bat [command]` | `.\run.bat [command]` |

---

## What Internally Happens

### Old Way (Conda)
```powershell
.\django.bat runserver

# Internally calls:
# conda run -n slats python manage.py runserver

# Which requires:
# 1. Conda installed on system
# 2. "slats" environment created
# 3. Django installed in that environment
# 4. Conda to be active/available
```

### New Way (venv)
```powershell
.\run.bat runserver

# Internally calls:
# venv\Scripts\python.exe manage.py runserver

# Which requires:
# 1. Python installed on system (that's it!)
# 2. venv folder in your project
# 3. Django installed in that venv
```

---

## Complete Command Examples

### Starting the Development Server

**Old:**
```powershell
cd c:\Users\DCCEEW\code\work-easi-eds\django_project
.\django.bat runserver
```

**New:**
```powershell
cd c:\Users\DCCEEW\code\work-easi-eds\django_project
.\run.bat runserver
```

**Access:** http://127.0.0.1:8000/admin/

---

### Running Database Migrations

**Old:**
```powershell
.\django.bat migrate
```

**New:**
```powershell
.\run.bat migrate
```

---

### Creating a Superuser

**Old:**
```powershell
.\django.bat createsuperuser
# Then enter: username, email, password
```

**New:**
```powershell
.\run.bat createsuperuser
# Then enter: username, email, password
```

---

### Opening Python Shell

**Old:**
```powershell
.\django.bat shell
# Then you can run Python commands
```

**New:**
```powershell
.\run.bat shell
# Then you can run Python commands
```

---

### Checking Configuration

**Old:**
```powershell
.\django.bat check
# Output: System check identified no issues (0 silenced).
```

**New:**
```powershell
.\run.bat check
# Output: System check identified no issues (0 silenced).
```

---

### Collecting Static Files

**Old:**
```powershell
.\django.bat collectstatic --noinput
```

**New:**
```powershell
.\run.bat collectstatic --noinput
```

---

## What Files to Use

### Python Virtual Environment Files
```
venv/
├── Scripts/
│   ├── python.exe           ← Python interpreter
│   ├── pip.exe              ← Package installer
│   ├── activate.bat         ← Manual activation (batch)
│   ├── Activate.ps1         ← Manual activation (PowerShell)
│   └── ... (other tools)
├── Lib/
│   └── site-packages/       ← All installed packages
└── pyvenv.cfg              ← venv configuration
```

### Runner Scripts
```
django_project/
├── run.bat                  ← NEW: Use this! (venv-based)
├── django.bat               ← OLD: Still works (conda-based)
└── ... (other files)
```

---

## When to Use Each Script

### Use `.\run.bat` ✅ (Recommended)
- Daily development
- Testing the project
- Running any Django command
- Team collaboration
- Deploying to servers
- Sharing with others

### Use `.\django.bat` ❌ (Legacy)
- Only if you specifically need conda
- Only if venv is not working
- Only for compatibility with existing scripts
- Can delete if not needed

### Use Neither
- You **never** need to manually activate conda anymore
- You **never** need to type `python manage.py` directly
- Just use `.\run.bat [command]`

---

## Installation/Setup Comparison

### Old Way: Conda Setup
```powershell
# 1. Install Conda (takes 30+ minutes, adds 500MB+)
# 2. Create environment: conda create -n slats python=3.14
# 3. Activate: conda activate slats
# 4. Install packages: pip install django djangorestframework ...
# 5. Create django.bat helper script
# 6. Run: .\django.bat runserver
```

### New Way: venv Setup
```powershell
# 1. Create venv: python -m venv venv
# 2. Install packages: .\venv\Scripts\pip.exe install django djangorestframework ...
# 3. Create run.bat helper script
# 4. Run: .\run.bat runserver
```

**Result:** Same functionality, cleaner setup! ✨

---

## Project Folder Comparison

### Old Setup (Conda)
```
django_project/
├── manage.py
├── django.bat                    ← Uses conda
├── eds_easi/
├── catalog/
├── runs/
└── ... (other Django files)

# Relies on external:
# - Python system installation
# - Conda (installed separately)
# - Conda environment "slats"
```

### New Setup (venv) ✅
```
django_project/
├── manage.py
├── run.bat                       ← Uses venv (NEW!)
├── django.bat                    ← Optional (OLD)
├── venv/                         ← NEW! Self-contained Python
│   ├── Scripts/
│   ├── Lib/
│   └── pyvenv.cfg
├── eds_easi/
├── catalog/
├── runs/
└── ... (other Django files)

# Self-contained:
# - Everything needed is in venv/
# - No external dependencies
# - Easy to move or share
```

---

## Environmental Variables

### Old Way (Conda)
```powershell
# Conda sets these automatically when activated
$env:PYTHONPATH
$env:PATH  (adds conda bin)
# etc.
```

### New Way (venv)
```powershell
# venv is activated by run.bat automatically
# No manual environment setup needed
# Scripts in venv\Scripts\ are called directly
```

---

## Troubleshooting: Old vs New

### Problem: "django command not found"

**With Conda (Old):**
```
Solution: conda activate slats
```

**With venv (New):**
```
Solution: Make sure you're in the django_project folder
         and run: .\run.bat check
```

### Problem: "No module named django"

**With Conda (Old):**
```
Solution: pip install django (in activated environment)
```

**With venv (New):**
```
Solution: .\venv\Scripts\pip.exe install django
```

### Problem: "Permission denied"

**With Conda (Old):**
```
Solution: Run PowerShell as Administrator
         Or modify execution policy
```

**With venv (New):**
```
Solution: run.bat uses .bat file which bypasses PowerShell policy
         Should work in regular PowerShell
```

---

## Team Sharing

### Old Way (Conda)
To share with team:
1. Tell them to install conda (30+ min)
2. Tell them to create `slats` environment
3. Tell them to install packages
4. They can finally run `.\django.bat runserver`

### New Way (venv) ✅
To share with team:
1. Copy `django_project/` folder (including `venv/`)
2. They run `.\run.bat runserver`
3. Done!

---

## Production Deployment

### Old Way (Conda)
```powershell
# On server:
1. Install conda
2. Create environment
3. Install packages
4. Deploy project
5. Run .\django.bat runserver
```

### New Way (venv) ✅
```powershell
# On server:
1. Deploy django_project/ (with venv/)
2. Run .\run.bat runserver
# Done!
```

---

## Summary Table

| Aspect | Conda | venv |
|--------|-------|------|
| **Learning Curve** | Complex | Simple |
| **Setup Time** | 30+ minutes | 2 minutes |
| **Dependencies** | Conda + Python | Just Python |
| **Portability** | Hard to move | Easy to move |
| **Production** | Manual setup | Copy and run |
| **Team Sharing** | Difficult | Just copy folder |
| **Size** | 500MB+ | 100-200MB |
| **Speed** | Slower | Faster |
| **Industry Standard** | Less common | Official Python |
| **Documentation** | Conda docs | Python docs |

---

## Migration Checklist

- ✅ Created venv in project
- ✅ Installed Django in venv
- ✅ Created run.bat script
- ✅ Updated documentation
- ✅ Server running successfully
- ✅ All tests passing
- ✅ Ready for team use!

---

## Going Forward

### All Commands You'll Ever Need
```powershell
.\run.bat runserver              # Start development server
.\run.bat migrate                # Apply database changes
.\run.bat createsuperuser        # Create admin user
.\run.bat shell                  # Python interactive shell
.\run.bat check                  # Verify configuration
.\run.bat [any command]          # Any Django command
```

### Never Use These Anymore (Optional)
```powershell
.\django.bat ...                 # Old conda-based (still works if needed)
conda activate slats             # Activating conda manually
python manage.py ...             # Direct Python (use .\run.bat instead)
```

---

## Quick Decision Tree

```
Do you want to...

├─ Start the server?
│  └─ .\run.bat runserver ✅
│
├─ Check configuration?
│  └─ .\run.bat check ✅
│
├─ Run migrations?
│  └─ .\run.bat migrate ✅
│
├─ Run any Django command?
│  └─ .\run.bat [command] ✅
│
└─ Do something else?
   └─ Check the docs! 📚
```

---

## Bottom Line

**Replace this:**
```powershell
.\django.bat [command]
```

**With this:**
```powershell
.\run.bat [command]
```

**That's all you need to know!** 🎉

