# Set up with an AI assistant

Give the prompt below to your AI coding assistant (Claude Code, Cursor, Copilot Chat, or similar) from inside a checkout of this repository. It installs the project into a local virtual environment, runs the self-test and starts the app. It never needs an API key for the core features.

## Copy-paste prompt

```text
You are installing the project in the current directory (Lead Radar, a local Python web app).

Rules:
- Read README.md and AI_SETUP.md first.
- Do not invent credentials. SMTP settings and LLM_API_KEY are optional: ask me, and leave them
  empty if I do not have them. Never print secrets or commit .env.
- Install only inside this folder (a .venv). Do not use sudo and do not change system Python.
- Ask me before installing a browser (step 4) and before contacting anyone: the app sends nothing
  unless I click Send in the UI.
- Show me the output of every command and stop if a step fails.

Do this:
1. Run the prerequisite checks (step 1 in AI_SETUP.md).
2. Run ./scripts/setup.sh (add --with-browser only if I agree) and confirm it ends with "Setup complete".
3. Ask me whether I want SMTP sending or a custom Chrome path, and edit .env accordingly.
4. Start the app with ./scripts/run.sh, check http://127.0.0.1:8790 answers with HTTP 200, then stop it.
5. Report PASS or FAIL for each verification check (step 6) and what I still have to do by hand
   (logging in to Gmail, Instagram and WhatsApp Web inside the app's own Chrome window).
```

## Checklist

### 1. Prerequisites

| Need | Check | Expected |
|---|---|---|
| Python 3.9 or newer | `python3 --version` | `Python 3.9` or higher |
| venv module | `python3 -m venv --help` | prints usage (on Debian/Ubuntu install `python3-venv`) |
| git | `git --version` | any recent version |
| Google Chrome (browser tasks only) | macOS: `ls "/Applications/Google Chrome.app"`; Linux: `google-chrome --version` | found, or install with `--with-browser` |

Platform notes:

- **macOS**: fully supported, including browser tasks.
- **Linux**: self-test and web UI work. Browser tasks need Google Chrome and `CHROME_BIN` pointing at the binary (for example `/usr/bin/google-chrome`).
- **Windows**: run the steps in WSL or Git Bash. Only the self-test and the web UI are supported; browser automation is untested.

### 2. Install

```sh
./scripts/setup.sh                 # venv, requirements, .env, self-test
./scripts/setup.sh --with-browser  # same, plus Google Chrome for Playwright
```

The script is idempotent. It creates `.venv/`, installs `requirements.txt` (Playwright, plus `tzdata` on Windows), copies `.env.example` to `.env` if missing, runs `radar.py --selftest` and `py_compile`.

`--with-browser` runs `python -m playwright install chrome`. The code launches Playwright with `channel="chrome"`, so it needs Google Chrome rather than the bundled Chromium. On Linux this step may need root privileges; if so, install Google Chrome with your package manager instead.

### 3. Values to ask the user for (all optional)

| Variable | When needed | Notes |
|---|---|---|
| `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_HOST`, `SMTP_PORT` | Only to send e-mail over SMTP | Defaults: `smtp.gmail.com`, `465`. Use an app password. Without a password the app drives Gmail web in its own Chrome |
| `CHROME_BIN` | Linux or a non-default Chrome location | Used for headless demo screenshots. Leave empty for the macOS default |
| `LEAD_RADAR_DATA`, `LEAD_RADAR_PORT` | Separate data directory or another port | Defaults: `./data`, `8790` |
| `LLM_API_KEY` | Only for `i18n/translate.py` | Not needed to run the app |

Edit `.env`. `scripts/run.sh` loads it automatically. To load it in your own shell: `set -a; . ./.env; set +a`.

### 4. Start

```sh
./scripts/run.sh
```

Expected output: `Lead Radar: http://127.0.0.1:8790`. Open that URL.

### 5. First-run configuration in the UI

1. Settings tab: sender name, contact line, price, postal address (required for US/Canada messages).
2. Accounts tab (needs Chrome): log in once to Gmail, Instagram and WhatsApp Web in the dedicated Chrome window. Logins stay in `data/chrome-profile/`.
3. Search tab: pick a country, city and category, then Search. Nothing is sent until you click Send and confirm.

### 6. Verify

| Check | Command | Expected |
|---|---|---|
| Self-test | `.venv/bin/python radar.py --selftest` | last line `selftest OK` |
| Syntax | `.venv/bin/python -m py_compile radar.py browser.py pdfmaker.py scripts/seed_demo_data.py` | no output, exit code 0 |
| Server up | start `./scripts/run.sh`, then `curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8790/` | `200` |
| Demo data (optional) | `LEAD_RADAR_DATA=/tmp/lead-radar-demo .venv/bin/python scripts/seed_demo_data.py` | creates about 25 fictional leads in that directory; needs Chrome for screenshots |

### Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `Python 3.9 or newer is required` | Old interpreter | Install a newer Python, then `PYTHON=python3.12 ./scripts/setup.sh` |
| `No module named venv` | Missing OS package | Debian/Ubuntu: `sudo apt install python3-venv` |
| `Address already in use` | Port 8790 is taken | Set `LEAD_RADAR_PORT=8791` in `.env` |
| `ModuleNotFoundError: playwright` | Setup not run, or system Python used | Run `./scripts/setup.sh`; start with `./scripts/run.sh` (uses `.venv`) |
| `Executable doesn't exist` / Chrome not found | Google Chrome not installed | Install Chrome, or run `./scripts/setup.sh --with-browser`; set `CHROME_BIN` on Linux |
| Demo screenshots are blank | `CHROME_BIN` wrong | Point it at a working Chrome binary |
| WhatsApp or Instagram asks to log in again | Profile was deleted | Log in again from the Accounts tab |
| HTTP 429 from Overpass | Public API rate limit | Wait a few minutes and search again; use smaller radius or count |
| Sending is blocked for a country | Built-in compliance guard (for example e-mail in DE/AT) | Use another channel or review local law; see Safety notes in README |

### Uninstall and cleanup

```sh
rm -rf .venv data .env     # virtual environment, all local data (including the Chrome profile) and your settings
```

Delete the checkout folder to remove everything else. If you ran `--with-browser` and no longer need Google Chrome, remove it with your OS tools. Log out of any accounts you used in the dedicated Chrome window before deleting `data/`.
