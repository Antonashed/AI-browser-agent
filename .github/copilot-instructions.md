# Project Guidelines

## Architecture
- **MyAgent** — Python-based AI agent project (early stage, no source files yet).
- Use Python 3.13.2 (venv at `venv/`; interpreter: `C:\Users\samos\AppData\Local\Programs\Python\Python313\python.exe`).

## Code Style
- Follow PEP 8; use type annotations for all public functions and classes.
- Keep agent logic modular: separate concerns into distinct files (e.g. `agent.py`, `tools.py`, `memory.py`).

## Build and Test
```bash
# Activate virtual environment (Windows)
venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Run agent
python main.py

# Run tests
python -m pytest
```

## Project Conventions
- Store configuration (API keys, model names) in a `.env` file; load with `python-dotenv`. Never commit `.env`.
- Add `.env`, `__pycache__/`, and `*.pyc` to `.gitignore`.
- Pin all direct dependencies in `requirements.txt` with exact versions (`==`).

## Integration Points
- Likely integrates with an LLM API (OpenAI, Anthropic, etc.) — add credentials to `.env` and wrap calls in a dedicated client module.

## Security
- Never hardcode secrets or API keys in source files.
- Validate and sanitize any external input before passing to tools or the LLM.
