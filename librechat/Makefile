.PHONY: init up down logs clean ps health

# First-time setup - creates .env from template with generated secrets
init:
	@if [ ! -f .env ]; then \
		cp env.example .env; \
		sed -i 's/generate_a_random_64_char_hex_string_here/'$$(openssl rand -hex 32)'/' .env; \
		sed -i 's/generate_another_random_64_char_hex_string_here/'$$(openssl rand -hex 32)'/' .env; \
		sed -i 's/generate_a_third_random_64_char_hex_string_here/'$$(openssl rand -hex 32)'/' .env; \
		sed -i 's/generate_a_random_32_char_hex_string_here/'$$(openssl rand -hex 16)'/' .env; \
		echo ".env created with generated secrets"; \
	else \
		echo ".env already exists"; \
	fi
	$(MAKE) up

# Start services
up:
	@mkdir -p images logs data/mongodb
	docker compose up -d

# Stop services
down:
	docker compose down

# View logs (follow mode)
logs:
	docker compose logs -f

# Clean up volumes
clean:
	docker compose down -v

# Show running containers
ps:
	docker compose ps

# Health check
health:
	@curl -sf http://localhost:3080/api/health && echo "Healthy" || echo "Not healthy"

