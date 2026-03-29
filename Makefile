SHELL := /bin/bash
PROJECT := ai-incident-commander

.PHONY: up down restart ps logs frontend-logs health metrics summary pay normal latency timeout dbexhaust error load slack-test alert-webhook runbook ui clean

up:
	docker compose up --build -d

down:
	docker compose down

restart:
	docker compose down && docker compose up --build -d

ps:
	docker compose ps

logs:
	docker compose logs -f payment-api

frontend-logs:
	docker compose logs -f frontend

health:
	curl -sS http://localhost:8000/health | jq .

metrics:
	curl -sS http://localhost:8000/metrics | head -n 40

summary:
	curl -sS http://localhost:8000/incident/summary | jq .

pay:
	curl -sS -X POST http://localhost:8000/pay \
	  -H 'Content-Type: application/json' \
	  -d '{"amount": 49.99, "currency": "USD", "merchant_id": "merchant_cardhub"}' | jq .

normal:
	curl -sS -X POST http://localhost:8000/simulate/normal | jq .

latency:
	curl -sS -X POST http://localhost:8000/simulate/latency_spike | jq .

timeout:
	curl -sS -X POST http://localhost:8000/simulate/timeout_storm | jq .

dbexhaust:
	curl -sS -X POST http://localhost:8000/simulate/db_pool_exhausted | jq .

error:
	curl -sS -X POST http://localhost:8000/simulate/error_spike | jq .

load:
	python3 scripts/traffic_generator.py --duration 60 --concurrency 25 --rps 40

slack-test:
	curl -sS -X POST http://localhost:8000/notifications/slack/test \
	  -H 'Content-Type: application/json' \
	  -d '{"message":"Test notification from AI Incident Commander"}' | jq .

alert-webhook:
	curl -sS -X POST http://localhost:8000/alerts/webhook \
	  -H 'Content-Type: application/json' \
	  -d '{"source":"manual-demo","severity":"critical","alert_name":"payment_api_high_error_rate","description":"Manual alert test"}' | jq .

runbook:
	tail -n 80 logs/runbooks/incident_runbook.md

ui:
	open http://localhost:5173

clean:
	docker compose down -v
	rm -rf logs/payment-api.log frontend/node_modules frontend/dist
