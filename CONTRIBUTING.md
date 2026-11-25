# Contributing

Thanks for your interest in Lead Radar. Small, focused pull requests are easiest to review.

1. Open an issue first for anything larger than a bug fix, so we can agree on the approach.
2. Fork the repository and create a branch from `main`.
3. Keep changes minimal and match the existing style (see `.editorconfig`).
4. Run the checks before you push:

   ```sh
   python3 radar.py --selftest
   python3 -m py_compile radar.py browser.py pdfmaker.py scripts/seed_demo_data.py
   for f in scripts/*.sh; do bash -n "$f"; done
   ```

5. Use conventional commit messages (`feat:`, `fix:`, `docs:`, `test:`, `chore:`).
6. Never commit secrets, real customer data or personal data. Use fictional examples.

By contributing you agree that your contribution is licensed under the MIT license of this project.
