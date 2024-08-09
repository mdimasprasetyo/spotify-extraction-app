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
from dotenv import load_dotenv
from config import Config

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__)
app.config.from_object(Config)
app.secret_key = app.config['SECRET_KEY']

# Initialize cache
cache = Cache(app, config={'CACHE_TYPE': 'SimpleCache'})

# Setup logging
logging.basicConfig(level=logging.INFO)

# Validate environment variables
if not app.config['SPOTIFY_CLIENT_ID'] or not app.config['SPOTIFY_CLIENT_SECRET']:
    logging.error("Spotify API credentials are not set in the environment variables.")
    exit(1)

def get_access_token():
    cached_token = cache.get('spotify_access_token')
    if cached_token:
        return cached_token

    url = 'https://accounts.spotify.com/api/token'
    headers = {
        'Content-Type': 'application/x-www-form-urlencoded'
    }
    data = {
        'grant_type': 'client_credentials'
    }
    response = requests.post(url, headers=headers, data=data, auth=(app.config['SPOTIFY_CLIENT_ID'], app.config['SPOTIFY_CLIENT_SECRET']))
    
    # Handle token fetch errors
    if response.status_code == 401:
        logging.error("Spotify API credentials are invalid.")
        raise Exception("Invalid Spotify API credentials")

    response.raise_for_status()
    token = response.json()['access_token']
    cache.set('spotify_access_token', token, timeout=60*60)
    return token

@retry(wait=wait_fixed(2), stop=stop_after_attempt(3))
def make_spotify_request(endpoint, access_token):
    headers = {
        'Authorization': f'Bearer {access_token}'
    }
    response = requests.get(endpoint, headers=headers)
    response.raise_for_status()
    return response.json()

def sanitize_filename(filename):
    return re.sub(r'[<>:"/\\|?*]', '', filename).strip()

def save_image(image_url):
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
    
    info = make_spotify_request(endpoint, access_token)
    
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
    
    return title, artist, album_art_url

main_bp = Blueprint('main', __name__)

@main_bp.route('/')
def index():
    return render_template('index.html')

@main_bp.route('/result', methods=['POST'])
def result():
    spotify_url = request.form['spotify_url']
    content_id, content_type = spotify_url_to_id(spotify_url)
    
    if content_id is None:
        flash("Invalid Spotify URL. Please try again.")
        return redirect(url_for('main.index'))

    try:
        title, artist, album_art_url = get_spotify_info(content_type, content_id)
    except Exception as e:
        logging.error(f"Error fetching Spotify data: {e}")
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
        return str(e), 400
    except requests.RequestException as e:
        logging.error(f"Error fetching Spotify data: {e}")
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
        return "File type not supported", 400

    file_name_encoded = urllib.parse.quote(file_name)

    return Response(file_content,
                    mimetype=mimetype,
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{file_name_encoded}"})

@main_bp.route('/back')
def back():
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