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
from requests.exceptions import HTTPError, RequestException

load_dotenv()

app = Flask(__name__)
app.config.from_object(Config)
app.config["SPOTIFY_CLIENT_ID"] = os.getenv("SPOTIFY_CLIENT_ID")
app.config["SPOTIFY_CLIENT_SECRET"] = os.getenv("SPOTIFY_CLIENT_SECRET")
app.secret_key = app.config['SECRET_KEY']

cache = Cache(app, config={'CACHE_TYPE': 'SimpleCache'})

logging.basicConfig(
    level=logging.DEBUG if app.debug else logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

def validate_spotify_credentials():
    if not app.config.get("SPOTIFY_CLIENT_ID") or not app.config.get("SPOTIFY_CLIENT_SECRET"):
        logger.error("Spotify API credentials are missing in environment variables.")
        exit(1)

validate_spotify_credentials()

@retry(wait=wait_fixed(2), stop=stop_after_attempt(5))
def get_access_token():
    cached_token = cache.get('spotify_access_token')
    if cached_token:
        logger.info("Using cached Spotify access token.")
        return cached_token

    url = "https://accounts.spotify.com/api/token"
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    data = {"grant_type": "client_credentials"}

    response = requests.post(
        url,
        headers=headers,
        data=data,
        auth=(app.config["SPOTIFY_CLIENT_ID"], app.config["SPOTIFY_CLIENT_SECRET"])
    )

    if response.status_code == 401:
        logger.error("Invalid Spotify credentials.")
        raise Exception("Invalid Spotify API credentials")

    response.raise_for_status()
    token = response.json()["access_token"]
    cache.set("spotify_access_token", token, timeout=3600)
    logger.info("Fetched new Spotify access token.")
    return token

@retry(wait=wait_fixed(2), stop=stop_after_attempt(3))
def make_spotify_request(endpoint, access_token):
    headers = {"Authorization": f"Bearer {access_token}"}
    response = requests.get(endpoint, headers=headers)
    logger.debug(f"Request to Spotify API: {endpoint}")

    if response.status_code == 403:
        raise Exception("The playlist may be private or restricted.")
    elif response.status_code >= 400:
        response.raise_for_status()

    return response.json()

def sanitize_filename(filename):
    return re.sub(r'[<>:"/\\|?*]', '', filename).strip()

def normalize_to_plain_text(text):
    normalized_text = unicodedata.normalize('NFKC', text)
    plain_text = ''.join(
        char for char in normalized_text 
        if not unicodedata.combining(char) or unicodedata.category(char).startswith('M')
    )
    return plain_text

def save_image(image_url):
    try:
        logger.debug(f"Downloading image from: {image_url}")
        image_url += f"?t={int(time.time())}"
        response = requests.get(image_url, timeout=10)
        response.raise_for_status()

        img = Image.open(BytesIO(response.content))
        if img.mode == "CMYK":
            img = img.convert("RGB")

        img_io = BytesIO()
        img.save(img_io, format="PNG")
        img_io.seek(0)
        return img_io
    except Exception as e:
        logger.error(f"Failed to save image: {e}")
        return BytesIO()

def spotify_url_to_id(url):
    """Extract Spotify ID and type from URL, including short link expansion."""
    content_map = {
        'track': 'track', 'album': 'album', 'playlist': 'playlist',
        'artist': 'artist', 'show': 'show', 'episode': 'episode'
    }

    if 'spotify.link' in url:
        try:
            logger.info(f"Expanding short Spotify link: {url}")
            response = requests.get(url, allow_redirects=True, timeout=3, stream=True)
            expanded = response.url
            logger.debug(f"Expanded short link: {expanded}")

            if expanded.strip() == "https://open.spotify.com/" or expanded.strip().endswith("open.spotify.com/"):
                flash("Invalid or incomplete Spotify short link. Please copy the full link from the Spotify app.")
                logger.warning(f"Incomplete Spotify short link detected: {url} -> {expanded}")
                return None, None

            url = expanded

        except Exception as e:
            logger.error(f"Failed to expand short link {url}: {e}")
            flash("Failed to expand Spotify short link. Please copy the full link from the Spotify app.")
            return None, None

    for key in content_map:
        if f"/{key}/" in url:
            content_id = url.split("/")[-1].split("?")[0]
            return content_id, content_map[key]

    flash("Invalid or unsupported Spotify link.")
    logger.warning(f"Unrecognized Spotify URL: {url}")
    return None, None

def get_spotify_code(uri):
    url = f'https://scannables.scdn.co/uri/plain/svg/ffffff/black/640/{uri}'
    logger.debug(f"Fetching Spotify code for URI: {uri}")
    
    response = requests.get(url)
    response.raise_for_status()
    return response.content

def get_spotify_info(content_type, content_id):
    access_token = get_access_token()
    endpoints = {
        "track": f"https://api.spotify.com/v1/tracks/{content_id}",
        "album": f"https://api.spotify.com/v1/albums/{content_id}",
        "playlist": f"https://api.spotify.com/v1/playlists/{content_id}",
        "artist": f"https://api.spotify.com/v1/artists/{content_id}",
        "show": f"https://api.spotify.com/v1/shows/{content_id}",
        "episode": f"https://api.spotify.com/v1/episodes/{content_id}"
    }

    if content_type not in endpoints:
        raise ValueError("Unsupported Spotify content type")

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
        flash("Unexpected error fetching Spotify data.")
        logger.error(f"Unexpected error: {e}")
        return None, None, None

    if content_type == "track":
        title = info["name"]
        artist = ", ".join(a["name"] for a in info["artists"])
        image = info["album"]["images"][0]["url"] if info["album"].get("images") else None
    elif content_type == "album":
        title = info["name"]
        artist = ", ".join(a["name"] for a in info["artists"])
        image = info["images"][0]["url"] if info.get("images") else None
    elif content_type == "playlist":
        title = normalize_to_plain_text(info["name"])
        artist = normalize_to_plain_text(info["owner"]["display_name"])
        image = info["images"][0]["url"] if info.get("images") else None
    elif content_type == "artist":
        title = info["name"]
        artist = ""
        image = info["images"][0]["url"] if info.get("images") else None
    elif content_type == "show":
        title = info["name"]
        artist = info["publisher"]
        image = info["images"][0]["url"] if info.get("images") else None
    elif content_type == "episode":
        title = info["name"]
        artist = info["show"]["publisher"]
        image = info["images"][0]["url"] if info.get("images") else None
    else:
        flash("Unsupported Spotify link type.")
        return None, None, None

    return title, artist, image

main_bp = Blueprint("main", __name__)

@main_bp.route("/")
def index():
    return render_template("index.html")

@main_bp.route("/show_result")
def show_result():
    spotify_url = request.args.get("spotify_url")
    if not spotify_url:
        flash("No Spotify URL provided.")
        return redirect(url_for("main.index"))

    try:
        content_id, content_type = spotify_url_to_id(spotify_url)
        if content_id is None:
            return redirect(url_for("main.index"))

        title, artist, album_art_url = get_spotify_info(content_type, content_id)
        if not title:
            return redirect(url_for("main.index"))

    except Exception as e:
        logger.error(f"Error processing Spotify URL {spotify_url} for display: {e}")
        flash("An unexpected error occurred while retrieving Spotify data.")
        return redirect(url_for("main.index"))

    return render_template(
        "result.html",
        title=title,
        artist=artist,
        link_type=content_type.capitalize(),
        album_art_url=album_art_url,
        spotify_url=spotify_url
    )

@main_bp.route("/result", methods=["POST"])
def result():
    spotify_url = request.form["spotify_url"].strip()

    if "youtube.com" in spotify_url.lower():
        redirect_url = spotify_url if spotify_url.startswith(("http://", "https://")) else f"https://{spotify_url}"
        return redirect(redirect_url)

    content_id, content_type = spotify_url_to_id(spotify_url)

    if content_id is None:
        return redirect(url_for("main.index"))

    return redirect(url_for("main.show_result", spotify_url=spotify_url))

@main_bp.route("/download/<file_type>")
@cache.cached(timeout=3600, query_string=True)
def download(file_type):
    spotify_url = request.args.get("spotify_url")
    if not spotify_url:
        return "Missing Spotify URL", 400

    content_id, content_type = spotify_url_to_id(spotify_url)
    if not content_id:
        return "Invalid Spotify URL", 400

    title, artist, album_art_url = get_spotify_info(content_type, content_id)
    sanitized_title = sanitize_filename(title)
    sanitized_artist = sanitize_filename(artist)

    if file_type == "album_art":
        file_content = save_image(album_art_url).getvalue()
        mimetype = "image/png"
        file_name = f"{sanitized_title}_{sanitized_artist}_album_art.png"
    elif file_type == "spotify_code":
        file_content = get_spotify_code(f"spotify:{content_type}:{content_id}")
        mimetype = "image/svg+xml"
        file_name = f"{sanitized_title}_{sanitized_artist}_code.svg"
    else:
        return "File type not supported", 400

    response = Response(file_content, mimetype=mimetype)
    response.headers["Content-Disposition"] = f"attachment; filename*=UTF-8''{urllib.parse.quote(file_name)}"
    response.headers["Cache-Control"] = "public, max-age=86400"
    response.headers["ETag"] = hashlib.md5(file_content).hexdigest()

    if request.headers.get("If-None-Match") == response.headers["ETag"]:
        response.status_code = 304
    return response

app.register_blueprint(main_bp)

@app.after_request
def add_security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response

if __name__ == "__main__":
    flask_env = os.getenv("FLASK_ENV", "production").lower()
    host = "127.0.0.1" if flask_env == "development" else "0.0.0.0"
    port = int(os.getenv("PORT", 8888))

    app.run(host=host, port=port, debug=(flask_env == "development"))
