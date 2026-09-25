# honcho runs the three dev processes. `make dev` starts docker infra first.
api: uvicorn api.app.main:app --reload --port 8000
worker: celery -A worker.celery_app.celery worker --loglevel=info
beat: celery -A worker.celery_app.celery beat --loglevel=info
web: npm --prefix web run dev
