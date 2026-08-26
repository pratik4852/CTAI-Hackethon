MEPIQ_API ?= http://127.0.0.1:8000

.PHONY: help install dev-api dev-web test smoke build up down logs eval clean

help:
	@echo "MEPIQ"
	@echo "  make install   install backend and frontend dependencies"
	@echo "  make dev-api   run the API on :8000 with reload"
	@echo "  make dev-web   run the web app on :5173"
	@echo "  make test      backend test suite + frontend production build"
	@echo "  make smoke     render every page against a running API and assert real data"
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
	cd frontend && node test/check-layout.mjs
	cd frontend && npm run build

# Renders every page in jsdom against a running API and asserts real data is
# shown — including with no document selected, the state a page reload leaves.
#   MEPIQ_PID=prj_xxx MEPIQ_DID=doc_yyy make smoke
smoke:
	cd frontend && npx esbuild test/smoke-entry.jsx --bundle --format=esm \
	  --platform=browser --loader:.jsx=jsx --jsx=automatic \
	  --define:import.meta.env.VITE_API_BASE='"$(MEPIQ_API)"' \
	  --define:process.env.NODE_ENV='"development"' \
	  --outfile=test/smoke-bundle.mjs --log-level=error
	cd frontend && node test/check-layout.mjs
	cd frontend && node test/run-smoke.mjs

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
