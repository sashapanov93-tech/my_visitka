import os


bind = f"0.0.0.0:{os.getenv('PORT', '10000')}"

# The in-memory limiter is shared by threads, not by separate processes.
workers = 1
worker_class = "gthread"
threads = 4

timeout = 15
graceful_timeout = 15
keepalive = 2

max_requests = 1000
max_requests_jitter = 100

limit_request_line = 2048
limit_request_fields = 50
limit_request_field_size = 4096

accesslog = "-"
# Do not retain visitor IPs, referrers, user agents, or query strings.
access_log_format = '%(t)s "%(m)s %(U)s %(H)s" %(s)s %(b)s %(L)s'
errorlog = "-"
