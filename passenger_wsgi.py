import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from a2wsgi import ASGIMiddleware
from app.main import app

application = ASGIMiddleware(app)

