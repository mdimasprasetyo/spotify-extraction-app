import requests
from flask import Flask, request, render_template, send_file
from PIL import Image
from io import BytesIO
import os
from dotenv import load_dotenv
import re

app = Flask(__name__)

# Load environment variables from .env file
load_dotenv()

# Get Spotify API credentials from environment variables
CLIENT_ID = os.getenv('SPOTIFY_CLIENT_ID')
CLIENT_SECRET = os.getenv('SPOTIFY_CLIENT_SECRET')
REDIRECT_URI = 'http://localhost:8888/callback'

def get_access_token():
    url = 'https://accounts.spotify.com/api/token'
    headers = {
        'Content-Type': 'application/x-www-form-urlencoded'
    }
    data = {
        'grant_type': 'client_credentials'
    }
    response = requests.post(url, headers=headers, data=data, auth=(CLIENT_ID, CLIENT_SECRET))
    return response.json()['access_token']

def get_track_info(access_token, track_id):
    url = f'https://api.spotify.com/v1/tracks/{track_id}'
    headers = {
        'Authorization': f'Bearer {access_token}'
    }
    response = requests.get(url, headers=headers)
    return response.json()

def get_album_info(access_token, album_id):
    url = f'https://api.spotify.com/v1/albums/{album_id}'
    headers = {
        'Authorization': f'Bearer {access_token}'
    }
    response = requests.get(url, headers=headers)
    return response.json()

def get_playlist_info(access_token, playlist_id):
    url = f'https://api.spotify.com/v1/playlists/{playlist_id}'
    headers = {
        'Authorization': f'Bearer {access_token}'
    }
    response = requests.get(url, headers=headers)
    return response.json()

def sanitize_filename(filename):
    """Sanitize filename to be filesystem-friendly."""
    return re.sub(r'[<>:"/\\|?*]', '', filename).strip()

def save_image(image_url, file_name):
    response = requests.get(image_url)
    img = Image.open(BytesIO(response.content))
    img.save(file_name, 'PNG')

def spotify_url_to_id(url):
    """Convert Spotify URL to URI or ID format."""
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
    return response.content

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/result', methods=['POST'])
def result():
    spotify_url = request.form['spotify_url']
    track_id, content_type = spotify_url_to_id(spotify_url)
    if track_id is None:
        return "Invalid Spotify URL", 400

    access_token = get_access_token()

    if content_type == 'track':
        track_info = get_track_info(access_token, track_id)
        title = track_info['name']
        artist = track_info['artists'][0]['name']
        album_art_url = track_info['album']['images'][0]['url']
    elif content_type == 'album':
        album_info = get_album_info(access_token, track_id)
        title = album_info['name']
        artist = album_info['artists'][0]['name']
        album_art_url = album_info['images'][0]['url']
    elif content_type == 'playlist':
        playlist_info = get_playlist_info(access_token, track_id)
        title = playlist_info['name']
        artist = playlist_info['owner']['display_name']  # Set artist name to playlist owner
        album_art_url = playlist_info['images'][0]['url']
    else:
        return "Unsupported Spotify URL type", 400

    # Sanitize title and artist for filenames
    sanitized_title = sanitize_filename(title)
    sanitized_artist = sanitize_filename(artist)
    album_art_filename = f'static/{sanitized_title}_{sanitized_artist}_album_art.png'
    spotify_code_filename = f'static/{sanitized_title}_{sanitized_artist}_spotify_code.svg'

    # Save album art with unique name based on title and artist
    save_image(album_art_url, album_art_filename)

    # Generate Spotify code
    spotify_code_svg = get_spotify_code(f'spotify:{content_type}:{track_id}')
    
    # Save SVG with unique name based on title and artist
    with open(spotify_code_filename, 'wb') as f:
        f.write(spotify_code_svg)

    return render_template('result.html', title=title, artist=artist, album_art_url=album_art_filename, spotify_code_url=spotify_code_filename)

@app.route('/download/<filename>')
def download(filename):
    file_path = os.path.join('static', filename)
    if os.path.exists(file_path):
        return send_file(file_path, as_attachment=True)
    else:
        return "File not found", 404

if __name__ == '__main__':
    app.run(port=8888)