import os
import secrets

class Config:
    # SECRET_KEY = os.getenv('SECRET_KEY')
    SECRET_KEY = secrets.token_hex(16)
    SPOTIFY_CLIENT_ID = os.getenv('SPOTIFY_CLIENT_ID')
    SPOTIFY_CLIENT_SECRET = os.getenv('SPOTIFY_CLIENT_SECRET')