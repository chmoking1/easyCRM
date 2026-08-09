"""WSGI configuration used by a production Python web server."""

import os
from django.core.wsgi import get_wsgi_application

# Point Django at this project's settings before building the WSGI application.
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

# Servers such as Gunicorn import this object to serve HTTP requests.
application = get_wsgi_application()
