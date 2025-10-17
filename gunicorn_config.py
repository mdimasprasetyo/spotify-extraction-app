import os
from pathlib import Path
from dotenv import load_dotenv

# Change to the project directory (folder containing this config file)
chdir = os.path.dirname(os.path.abspath(__file__))

# Load .env before app starts
env_path = Path(chdir) / ".env"
if env_path.exists():
    load_dotenv(dotenv_path=env_path)
else:
    print(f"⚠️  .env file not found at {env_path}")

# Gunicorn settings
bind = '0.0.0.0:8000'
workers = 4       # Number of worker processes
threads = 2       # Number of threads per worker
loglevel = 'info'
accesslog = '-'   # Log to stdout
errorlog = '-'    # Log to stderr