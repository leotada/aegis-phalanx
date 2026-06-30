.PHONY: up build down restart logs status test render-infra

COMPOSE_FILES = -f compose.yml -f compose.tool.yml

render-infra:
	python3 scripts/render_compose_overlay.py

up: render-infra
	podman compose --env-file .env $(COMPOSE_FILES) up -d

build: render-infra
	podman compose --env-file .env $(COMPOSE_FILES) up -d --build

down:
	podman compose --env-file .env $(COMPOSE_FILES) down

restart: render-infra
	podman compose --env-file .env $(COMPOSE_FILES) restart

logs:
	podman compose --env-file .env $(COMPOSE_FILES) logs -f agent

status:
	podman compose --env-file .env $(COMPOSE_FILES) ps

test:
	python3 -m pytest test_agents.py test_tool_infrastructure.py test_telegram_listener.py test_coverage_boost.py -q -k 'not trio' --cov --cov-report=term-missing
