web: uvicorn app.main:app --host 0.0.0.0 --port $PORT
worker: celery -A app.workers.celery_app.celery worker --loglevel=info --queues=default
beat: celery -A app.workers.celery_app.celery beat --loglevel=info
