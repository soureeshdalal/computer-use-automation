# Publish to GitHub

This project was developed in a Cursor cloud workspace. The default `origin` remote points at Cursor's temporary git host, **not** your GitHub account. That is why you do not see `computer-use-automation` on github.com yet.

## Steps

1. Create a new **public** repository on GitHub:
   - Name: `computer-use-automation`
   - Do not initialize with a README (this repo already has one)

2. From your machine (or this workspace), add GitHub as a remote and push:

```bash
git remote add github https://github.com/soureeshdalal/computer-use-automation.git
git push -u github main
```

If the remote already exists:

```bash
git push -u github main
```

3. Confirm the repo is public and contains:
   - `README.md`, `REPORT.md`
   - `capabilities/lookup_member_balance.json`
   - `evidence/submission/`

4. Email the GitHub URL to assignments@interface.ai (see `SUBMISSION_EMAIL.md`).
