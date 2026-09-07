# Car Dealership AI Sales & Customer Service Agent

Production-oriented Flask foundation for an AI sales and customer service agent used by a car dealership.

## Current goal

Establish a clean, testable Flask application skeleton so later phases can add the database, domain services, LangGraph orchestration, and RAG without rewriting the app bootstrap.

## Current phase

**Phase 1 — Flask Foundation**

This phase includes:

- Flask application factory
- Environment-based configuration
- Centralized extension initialization
- Logging foundation
- Basic JSON error handling
- Health endpoint
- Pytest setup

It does **not** include database, SQLAlchemy, models, AI integrations, LangGraph, RAG, authentication, or an admin dashboard.

## Setup

### Create a virtual environment

Windows (PowerShell):

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

macOS / Linux:

```bash
python -m venv .venv
source .venv/bin/activate
```

### Install requirements

```bash
pip install -r requirements.txt
```

Copy `.env.example` to `.env` and set values as needed:

```powershell
copy .env.example .env
```

## Run the Flask application

```bash
python run.py
```

The development server listens on `http://127.0.0.1:5000`.

Health check:

```text
GET /health
```

Example response:

```json
{"status": "ok"}
```

## Run tests

```bash
pytest
```
