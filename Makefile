.PHONY: test shell clean

default: shell

build:
	docker compose build

analyze:
	docker compose up -d --build
	docker compose exec app uv run src/test.py --analyze all

generate:
	docker compose up -d --build
	docker compose exec app uv run src/test.py --llm all

shell:
	docker compose up -d --build
	docker compose exec app uv run src/main.py

clean:
	docker compose down
	rm -rf logs/*
