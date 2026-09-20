# Gunicorn auto-loads this file from the working directory, so these settings
# apply even on hosts that just run `gunicorn app:app` without extra flags.
#
# timeout: Ollama Cloud generations (especially file-heavy STL/document
# requests, a web-search pass first, or High/Max reasoning effort on the
# largest model) can take well over gunicorn's 30s default, which otherwise
# kills the worker mid-request and makes the platform's proxy return an HTML
# error page instead of Forge's own JSON error response. Kept above app.py's
# own request timeout (up to 280s at High/Max power) so gunicorn never wins
# that race.
#
# workers MUST stay at 1. Login sessions (SESSION_TOKENS) live in an
# in-memory Python dict by design — that's what makes a restart wipe every
# session, with no session ever touching disk. But each gunicorn *worker* is
# a separate OS process with its own private memory: with more than one
# worker, a token issued by whichever process handled /api/login is simply
# invisible to whichever process happens to handle the next request, which
# looks exactly like getting logged out at random (in practice, close to
# every single message, since requests round-robin across workers). Do not
# "fix" this by raising `workers` — concurrency instead comes from
# `worker_class = "gthread"` + `threads`, which run as threads inside this
# one process and therefore correctly share the same SESSION_TOKENS dict.
workers = 1
worker_class = "gthread"
threads = 8
timeout = 340
