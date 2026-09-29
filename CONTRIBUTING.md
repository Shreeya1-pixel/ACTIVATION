# Contributing to AutoStack IN

Thank you for your interest in contributing! Here's everything you need to get started.

## Prerequisites

- Python 3.11+
- Node.js 18+
- Git

## Local Setup

```bash
# 1. Fork and clone
git clone https://github.com/allurimohansrisaivarma-coder/autostack-in.git
cd autostack-in

# 2. Python environment
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt   # Windows
# source .venv/bin/activate && pip install -r requirements.txt  # Linux/macOS

# 3. Frontend dependencies
cd frontend && npm install && cd ..

# 4. Environment
cp .env.example .env
# Edit .env if needed (mock AI works with no changes)
```

## Running the Stack

```bash
# Terminal 1 — Backend worker
.venv\Scripts\python scripts\run_worker.py

# Terminal 2 — Frontend dev server
cd frontend && npm run dev
```

Open http://localhost:5173

## Running Tests

```bash
# Unit/integration tests (safe — isolated DBs)
.venv\Scripts\python -m pytest tests/ -q

# Live-stack probes (worker must be running)
.venv\Scripts\python scripts/qa_probe.py
.venv\Scripts\python scripts/scenario_battery.py
```

## Code Style

- **Python**: Follow PEP 8. Keep functions focused.
- **JavaScript/JSX**: Use functional components, no class components.
- **CSS**: Use the existing design tokens in `frontend/src/styles.css` — avoid hardcoded colors.

## Pull Request Guidelines

1. Branch from `main`
2. Keep PRs focused — one feature/fix per PR
3. Run the full test suite before opening a PR
4. Update the README if you're adding a new feature

## Project Structure

See the **Repository Layout** section in [README.md](README.md) for a full map.

## Questions?

Open an issue or reach out to the team.
