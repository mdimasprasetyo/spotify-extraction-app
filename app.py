import requests
from flask import Flask, request, render_template, send_file, Response, redirect, url_for, flash
from flask import Blueprint
from flask_caching import Cache
from PIL import Image
from io import BytesIO
from tenacity import retry, wait_fixed, stop_after_attempt
import re
import urllib.parse
import logging
from logging.handlers import RotatingFileHandler
from dotenv import load_dotenv
from config import Config
import hashlib

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__)
app.config.from_object(Config)
app.secret_key = app.config['SECRET_KEY']

# Initialize cache
cache = Cache(app, config={'CACHE_TYPE': 'SimpleCache'})

# Setup logging
if not app.debug:  # Only set up file logging if not in debug mode
    file_handler = RotatingFileHandler('app.log', maxBytes=100000, backupCount=3)
    file_handler.setLevel(logging.INFO)
    file_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    file_handler.setFormatter(file_formatter)
    app.logger.addHandler(file_handler)

# Console logging (for development)
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.DEBUG if app.debug else logging.INFO)
console_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
console_handler.setFormatter(console_formatter)
app.logger.addHandler(console_handler)

# Validate environment variables
if not app.config['SPOTIFY_CLIENT_ID'] or not app.config['SPOTIFY_CLIENT_SECRET']:
    app.logger.error("Spotify API credentials are not set in the environment variables.")
    exit(1)

def get_access_token():
    cached_token = cache.get('spotify_access_token')
    if cached_token:
        app.logger.info("Retrieved cached Spotify access token.")
        return cached_token

    url = 'https://accounts.spotify.com/api/token'
    headers = {
        'Content-Type': 'application/x-www-form-urlencoded'
    }
    data = {
        'grant_type': 'client_credentials'
    }
    response = requests.post(url, headers=headers, data=data, auth=(app.config['SPOTIFY_CLIENT_ID'], app.config['SPOTIFY_CLIENT_SECRET']))

    if response.status_code == 401:
        app.logger.error("Spotify API credentials are invalid.")
        raise Exception("Invalid Spotify API credentials")

    response.raise_for_status()
    token = response.json()['access_token']
    cache.set('spotify_access_token', token, timeout=60*60)
    app.logger.info("Fetched new Spotify access token.")
    return token

@retry(wait=wait_fixed(2), stop=stop_after_attempt(3))
def make_spotify_request(endpoint, access_token):
    headers = {
        'Authorization': f'Bearer {access_token}'
    }
    app.logger.debug(f"Making Spotify API request to endpoint: {endpoint}")
    response = requests.get(endpoint, headers=headers)
    response.raise_for_status()
    return response.json()

def sanitize_filename(filename):
    return re.sub(r'[<>:"/\\|?*]', '', filename).strip()

def save_image(image_url):
    app.logger.debug(f"Saving image from URL: {image_url}")
    response = requests.get(image_url)
    response.raise_for_status()
    img = Image.open(BytesIO(response.content))
    img_io = BytesIO()
    img.save(img_io, format='PNG')
    img_io.seek(0)
    return img_io

def spotify_url_to_id(url):
    if 'track' in url:
        return url.split('/')[-1].split('?')[0], 'track'
    elif 'album' in url:
        return url.split('/')[-1].split('?')[0], 'album'
    elif 'playlist' in url:
        return url.split('/')[-1].split('?')[0], 'playlist'
    return None, None

def get_spotify_code(uri):
    url = f'https://scannables.scdn.co/uri/plain/svg/ffffff/black/640/{uri}'
    app.logger.debug(f"Fetching Spotify code for URI: {uri}")
    response = requests.get(url)
    response.raise_for_status()
    return response.content

def get_spotify_info(content_type, content_id):
    access_token = get_access_token()
    if content_type == 'track':
        endpoint = f'https://api.spotify.com/v1/tracks/{content_id}'
    elif content_type == 'album':
        endpoint = f'https://api.spotify.com/v1/albums/{content_id}'
    elif content_type == 'playlist':
        endpoint = f'https://api.spotify.com/v1/playlists/{content_id}'
    else:
        raise ValueError("Unsupported content type")

    try:
        info = make_spotify_request(endpoint, access_token)
    except Exception as e:
        app.logger.error(f"Error fetching Spotify info for {content_type} {content_id}: {e}")
        raise
    
    if content_type == 'track':
        title = info['name']
        artist = ', '.join(artist['name'] for artist in info['artists'])
        album_art_url = info['album']['images'][0]['url']
    elif content_type == 'album':
        title = info['name']
        artist = ', '.join(artist['name'] for artist in info['artists'])
        album_art_url = info['images'][0]['url']
    elif content_type == 'playlist':
        title = info['name']
        artist = info['owner']['display_name']
        album_art_url = info['images'][0]['url']

    app.logger.info(f"Fetched Spotify info: Title: {title}, Artist: {artist}, Type: {content_type}")
    return title, artist, album_art_url

