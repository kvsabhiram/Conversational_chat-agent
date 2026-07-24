#!/bin/sh
# Wait for Postgres, run Alembic migrations, then start the app.
# Best-effort by design (matches db_session.py's policy): if Postgres never
# comes up, we log and continue rather than crash-looping the container —
# the app already tolerates a missing DB by disabling conversation logging.
set -e

if [ -n "$DATABASE_URL" ]; then
  echo "Waiting for database..."
  python <<'PYEOF'
import asyncio
import os
import sys

from sqlalchemy.ext.asyncio import create_async_engine


async def wait_for_db():
    url = os.environ.get("DATABASE_URL")
    engine = create_async_engine(url)
    for attempt in range(30):
        try:
            async with engine.connect():
                pass
            await engine.dispose()
            print("Database is up.")
            return
        except Exception:
            await asyncio.sleep(2)
    print("Database not reachable after retries; continuing anyway.", file=sys.stderr)


asyncio.run(wait_for_db())
PYEOF

  echo "Running Alembic migrations..."
  alembic upgrade head || echo "Alembic upgrade failed; continuing (best-effort DB policy)."
fi

exec "$@"
