import os
from pathlib import Path
from dotenv import load_dotenv

# Change to project directory
chdir = os.path.dirname(os.path.abspath(__file__))

# Load .env if exists
env_path = Path(chdir) / ".env"
if env_path.exists():
    load_dotenv(dotenv_path=env_path)
else:
    print(f"⚠️  .env file not found at {env_path}")

# Detect environment
flask_env = os.getenv("FLASK_ENV", "production").lower()
port = os.getenv("PORT", "8080")

# Bind to localhost in dev, 0.0.0.0 in production
if flask_env == "development":
    bind = f"127.0.0.1:{port}"  # local testing
else:
    bind = f"0.0.0.0:{port}"    # production / App Engine

workers = 4
threads = 2
loglevel = 'info'
accesslog = '-'
errorlog = '-'

# Print info for local development
if flask_env == "development":
    print(f"🚀 Gunicorn running locally at http://127.0.0.1:{port}")
else:
    print(f"🚀 Gunicorn running in production mode — bound to {bind}")
