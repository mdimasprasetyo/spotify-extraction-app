import requests
import re
import os
import urllib.parse
import hashlib
import logging
import unicodedata
import time
from io import BytesIO
from PIL import Image
from flask import Flask, request, render_template, send_file, Response, redirect, url_for, flash, Blueprint
from flask_caching import Cache
from tenacity import retry, wait_fixed, stop_after_attempt
from dotenv import load_dotenv
from config import Config
from requests.exceptions import HTTPError

load_dotenv()

app = Flask(__name__)
app.config.from_object(Config)
app.secret_key = app.config['SECRET_KEY']

cache = Cache(app, config={'CACHE_TYPE': 'SimpleCache'})

logging.basicConfig(level=logging.DEBUG if app.debug else logging.INFO, 
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def validate_spotify_credentials():
    if not app.config['SPOTIFY_CLIENT_ID'] or not app.config['SPOTIFY_CLIENT_SECRET']:
        logger.error("Spotify API credentials are missing in environment variables.")
        exit(1)

validate_spotify_credentials()

@retry(wait=wait_fixed(2), stop=stop_after_attempt(5))
def get_access_token():
    """Fetch and cache Spotify access token."""
    cached_token = cache.get('spotify_access_token')
    if cached_token:
        logger.info("Retrieved cached Spotify access token.")
        return cached_token

    url = 'https://accounts.spotify.com/api/token'
    headers = {'Content-Type': 'application/x-www-form-urlencoded'}
    data = {'grant_type': 'client_credentials'}
    
    response = requests.post(url, headers=headers, data=data, 
                             auth=(app.config['SPOTIFY_CLIENT_ID'], app.config['SPOTIFY_CLIENT_SECRET']))
    if response.status_code == 401:
        logger.error("Spotify API credentials are invalid.")
        raise Exception("Invalid Spotify API credentials")
    
    response.raise_for_status()
    token = response.json()['access_token']
    
    cache.set('spotify_access_token', token, timeout=60*60)
    logger.info("Fetched new Spotify access token.")
    return token

@retry(wait=wait_fixed(2), stop=stop_after_attempt(3))
def make_spotify_request(endpoint, access_token):
    """Make a Spotify API request."""
    headers = {'Authorization': f'Bearer {access_token}'}
    logger.debug(f"Making Spotify API request to: {endpoint}")
    
    response = requests.get(endpoint, headers=headers)
    
    if response.status_code == 403:
        logger.warning("Access denied: The playlist might be private.")
        raise Exception("The playlist is private or access is restricted.")

    if response.status_code == 304:
        logger.info("Spotify API returned 304: Not Modified.")
        return None

    response.raise_for_status()
    return response.json()

def sanitize_filename(filename):
    """Sanitize filename to remove invalid characters."""
    return re.sub(r'[<>:"/\\|?*]', '', filename).strip()

def normalize_to_plain_text(text):
    """Convert fancy Unicode text to plain ASCII text."""
    normalized_text = unicodedata.normalize('NFKD', text)
    plain_text = ''.join(char for char in normalized_text if not unicodedata.combining(char))
    return plain_text.encode('ascii', 'ignore').decode('ascii')

def save_image(image_url):
    """Save image from URL with cache-busting."""
    logger.debug(f"Saving image from URL: {image_url}")
    # Append a cache-busting parameter to the URL
    image_url += f"?t={int(time.time())}"
    response = requests.get(image_url)
    response.raise_for_status()
    img = Image.open(BytesIO(response.content))
    
    if img.mode == 'CMYK':
        img = img.convert('RGB')
    
    img_io = BytesIO()
    img.save(img_io, format='PNG')
    img_io.seek(0)
    
    return img_io

def spotify_url_to_id(url):
    """Extract Spotify ID and type from URL."""
    content_map = {'track': 'track', 'album': 'album', 'playlist': 'playlist', 
                   'artist': 'artist', 'show': 'show', 'episode': 'episode'}
    
    for key in content_map:
        if key in url:
            return url.split('/')[-1].split('?')[0], content_map[key]
    return None, None

def get_spotify_code(uri):
    """Get Spotify code for a given URI."""
    url = f'https://scannables.scdn.co/uri/plain/svg/ffffff/black/640/{uri}'
    logger.debug(f"Fetching Spotify code for URI: {uri}")
    
    response = requests.get(url)
    response.raise_for_status()
    return response.content

def get_spotify_info(content_type, content_id):
    """Fetch Spotify content information based on type and ID."""
    access_token = get_access_token()
    endpoints = {
        'track': f'https://api.spotify.com/v1/tracks/{content_id}',
        'album': f'https://api.spotify.com/v1/albums/{content_id}',
        'playlist': f'https://api.spotify.com/v1/playlists/{content_id}',
        'artist': f'https://api.spotify.com/v1/artists/{content_id}',
        'show': f'https://api.spotify.com/v1/shows/{content_id}',
        'episode': f'https://api.spotify.com/v1/episodes/{content_id}'
    }

    if content_type not in endpoints:
        raise ValueError("Unsupported content type")

    try:
        info = make_spotify_request(endpoints[content_type], access_token)
    except HTTPError as e:
        if e.response.status_code == 403:
            flash("This playlist is private or restricted. Please ensure it’s public or accessible.")
            logger.error("Access restricted for private playlist.")
            return None, None, None
        else:
            logger.error(f"HTTPError fetching Spotify info for {content_type} {content_id}: {e}")
            raise
    except Exception as e:
        flash("An error occurred while fetching data. Please try again later.")
        logger.error(f"Unexpected error fetching Spotify info for {content_type} {content_id}: {e}")
        return None, None, None

    if content_type == 'track':
        title = info['name']
        artist = ', '.join(artist['name'] for artist in info['artists'])
        album_art_url = info['album']['images'][0]['url'] if info['album'].get('images') else None
    elif content_type == 'album':
        title = info['name']
        artist = ', '.join(artist['name'] for artist in info['artists'])
        album_art_url = info['images'][0]['url'] if info.get('images') else None
    elif content_type == 'playlist':
        title = normalize_to_plain_text(info['name'])
        artist = normalize_to_plain_text(info['owner']['display_name'])
        album_art_url = info['images'][0]['url'] if info.get('images') else None
    elif content_type == 'artist':
        title = info['name']
        artist = ''
        album_art_url = info['images'][0]['url'] if info.get('images') else None
    elif content_type == 'show':
        title = info['name']
        artist = info['publisher']
        album_art_url = info['images'][0]['url'] if info.get('images') else None
    elif content_type == 'episode':
        title = info['name']
        artist = info['show']['publisher']
        album_art_url = info['images'][0]['url'] if info.get('images') else None

    logger.info(f"Fetched Spotify info: Title: {title}, Artist: {artist}, Type: {content_type}")
    return title, artist, album_art_url

def generate_etag(file_content):
    """Generate an ETag based on the file content."""
    return hashlib.md5(file_content).hexdigest()

main_bp = Blueprint('main', __name__)

@main_bp.route('/')
def index():
    """Render the index page."""
    logger.info("Rendering index page")
    return render_template('index.html')

@main_bp.route('/result', methods=['POST'])
def result():
    """Handle the result submission and display Spotify information."""
    spotify_url = request.form['spotify_url']
    content_id, content_type = spotify_url_to_id(spotify_url)

    if content_id is None:
        flash("Invalid Spotify URL. Please try again.")
        logger.warning(f"Invalid Spotify URL: {spotify_url}")
        return redirect(url_for('main.index'))

    try:
        title, artist, album_art_url = get_spotify_info(content_type, content_id)
        if title is None:
            flash("The playlist is private or access is restricted. Please choose a public playlist.")
            return redirect(url_for('main.index'))
    except Exception as e:
        logger.error(f"Error fetching Spotify data for URL {spotify_url}: {e}")
        flash("Error fetching Spotify data. Please try again later.")
        return redirect(url_for('main.index'))

    sanitized_title = sanitize_filename(title)
    sanitized_artist = sanitize_filename(artist)
    album_art_filename = f'{sanitized_title}_{sanitized_artist}_album_art.png'
    spotify_code_filename = f'{sanitized_title}_{sanitized_artist}_spotify_code.svg'

    album_art_img_io = save_image(album_art_url) if album_art_url else BytesIO()
    spotify_code_svg = get_spotify_code(f'spotify:{content_type}:{content_id}')
    spotify_code_io = BytesIO(spotify_code_svg)

    link_type = content_type.capitalize()
    
    logger.info(f"Rendered result page for Spotify URL {spotify_url}")
    return render_template(
        'result.html',
        title=title,
        artist=artist,
        link_type=link_type,
        album_art_url=album_art_url,
        spotify_code_url=urllib.parse.quote(spotify_code_filename),
        spotify_url=spotify_url
    )

@main_bp.route('/download/<file_type>')
def download(file_type):
    """Handle file downloads for album art and Spotify codes."""
    spotify_url = request.args.get('spotify_url')
    content_id, content_type = spotify_url_to_id(spotify_url)

    try:
        title, artist, album_art_url = get_spotify_info(content_type, content_id)
    except ValueError as e:
        logger.error(f"Error: {e}")
        return str(e), 400
    except requests.RequestException as e:
        logger.error(f"Error fetching Spotify data for URL {spotify_url}: {e}")
        return "Error fetching Spotify data", 500

    sanitized_title = sanitize_filename(title)
    sanitized_artist = sanitize_filename(artist)

    if file_type == 'album_art':
        file_name = f'{sanitized_title}_{sanitized_artist}_album_art.png'
        file_content = save_image(album_art_url).getvalue()
        mimetype = 'image/png'
    elif file_type == 'spotify_code':
        file_name = f'{sanitized_title}_{sanitized_artist}_code.svg'
        file_content = get_spotify_code(f'spotify:{content_type}:{content_id}')
        mimetype = 'image/svg+xml'
    else:
        logger.warning(f"Unsupported file type requested: {file_type}")
        return "File type not supported", 400

    file_name_encoded = urllib.parse.quote(file_name)

    response = Response(file_content, mimetype=mimetype,
                        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{file_name_encoded}"})
    response.headers['Cache-Control'] = 'public, max-age=86400'
    response.headers['ETag'] = generate_etag(file_content)
    
    if request.headers.get('If-None-Match') == response.headers['ETag']:
        logger.info(f"File {file_name} not modified, returning 304.")
        response.status_code = 304
    
    logger.info(f"Serving download for {file_name}")
    return response

@main_bp.route('/back')
def back():
    """Redirect back to the index page."""
    logger.info("Redirecting to index page")
    return redirect(url_for('main.index'))

app.register_blueprint(main_bp)

@app.after_request
def add_security_headers(response):
    """Add security headers to each response."""
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    return response

if __name__ == '__main__':
    port = int(os.getenv('PORT', 8888))
    app.run(host='0.0.0.0', port=port, threaded=True)