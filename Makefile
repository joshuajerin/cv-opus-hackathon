.PHONY: install serve build scrape test clean

# ── Setup ──────────────────────────────────────────────────
install:
	pip install -r requirements.txt
	cd frontend && npm install && npm run build

# ── Backend ────────────────────────────────────────────────
serve:
	PYTHONPATH=. uvicorn src.api.server:app --host 0.0.0.0 --port 8000 --reload

serve-prod:
	PYTHONPATH=. uvicorn src.api.server:app --host 0.0.0.0 --port 8000 --workers 2

# ── Frontend ───────────────────────────────────────────────
dev:
	cd frontend && npm run dev

build:
	cd frontend && npm run build

# ── Database ───────────────────────────────────────────────
scrape:
	PYTHONPATH=. python3 src/scraper/wayback_scraper.py

scrape-resume:
	PYTHONPATH=. python3 src/scraper/wayback_scraper.py --resume

db-stats:
	PYTHONPATH=. python3 -c "\
		from src.db.schema import init_db, get_db_stats; \
		import json; \
		conn = init_db(); \
		print(json.dumps(get_db_stats(conn), indent=2))"

db-rebuild-fts:
	PYTHONPATH=. python3 -c "\
		from src.db.schema import init_db; \
		c = init_db(); \
		c.execute('INSERT INTO parts_fts(parts_fts) VALUES(\"rebuild\")'); \
		c.commit(); \
		print('FTS index rebuilt')"

# ── Pipeline ──────────────────────────────────────────────
run:
	@echo "Usage: make run PROMPT='autonomous drone'"
	PYTHONPATH=. python3 run.py "$(PROMPT)"

run-staged:
	@echo "Usage: make run-staged PROMPT='autonomous drone'"
	PYTHONPATH=. python3 run_staged.py "$(PROMPT)"

# ── Test ──────────────────────────────────────────────────
test:
	PYTHONPATH=. python3 -c "\
		import asyncio; \
		from src.agents.quoter.quoter_agent import QuoterAgent; \
		from src.agents.orchestrator import AgentMessage; \
		msg = AgentMessage(from_agent='test', to_agent='quoter', task='test', \
			payload={'bom': [{'name': 'LED', 'price': 10, 'quantity': 5}]}); \
		r = asyncio.run(QuoterAgent().handle(msg)); \
		print(f'Quote: \$${r[\"total\"]} {r[\"currency\"]}')"

health:
	curl -s http://localhost:8000/health | python3 -m json.tool

# ── Docker ────────────────────────────────────────────────
docker-build:
	docker build -t hardware-builder .

docker-run:
	docker run -p 8000:8000 -e ANTHROPIC_API_KEY hardware-builder

# ── Cleanup ───────────────────────────────────────────────
clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	rm -rf frontend/node_modules frontend/dist output/*.json
