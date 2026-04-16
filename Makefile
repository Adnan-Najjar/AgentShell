.PHONY: test shell clean

default: shell

test:
	docker compose up -d --build
	docker compose exec app uv run src/test.py

shell:
	docker compose up -d --build
	docker compose exec app uv run src/main.py

clean:
	docker compose down
	rm -rf output/* logs/*
