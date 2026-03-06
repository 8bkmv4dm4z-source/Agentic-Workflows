.PHONY: install run test lint format typecheck audit clean clean-artifacts docker-build docker-up docker-down docker-reset docker-logs

install:
	pip install -e ".[dev]"

run:
	python -m agentic_workflows.orchestration.langgraph.run

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
	docker build -t agentic-workflows .

docker-up:
	docker compose up -d

docker-down:
	docker compose down

docker-reset:
	docker compose down -v

docker-logs:
	docker compose logs -f