def generate_etag(file_content):
    return hashlib.md5(file_content).hexdigest()

main_bp = Blueprint('main', __name__)

@main_bp.route('/')
def index():
    app.logger.info("Rendering index page")
    return render_template('index.html')

@main_bp.route('/result', methods=['POST'])
def result():
    spotify_url = request.form['spotify_url']
    content_id, content_type = spotify_url_to_id(spotify_url)

    if content_id is None:
        flash("Invalid Spotify URL. Please try again.")
        app.logger.warning(f"Invalid Spotify URL submitted: {spotify_url}")
        return redirect(url_for('main.index'))

    try:
        title, artist, album_art_url = get_spotify_info(content_type, content_id)
    except Exception as e:
        app.logger.error(f"Error fetching Spotify data for URL {spotify_url}: {e}")
        flash("Error fetching Spotify data. Please try again later.")
        return redirect(url_for('main.index'))

    sanitized_title = sanitize_filename(title)
    sanitized_artist = sanitize_filename(artist)
    album_art_filename = f'{sanitized_title}_{sanitized_artist}_album_art.png'
    spotify_code_filename = f'{sanitized_title}_{sanitized_artist}_spotify_code.svg'

    album_art_img_io = save_image(album_art_url)
    spotify_code_svg = get_spotify_code(f'spotify:{content_type}:{content_id}')
    spotify_code_io = BytesIO(spotify_code_svg)

    link_type = content_type.capitalize()  # Capitalize first letter for display
    
    app.logger.info(f"Rendered result page for Spotify URL {spotify_url}")
    return render_template('result.html',
                          title=title,
                          artist=artist,
                          link_type=link_type,
                          album_art_url=urllib.parse.quote(album_art_filename),
                          spotify_code_url=urllib.parse.quote(spotify_code_filename),
                          spotify_url=spotify_url)

@main_bp.route('/download/<file_type>')
def download(file_type):
    spotify_url = request.args.get('spotify_url')
    content_id, content_type = spotify_url_to_id(spotify_url)

    try:
        title, artist, album_art_url = get_spotify_info(content_type, content_id)
    except ValueError as e:
        app.logger.error(f"Error: {e}")
        return str(e), 400
    except requests.RequestException as e:
        app.logger.error(f"Error fetching Spotify data for URL {spotify_url}: {e}")
        return "Error fetching Spotify data", 500

    sanitized_title = sanitize_filename(title)
    sanitized_artist = sanitize_filename(artist)

    if file_type == 'album_art':
        file_name = f'{sanitized_title}_{sanitized_artist}_album_art.png'
        file_content = save_image(album_art_url).getvalue()
        mimetype = 'image/png'
    elif file_type == 'spotify_code':
        file_name = f'{sanitized_title}_{sanitized_artist}_spotify_code.svg'
        file_content = get_spotify_code(f'spotify:{content_type}:{content_id}')
        mimetype = 'image/svg+xml'
    else:
        app.logger.warning(f"Unsupported file type requested: {file_type}")
        return "File type not supported", 400

    file_name_encoded = urllib.parse.quote(file_name)

    response = Response(file_content, mimetype=mimetype,
                        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{file_name_encoded}"})
    response.headers['Cache-Control'] = 'public, max-age=86400'  # Cache for 1 day
    response.headers['ETag'] = generate_etag(file_content)
    
    if request.headers.get('If-None-Match') == response.headers['ETag']:
        app.logger.info(f"File {file_name} not modified, returning 304.")
        response.status_code = 304  # Not modified
    
    app.logger.info(f"Serving download for {file_name}")
    return response

@main_bp.route('/back')
def back():
    app.logger.info("Redirecting to index page")
    return redirect(url_for('main.index'))

app.register_blueprint(main_bp)

@app.after_request
def add_security_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    return response

if __name__ == '__main__':
    app.run(port=8888, threaded=True)