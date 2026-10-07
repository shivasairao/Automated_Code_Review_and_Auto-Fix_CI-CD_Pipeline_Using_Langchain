.PHONY: install lint format test run docker-build docker-run review clean

install:
	pip install -r requirements.txt -r requirements-dev.txt
	pip install -e .

lint:
	ruff check .
	ruff format --check .

format:
	ruff check --fix .
	ruff format .

test:
	pytest

run:
	streamlit run app.py

docker-build:
	docker build -t ai-code-review .

docker-run:
	docker run --rm -p 8501:8501 --env-file .env ai-code-review

review:
	ai-review --paths src app.py --report-md review_report.md --report-json review_report.json

clean:
	rm -rf .pytest_cache .ruff_cache .coverage build dist *.egg-info src/*.egg-info review_report.*
