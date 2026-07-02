#!/bin/bash
set -e

echo "=== Creating database tables ==="
python -c "
import os
from app.models.base import Base
from sqlalchemy import create_engine
engine = create_engine(os.environ['DATABASE_URL_SYNC'])
Base.metadata.create_all(engine)
print('Tables created')
"

echo "=== Running database migrations ==="
alembic upgrade head

echo "=== FastAgent Bootstrap ==="
python -m app.bootstrap

echo "=== Starting API Server ==="
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
