import requests
from flask import Flask, request, render_template, send_file, Response, redirect, url_for
from PIL import Image
from io import BytesIO
import os
from dotenv import load_dotenv
import re
import urllib.parse

app = Flask(__name__)

# Load environment variables from .env file
load_dotenv()

# Get Spotify API credentials from environment variables
CLIENT_ID = os.getenv('SPOTIFY_CLIENT_ID')
CLIENT_SECRET = os.getenv('SPOTIFY_CLIENT_SECRET')

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

def save_image(image_url):
    response = requests.get(image_url)
    img = Image.open(BytesIO(response.content))
    img_io = BytesIO()
    img.save(img_io, format='PNG')
    img_io.seek(0)
    return img_io

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

def get_track_title_artist(track_id):
    access_token = get_access_token()
    track_info = get_track_info(access_token, track_id)
    title = track_info['name']
    artist = track_info['artists'][0]['name']
    album_art_url = track_info['album']['images'][0]['url']
    return title, artist, album_art_url

def get_album_title_artist(album_id):
    access_token = get_access_token()
    album_info = get_album_info(access_token, album_id)
    title = album_info['name']
    artist = album_info['artists'][0]['name']
    album_art_url = album_info['images'][0]['url']
    return title, artist, album_art_url

def get_playlist_title_artist(playlist_id):
    access_token = get_access_token()
    playlist_info = get_playlist_info(access_token, playlist_id)
    title = playlist_info['name']
    artist = playlist_info['owner']['display_name']  # Set artist name to playlist owner
    album_art_url = playlist_info['images'][0]['url']
    return title, artist, album_art_url

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
    album_art_filename = f'{sanitized_title}_{sanitized_artist}_album_art.png'
    spotify_code_filename = f'{sanitized_title}_{sanitized_artist}_spotify_code.svg'

    # Save album art with unique name based on title and artist
    album_art_img_io = save_image(album_art_url)

    # Generate Spotify code
    spotify_code_svg = get_spotify_code(f'spotify:{content_type}:{track_id}')
    spotify_code_io = BytesIO(spotify_code_svg)

    return render_template('result.html',
                          title=title,
                          artist=artist,
                          album_art_url=urllib.parse.quote(album_art_filename),
                          spotify_code_url=urllib.parse.quote(spotify_code_filename),
                          spotify_url=spotify_url)

@app.route('/download/<file_type>')
def download(file_type):
    spotify_url = request.args.get('spotify_url')
    track_id, content_type = spotify_url_to_id(spotify_url)

    if content_type == 'track':
        title, artist, album_art_url = get_track_title_artist(track_id)
    elif content_type == 'album':
        title, artist, album_art_url = get_album_title_artist(track_id)
    elif content_type == 'playlist':
        title, artist, album_art_url = get_playlist_title_artist(track_id)
    else:
        return "Unsupported Spotify URL type", 400

    sanitized_title = sanitize_filename(title)
    sanitized_artist = sanitize_filename(artist)

    if file_type == 'album_art':
        file_name = f'{sanitized_title}_{sanitized_artist}_album_art.png'
        file_content = save_image(album_art_url).getvalue()
        mimetype = 'image/png'
    elif file_type == 'spotify_code':
        file_name = f'{sanitized_title}_{sanitized_artist}_spotify_code.svg'
        file_content = get_spotify_code(f'spotify:{content_type}:{track_id}')
        mimetype = 'image/svg+xml'
    else:
        return "File type not supported", 400

    # Encode file name for safe HTTP headers
    file_name_encoded = urllib.parse.quote(file_name)

    return Response(file_content,
                    mimetype=mimetype,
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{file_name_encoded}"})

@app.route('/back')
def back():
    return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(port=8888, threaded=True)