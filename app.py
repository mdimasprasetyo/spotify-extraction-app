import requests
from flask import Flask, request, render_template, send_file, Response
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

def get_image_from_url(image_url):
    response = requests.get(image_url)
    return Image.open(BytesIO(response.content))

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

    # Fetch and serve album art dynamically
    album_art_img = get_image_from_url(album_art_url)
    album_art_bytes = BytesIO()
    album_art_img.save(album_art_bytes, format='PNG')
    album_art_bytes.seek(0)

    # Generate Spotify code dynamically
    spotify_code_svg = get_spotify_code(f'spotify:{content_type}:{track_id}')
    spotify_code_bytes = BytesIO(spotify_code_svg)
    spotify_code_bytes.seek(0)

    return render_template(
        'result.html',
        title=title,
        artist=artist,
        album_art_url='/dynamic_album_art?spotify_url=' + spotify_url,
        spotify_code_url='/dynamic_spotify_code?spotify_url=' + spotify_url
    )

@app.route('/dynamic_album_art')
def dynamic_album_art():
    spotify_url = request.args.get('spotify_url')
    track_id, content_type = spotify_url_to_id(spotify_url)
    if track_id is None:
        return "Invalid Spotify URL", 400

    access_token = get_access_token()

    if content_type == 'track':
        track_info = get_track_info(access_token, track_id)
        album_art_url = track_info['album']['images'][0]['url']
    elif content_type == 'album':
        album_info = get_album_info(access_token, track_id)
        album_art_url = album_info['images'][0]['url']
    elif content_type == 'playlist':
        playlist_info = get_playlist_info(access_token, track_id)
        album_art_url = playlist_info['images'][0]['url']
    else:
        return "Unsupported Spotify URL type", 400

    album_art_img = get_image_from_url(album_art_url)
    album_art_bytes = BytesIO()
    album_art_img.save(album_art_bytes, format='PNG')
    album_art_bytes.seek(0)

    return send_file(album_art_bytes, mimetype='image/png', as_attachment=False)

@app.route('/dynamic_spotify_code')
def dynamic_spotify_code():
    spotify_url = request.args.get('spotify_url')
    track_id, content_type = spotify_url_to_id(spotify_url)
    if track_id is None:
        return "Invalid Spotify URL", 400

    spotify_code_svg = get_spotify_code(f'spotify:{content_type}:{track_id}')
    spotify_code_bytes = BytesIO(spotify_code_svg)
    spotify_code_bytes.seek(0)

    return send_file(spotify_code_bytes, mimetype='image/svg+xml', as_attachment=False)

@app.route('/download/<file_type>')
def download(file_type):
    spotify_url = request.args.get('spotify_url')
    track_id, content_type = spotify_url_to_id(spotify_url)
    if track_id is None:
        return "Invalid Spotify URL", 400

    access_token = get_access_token()

    if file_type == 'album_art':
        if content_type == 'track':
            track_info = get_track_info(access_token, track_id)
            album_art_url = track_info['album']['images'][0]['url']
        elif content_type == 'album':
            album_info = get_album_info(access_token, track_id)
            album_art_url = album_info['images'][0]['url']
        elif content_type == 'playlist':
            playlist_info = get_playlist_info(access_token, track_id)
            album_art_url = playlist_info['images'][0]['url']
        else:
            return "Unsupported Spotify URL type", 400

        album_art_img = get_image_from_url(album_art_url)
        album_art_bytes = BytesIO()
        album_art_img.save(album_art_bytes, format='PNG')
        album_art_bytes.seek(0)
        return send_file(album_art_bytes, mimetype='image/png', as_attachment=True, download_name=f"{sanitize_filename(title)}_{sanitize_filename(artist)}_album_art.png")

    elif file_type == 'spotify_code':
        spotify_code_svg = get_spotify_code(f'spotify:{content_type}:{track_id}')
        spotify_code_bytes = BytesIO(spotify_code_svg)
        spotify_code_bytes.seek(0)
        return send_file(spotify_code_bytes, mimetype='image/svg+xml', as_attachment=True, download_name=f"{sanitize_filename(title)}_{sanitize_filename(artist)}_spotify_code.svg")

    return "File type not supported", 400

if __name__ == '__main__':
    app.run(port=8888)