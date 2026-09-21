import os

bind = f"{os.environ.get('HOST', '0.0.0.0')}:{os.environ.get('PORT', '3000')}"
# One process keeps the two scrypt derivations within the service memory budget.
workers = 1
worker_class = 'gthread'
threads = 4
timeout = 30
graceful_timeout = 30
keepalive = 5
accesslog = None
errorlog = '-'
capture_output = True
# Session security uses the configured public origin, not forwarded headers.
forwarded_allow_ips = ''
# Administration uses Render; an additional local control socket is unnecessary.
control_socket_disable = True
