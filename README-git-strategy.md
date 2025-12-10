# Git Branching Strategy for EDS Project

## Overview

This project uses a structured branching strategy to ensure clean, organized development with proper testing before production deployment.

## Branch Structure

```
main (production)
  ↑
staging (pre-production testing)
  ↑
dev/{feature} (feature development)
```

### Branch Purposes

| Branch | Purpose | Deployment |
|--------|---------|------------|
| `main` | Production-ready code | Production environment |
| `staging` | Pre-production testing and validation | Staging/test environment |
| `dev/{feature}` | Individual feature development | Local/dev environment |

---

## Workflow

### 1. Starting New Feature Development

When starting work on a new feature:

```powershell
# Ensure you're up to date with staging
git checkout staging
git pull origin staging

# Create a new feature branch
git checkout -b dev/feature-name

# Example feature names:
# dev/database-migration
# dev/dashboard-improvements
# dev/api-integration
# dev/bug-fix-tile-processing
```

**Naming Convention**: `dev/{descriptive-feature-name}`
- Use lowercase and hyphens
- Be descriptive but concise
- Examples: `dev/sqlite-migration`, `dev/add-qc-validation`, `dev/fix-login-bug`

### 2. Working on Your Feature

```powershell
# Make your changes, then stage and commit
git add .
git commit -m "feat: descriptive message about what you changed"

# Push your feature branch to remote
git push -u origin dev/feature-name

# Continue working and pushing as needed
git add .
git commit -m "fix: another descriptive message"
git push
```

**Commit Message Convention**:
- `feat:` - New feature
- `fix:` - Bug fix
- `docs:` - Documentation changes
- `refactor:` - Code refactoring
- `test:` - Adding tests
- `chore:` - Maintenance tasks

### 3. Merging Feature to Staging

When your feature is complete and tested locally:

```powershell
# Ensure your feature branch is up to date
git checkout dev/feature-name
git pull origin dev/feature-name

# Update with latest staging changes
git checkout staging
git pull origin staging

# Merge your feature into staging
git merge dev/feature-name

# If there are conflicts, resolve them, then:
git add .
git commit -m "merge: dev/feature-name into staging"

# Push staging
git push origin staging
```

**Alternative: Use Pull Requests** (Recommended)
1. Push your feature branch: `git push origin dev/feature-name`
2. Create a Pull Request on GitHub: `dev/feature-name` → `staging`
3. Review, approve, and merge via GitHub interface

### 4. Testing in Staging

After merging to staging:
1. Deploy to staging environment
2. Run comprehensive tests
3. Verify functionality
4. Get team approval if needed

### 5. Promoting Staging to Production

Once staging is validated and ready for production:

```powershell
# Ensure staging is fully up to date
git checkout staging
git pull origin staging

# Switch to main and merge staging
git checkout main
git pull origin main
git merge staging

# Tag the release (optional but recommended)
git tag -a v1.0.0 -m "Release version 1.0.0"

# Push to production
git push origin main
git push origin --tags
```

**Alternative: Use Pull Requests** (Recommended)
1. Create a Pull Request on GitHub: `staging` → `main`
2. Review changelog and all merged features
3. Get final approval
4. Merge via GitHub interface
5. Tag the release on GitHub

### 6. Cleaning Up Feature Branches

After successfully merging to staging and verifying:

```powershell
# Delete local branch
git branch -d dev/feature-name

# Delete remote branch
git push origin --delete dev/feature-name
```

**Note**: Only delete branches after they're merged and verified!

---

## Quick Reference Commands

### Starting Work
```powershell
git checkout staging
git pull origin staging
git checkout -b dev/your-feature-name
```

### Regular Commits
```powershell
git add .
git commit -m "feat: your changes"
git push origin dev/your-feature-name
```

### Merging to Staging
```powershell
git checkout staging
git pull origin staging
git merge dev/your-feature-name
git push origin staging
```

### Promoting to Production
```powershell
git checkout main
git pull origin main
git merge staging
git push origin main
```

### Syncing Your Branch with Staging
```powershell
git checkout dev/your-feature-name
git pull origin staging
# Resolve any conflicts
git push origin dev/your-feature-name
```

---

## Handling Conflicts

When you encounter merge conflicts:

1. **Identify conflicts**:
   ```powershell
   git status
   # Shows files with conflicts
   ```

2. **Open conflicted files** and look for conflict markers:
   ```
   <<<<<<< HEAD
   Your changes
   =======
   Changes from other branch
   >>>>>>> dev/feature-name
   ```

