.PHONY: help install dev-api dev-web test build up down logs eval clean

help:
	@echo "MEPIQ"
	@echo "  make install   install backend and frontend dependencies"
	@echo "  make dev-api   run the API on :8000 with reload"
	@echo "  make dev-web   run the web app on :5173"
	@echo "  make test      backend test suite + frontend production build"
	@echo "  make up        docker compose up --build"
	@echo "  make down      docker compose down"
	@echo "  make build     build the single-container image"
	@echo "  make eval      evaluate against the CTD dataset"

install:
	cd backend && pip install -r requirements.txt && pip install pytest httpx
	cd frontend && npm install --no-audit --no-fund

dev-api:
	cd backend && uvicorn app.main:app --reload --port 8000

dev-web:
	cd frontend && npm run dev

test:
	cd backend && pytest -q
	cd frontend && npm run build

up:
	docker compose up --build

down:
	docker compose down

logs:
	docker compose logs -f --tail=100

build:
	docker build -t mepiq .

eval:
	cd backend && python evaluate_dataset.py --dataset "../CTD Dataset/CTD Dataset" --out ../evaluation

clean:
	rm -rf backend/data backend/.pytest_cache frontend/dist frontend/test/smoke-bundle.mjs
	find . -name '__pycache__' -type d -prune -exec rm -rf {} +
