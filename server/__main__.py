"""Development server; use Gunicorn for production."""
import os
from .runtime import application

app = application()
if os.environ.get('APP_ENV', os.environ.get('NODE_ENV')) == 'production':
    raise SystemExit('Für den Produktionsbetrieb Gunicorn verwenden: gunicorn -c gunicorn.conf.py server.wsgi:app')
app.run(host=os.environ.get('HOST', '127.0.0.1'), port=int(os.environ.get('PORT', '3000')), debug=False)
