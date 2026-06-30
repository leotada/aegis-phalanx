.PHONY: up build down restart logs status test

up:
	podman compose --env-file .env up -d

build:
	podman compose --env-file .env up -d --build

down:
	podman compose down

restart:
	podman compose restart

logs:
	podman compose logs -f agent

status:
	podman compose ps

test:
	.venv/bin/pytest