3. **Resolve conflicts** by editing the files to keep desired changes

4. **Mark as resolved**:
   ```powershell
   git add conflicted-file.py
   git commit -m "merge: resolved conflicts from dev/feature-name"
   git push
   ```

---

## Best Practices

### ✅ Do's

- **Keep feature branches small and focused** - One feature per branch
- **Commit frequently** with clear messages
- **Pull from staging regularly** to avoid conflicts
- **Test locally** before pushing
- **Delete merged branches** to keep repo clean
- **Use descriptive branch names** - `dev/add-user-auth` not `dev/stuff`
- **Review code** before merging to staging
- **Tag releases** on main branch for version tracking

### ❌ Don'ts

- **Don't commit directly to main** - Always go through staging
- **Don't commit directly to staging** - Use feature branches
- **Don't push broken code** - Test before pushing
- **Don't leave branches unmerged** for long periods
- **Don't force push** to shared branches (`-f` flag)
- **Don't merge without testing** in staging first
- **Don't mix multiple features** in one branch

---

## Emergency Hotfix Procedure

For critical bugs that need immediate fixing in production:

```powershell
# Create hotfix branch from main
git checkout main
git pull origin main
git checkout -b hotfix/critical-bug-name

# Make your fix
git add .
git commit -m "hotfix: description of critical fix"

# Merge to main
git checkout main
git merge hotfix/critical-bug-name
git push origin main

# Also merge to staging to keep it in sync
git checkout staging
git merge hotfix/critical-bug-name
git push origin staging

# Clean up
git branch -d hotfix/critical-bug-name
```

---

## Troubleshooting

### "Updates were rejected" when pushing

```powershell
# Pull remote changes first
git pull origin your-branch-name

# If there are conflicts, resolve them
# Then push again
git push origin your-branch-name
```

### Accidentally committed to wrong branch

```powershell
# If not pushed yet - move commits to new branch
git branch dev/new-feature-name
git reset --hard HEAD~1  # Remove commit from current branch
git checkout dev/new-feature-name
```

### Need to undo last commit

```powershell
# Undo commit but keep changes
git reset --soft HEAD~1

# Undo commit and discard changes (CAREFUL!)
git reset --hard HEAD~1
```

### See what changed

```powershell
# See what's changed in working directory
git status

# See actual changes
git diff

# See commit history
git log --oneline

# See branch structure
git log --graph --oneline --all
```

---

## Visual Workflow Diagram

```
Developer Workflow:
===================

1. Create Feature Branch
   staging → dev/feature-name

2. Develop & Commit
   dev/feature-name (multiple commits)

3. Merge to Staging
   dev/feature-name → staging

4. Test in Staging
   staging (testing & validation)

5. Promote to Production
   staging → main

6. Tag Release
   main (v1.0.0, v1.1.0, etc.)

7. Clean Up
   Delete dev/feature-name
```

---

## Branch Protection Rules (Recommended)

If using GitHub, configure these protection rules:

### `main` branch:
- ✅ Require pull request reviews before merging
- ✅ Require status checks to pass before merging
- ✅ Require branches to be up to date before merging
- ✅ Restrict who can push to main

### `staging` branch:
- ✅ Require pull request reviews before merging
- ✅ Require status checks to pass before merging

### `dev/*` branches:
- ✅ Allow direct commits (for rapid development)

---

## Example Complete Workflow

```powershell
# 1. Start new feature
git checkout staging
git pull origin staging
git checkout -b dev/add-sqlite-migration

# 2. Make changes and commit
git add .
git commit -m "feat: implement PostgreSQL to SQLite migration tool"
git push -u origin dev/add-sqlite-migration

# 3. Continue working
git add .
git commit -m "feat: add verification script for migration"
git push

git add .
git commit -m "docs: add migration documentation"
git push

# 4. Ready to test - merge to staging
git checkout staging
git pull origin staging
git merge dev/add-sqlite-migration
git push origin staging

# 5. Test in staging environment
# ... testing happens ...

# 6. Ready for production - merge to main
git checkout main
git pull origin main
git merge staging
git tag -a v1.2.0 -m "Release: SQLite migration feature"
git push origin main
git push origin --tags

# 7. Clean up feature branch
git branch -d dev/add-sqlite-migration
git push origin --delete dev/add-sqlite-migration
```

---

## Questions & Support

- **Merge conflicts?** See "Handling Conflicts" section above
- **Broken something?** Check "Troubleshooting" section
- **Need a hotfix?** Follow "Emergency Hotfix Procedure"

Remember: **When in doubt, commit locally and ask before pushing!**
