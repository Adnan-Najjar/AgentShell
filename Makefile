.PHONY: test shell clean analyze serve

default: serve

serve:
	docker compose up --build

analyze:
	docker compose up -d --build
	docker compose exec app uv run src/test.py --analyze all

test:
	docker compose up -d --build
	docker compose exec app uv run src/test.py --llm all

shell:
	docker compose up -d --build
	docker compose exec app uv run src/main.py

clean:
	docker compose down --remove-orphans
	rm -rf logs/*
