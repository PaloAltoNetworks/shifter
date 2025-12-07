.PHONY: up down build logs shell migrate makemigrations createsuperuser test clean init

# First-time setup
init: up
	@echo "Waiting for services to be ready..."
	@sleep 5
	@$(MAKE) createsuperuser

# Start services
up:
	docker compose up -d

# Stop services
down:
	docker compose down

# Rebuild and start
build:
	docker compose up -d --build

# View logs (follow mode)
logs:
	docker compose logs -f web

# Django shell
shell:
	docker compose exec web python manage.py shell

# Run migrations
migrate:
	docker compose exec web python manage.py migrate

# Create migrations
makemigrations:
	docker compose exec web python manage.py makemigrations

# Create superuser
createsuperuser:
	docker compose exec web python manage.py createsuperuser

# Run tests
test:
	docker compose exec web pytest

# Clean up volumes
clean:
	docker compose down -v

# Show running containers
ps:
	docker compose ps

# Restart web service
restart:
	docker compose restart web

# Database shell
dbshell:
	docker compose exec db psql -U postgres -d shifter
