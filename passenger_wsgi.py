from fastapi import FastAPI
from mangum import Mangum  # Optional for ASGI-to-WSGI wrapper
import sys
import os

# Include your app directory in the path
sys.path.insert(0, os.path.dirname(__file__))

from app.main import app  # your FastAPI app

# If your hosting requires WSGI:
try:
    from mangum import Mangum
    application = Mangum(app)
except ImportError:
    # fallback: use as ASGI app directly
    application = app
