.PHONY: help build run test docker-up docker-down docker-logs clean

help:
	@echo "HTTP Metadata Inventory - Make commands"
	@echo ""
	@echo "Development:"
	@echo "  make run        - Run the API locally"
	@echo "  make test      - Run tests"
	@echo "  make test-cov  - Run tests with coverage"
	@echo ""
	@echo "Docker:"
	@echo "  make docker-up     - Start services with docker-compose"
	@echo "  make docker-down - Stop services"
	@echo "  make docker-logs - View logs"
	@echo ""
	@echo "Utilities:"
	@echo "  make clean     - Remove containers and volumes"

build:
	docker-compose build

docker-up:
	docker-compose up -d
	@echo "API running at http://localhost:8000"
	@echo "Swagger docs at http://localhost:8000/docs"

docker-down:
	docker-compose down

docker-logs:
	docker-compose logs -f

clean:
	docker-compose down -v


test:
	python3 -m pytest -v

test-cov:
	python3 -m pytest --cov=app --cov-report=term-missing