.PHONY: up build down logs status test

up:
	podman compose --env-file .env up -d

build:
	podman compose --env-file .env up -d --build

down:
	podman compose down

logs:
	podman compose logs -f agent

status:
	podman compose ps

test:
	.venv/bin/pytest
