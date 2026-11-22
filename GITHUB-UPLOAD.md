# GitHub upload guide

This archive is the MarketMind AI v1.0.0 source bundle. Extract it, open the `marketmind-ai` folder, and upload its contents to your private GitHub repository.

## Recommended: Git from Kali Linux

From the extracted project root:

```bash
git init -b main
git add -A
git status --short
git diff --cached --check
# Review the staged file list before committing.
git commit -m "Initial MarketMind AI v1.0.0 release"
git remote add origin https://github.com/YOUR-GITHUB-USERNAME/marketmind-ai.git
git push -u origin main
```

Replace `YOUR-GITHUB-USERNAME` with your GitHub account name. Authenticate using GitHub's browser/device flow or a credential manager; never put a personal access token in a command, source file, or chat.

## Security notes

- `.gitignore` excludes `.env*` files except the checked-in example templates, local databases, virtual environments, `node_modules`, build output, logs, and runtime data.
- Keep real API keys and passwords in local environment files or a secrets manager.
- Review `git status --short` before committing. Do not upload databases or credentials.
- The project is a research platform, not an automated trading system. See `README.md` and `docs/FINAL-RELEASE.md`.
