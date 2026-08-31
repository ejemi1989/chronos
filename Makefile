# Chronos Makefile
# Convenience targets for the demo.

.PHONY: help install test test-go test-py broker orchestrator dashboard docker-up docker-down clean

help:
	@echo "Chronos targets:"
	@echo "  make install      - install Python deps into ./.venv"
	@echo "  make test         - run all tests (Python + Go)"
	@echo "  make test-py      - run Python tests only"
	@echo "  make test-go      - run Go tests only"
	@echo "  make broker       - run the Go A2A broker locally (port :8080)"
	@echo "  make orchestrator - run the FastAPI orchestrator (port :8080/api)"
	@echo "  make dashboard    - run the Streamlit dashboard (port :8501)"
	@echo "  make docker-up    - docker compose up --build"
	@echo "  make docker-down  - docker compose down"

install:
	python3 -m venv .venv
	.venv/bin/pip install -r apps/orchestrator/requirements.txt

test: test-py test-go

test-py:
	.venv/bin/python -m pytest apps/orchestrator/tests/ -v

test-go:
	cd services/action-broker-go && go test ./... -v

broker:
	cd services/action-broker-go && CHRONOS_BROKER_ADDR=:8080 go run ./cmd/server

orchestrator:
	.venv/bin/uvicorn apps.orchestrator.api:app --host 0.0.0.0 --port 8080

dashboard:
	.venv/bin/streamlit run apps/dashboard/streamlit_app.py --server.port 8501

docker-up:
	docker compose up --build

docker-down:
	docker compose down

clean:
	rm -rf .pytest_cache apps/orchestrator/__pycache__ apps/orchestrator/*/__pycache__