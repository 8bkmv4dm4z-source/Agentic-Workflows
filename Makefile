.PHONY: install run user-run local-run test lint format typecheck audit clean clean-artifacts docker-build docker-up docker-down docker-reset docker-logs

install:
	pip install -e ".[dev]"

run:
	python -m agentic_workflows.orchestration.langgraph.run

local-run:
	@echo "Stopping Docker API container if running..."
	docker.exe compose stop api 2>/dev/null || true
	@echo "Starting Postgres only in Docker..."
	docker.exe compose up -d postgres
	@echo "Waiting for Postgres..."
	@until docker.exe compose exec postgres pg_isready -U agentic -d agentic_workflows > /dev/null 2>&1; do sleep 1; done
	@echo "Starting API server locally..."
	@mkdir -p .tmp
	@lsof -ti:8000 2>/dev/null | xargs -r kill -9 2>/dev/null; sleep 1; true
	.venv/bin/uvicorn agentic_workflows.api.app:app --host 127.0.0.1 --port 8000 > .tmp/api.log 2>&1 &
	@until curl -sf http://localhost:8000/health > /dev/null 2>&1; do sleep 1; done
	@echo "API ready."
	python -m agentic_workflows.cli.user_run

user-run:
	@if ! docker.exe ps > /dev/null 2>&1; then \
		echo "Docker Desktop is not running or not ready — starting it..."; \
		powershell.exe -Command "Start-Process 'C:\\Program Files\\Docker\\Docker\\Docker Desktop.exe'" 2>/dev/null || true; \
		echo "Waiting for Docker Desktop + WSL integration to be ready (this may take ~30s)..."; \
		until docker.exe ps > /dev/null 2>&1; do sleep 2; done; \
		echo "Docker Desktop is ready."; \
	fi
	docker.exe compose up -d --force-recreate
	@echo "Waiting for API to be ready..."
	@until curl -sf http://localhost:8000/health > /dev/null 2>&1; do sleep 1; done
	@echo "API ready."
	python -m agentic_workflows.cli.user_run

test:
	pytest tests/ -q

test-unit:
	pytest tests/unit/ -q

test-integration:
	pytest tests/integration/ -q

lint:
	ruff check src/ tests/

format:
	ruff format src/ tests/

typecheck:
	mypy src/

audit:
	python -m agentic_workflows.orchestration.langgraph.run_audit

clean:
	rm -rf .tmp/ dist/ *.egg-info src/*.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

clean-artifacts:
	rm -f lastRun.txt analysis_results.txt pattern_report.txt users_sorted.txt fib*.txt

docker-build:
	docker.exe build -t agentic-workflows .

docker-up:
	docker.exe compose up -d

docker-down:
	docker.exe compose down

docker-reset:
	docker.exe compose down -v

docker-logs:
	docker.exe compose logs -f
