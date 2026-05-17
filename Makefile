.PHONY: test benchmark shell clean analyze serve

default: serve

serve:
	docker compose up --build

analyze:
	uv run src/test.py --analyze all

benchmark:
	docker compose up -d --build
	docker compose exec app uv run src/test.py --llm all

test:
	python -m unittest discover tests -v

shell:
	docker compose up -d --build
	docker compose exec app uv run src/main.py

clean:
	docker compose down --remove-orphans
	sudo rm -rf logs/*
