# Repository Context

## Purpose

- Serverless single-user bot that ingests GitHub, optional Google Calendar, and
  technology news, then drafts Twitter/LinkedIn content for manual Telegram
  review.

## Stack

- Python 3.13, AWS Lambda arm64, FastAPI + Mangum, DynamoDB, Bedrock/Strands,
  SSM Parameter Store, and AWS SAM.

## Project Structure

- `src/handler.py`: Lambda entrypoint.
- `src/jobs/`: daily orchestration.
- `src/ingestion/`: external activity/news clients.
- `src/generation/`: prompts and Bedrock draft generation.
- `src/storage/`: DynamoDB models and repository.
- `tests/`: pytest unit and integration-style tests.

## Package Manager And Scripts

- Dependencies are installed with `pip` from `requirements-dev.txt`.
- Runtime dependencies live in `src/requirements.txt`.
- No package manager scripts are defined in `pyproject.toml`.

## Architecture Rules

- Keep the Lambda monolithic and sources independently degradable.
- Store secrets in SSM SecureString; do not auto-publish content.
- Use generic DynamoDB `pk`/`sk` records and existing dataclass models.

## Testing And Verification

- Tests: `.venv/bin/python -m pytest -q`
- Lint: `.venv/bin/ruff check .`
- SAM validation/build: `sam validate --lint`, `sam build`

## Local Development Services

- No Docker service is required for local tests; moto mocks DynamoDB.

## Agent Notes

- Technology-news ingestion is configured through environment variables in
  `src/config.py` and consumed by `src/jobs/daily_job.py`.

## Last Reviewed

2026-09-21 — inspected SAM, Python source layout, configuration, and tests.
