# Django with Python venv - No Conda Dependency

## ✅ Why Use venv Instead of Conda?

The `.bat` file was needed because Django had to run within the conda environment. **Now you don't need conda anymore!**

### Advantages of venv
- ✅ **Standalone** - No conda dependency required
- ✅ **Cleaner** - Uses built-in Python venv module
- ✅ **Portable** - Easy to move or share
- ✅ **Faster** - Quicker activation than conda
- ✅ **Standard** - Official Python way to create virtual environments

---

## 🚀 Using the New venv Setup

### Start the Server
```powershell
cd c:\Users\DCCEEW\code\work-easi-eds\django_project
.\run.bat runserver
```

That's it! The `run.bat` file automatically:
1. Activates the venv
2. Runs your command with venv's Python
3. Returns you to your shell when done

### Any Django Command
```powershell
# Check configuration
.\run.bat check

# Create superuser
.\run.bat createsuperuser

# Database migrations
.\run.bat migrate

# Django shell
.\run.bat shell

# Open admin
.\run.bat runserver
```

---

## 📁 What Was Created

```
django_project/
├── venv/                          # ← NEW: Python virtual environment
│   ├── Scripts/
│   │   ├── python.exe             # venv's Python interpreter
│   │   ├── pip.exe                # venv's pip
│   │   └── ... (other tools)
│   ├── Lib/
│   │   └── site-packages/         # Django, DRF, etc installed here
│   └── pyvenv.cfg                 # venv configuration
│
├── run.bat                        # ← NEW: Simple runner script
├── django.bat                     # OLD: Conda-based runner
│
└── ... (rest of Django project)
```

**Key Difference:**
- `django.bat` → Uses conda's Python (now optional)
- `run.bat` → Uses venv's Python (recommended)

---

## 📦 Installed Packages in venv

```
django==6.0
djangorestframework==3.16.1
django-cors-headers==4.9.0
pillow==12.0.0
asgiref>=3.9.1
sqlparse>=0.5.0
tzdata
```

These are installed **only** in the venv, not system-wide.

---

## 🔄 Complete Workflow

### First Time (Already Done)
```powershell
# 1. Create venv
python -m venv venv

# 2. Install packages
.\venv\Scripts\pip.exe install django djangorestframework django-cors-headers pillow

# 3. Create run.bat helper
# (Already created for you)
```

### Every Time You Use It
```powershell
cd c:\Users\DCCEEW\code\work-easi-eds\django_project

# Start server
.\run.bat runserver

# Login to http://127.0.0.1:8000/admin/
```

---

## ✨ Comparison

| Feature | With Conda | With venv |
|---------|-----------|----------|
| **Dependency** | Requires conda installed | Only Python 3.x needed |
| **Command** | `.\django.bat runserver` | `.\run.bat runserver` |
| **Size** | Conda env size varies | ~100-200 MB |
| **Speed** | Slower startup | Faster startup |
| **Portability** | Harder to move | Easier to move |
| **Standard** | Conda-specific | Python standard |
| **Admin Needed** | Maybe | No |

---

## 🎯 You Can Now:

✅ Run Django **without conda**  
✅ Share venv with team members  
✅ Deploy easily (venv goes with project)  
✅ Use standard Python tools  
✅ No conda environment switching needed  

---

## 📝 Quick Reference

```powershell
# From django_project directory:

# Start server
.\run.bat runserver

# Run specific command
.\run.bat [command]

# Examples:
.\run.bat check              # Check configuration
.\run.bat migrate            # Run migrations
.\run.bat shell              # Open Python shell
.\run.bat createsuperuser    # Create new user
.\run.bat collectstatic      # Collect static files
```

---

## 🔐 Can You Delete These Files?

### Safe to Delete (Optional)
- ❌ `django.bat` - Not needed anymore, but safe to keep
- ❌ `DJANGO_SETUP_COMPLETE.md` - Reference only, can be removed

### DO NOT Delete
- ✅ `venv/` - Your entire Python environment lives here
- ✅ `run.bat` - Your simple runner script
- ✅ All other Django files

---

## 🚀 Comparison: Before vs After

### Before (Conda-based)
```powershell
.\django.bat runserver
# This internally called:
# conda run -n slats python manage.py runserver
```

### Now (venv-based)
```powershell
.\run.bat runserver
# This internally calls:
# venv\Scripts\python.exe manage.py runserver
```

**Result:** Cleaner, faster, no conda dependency! ✨

---

## 📋 Troubleshooting

### "venv not found"
→ You're not in the right directory. Must be in `django_project/` folder

### "run.bat not found"
→ Run this command: `ls *.bat` to see what files exist
→ If missing, the file creation failed - let me know

### "Python: No module named django"
→ venv wasn't activated properly
→ Try: `.\venv\Scripts\python.exe -m django --version`
→ If that fails, reinstall: `.\venv\Scripts\pip.exe install django`

### "Can't find python.exe"
→ venv wasn't created properly
→ Recreate: `python -m venv venv` (from django_project folder)

---

## 📚 Learn More

**Why venv?**
- https://docs.python.org/3/tutorial/venv.html
- https://docs.python.org/3/library/venv.html

**Django Development Server:**
- https://docs.djangoproject.com/en/6.0/ref/django-admin/#runserver

---

## ✅ Summary

You now have:
1. ✅ A standalone Python venv (no conda needed)
2. ✅ All Django packages installed in venv
3. ✅ Simple `run.bat` script to run any Django command
4. ✅ Same functionality, cleaner setup!

**Just use: `.\run.bat runserver`**

Go to http://127.0.0.1:8000/admin/ and enjoy! 🎉

