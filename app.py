import yt_dlp
import whisper
import os
import re
from pathlib import Path
from flask import Flask, request, render_template, redirect, url_for
import sqlite3

# Initialize Flask app
app = Flask(__name__)

def init_db():
    """Initialize SQLite database."""
    conn = sqlite3.connect('videos.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS videos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            video_title TEXT,
            mp3_file_link TEXT,
            transcription_file_link TEXT,
            transcription TEXT,
            platform TEXT,
            category TEXT
        )
    ''')
    conn.commit()
    conn.close()

init_db()

def sanitize_filename(filename):
    """Remove special characters from filenames."""
    return re.sub(r'[<>:"/\\|?*]', '', filename)

def verify_audio_file(file_path):
    """Verify that the audio file exists and is not empty."""
    if not file_path.exists():
        raise RuntimeError(f"Audio file {file_path} does not exist.")
    if file_path.stat().st_size == 0:
        raise RuntimeError(f"Audio file {file_path} is empty.")

def download_video(url, output_dir="static/downloads"):
    """Download YouTube video as audio."""
    output_path = Path(output_dir)
    output_path.mkdir(exist_ok=True)

    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': str(output_path / '%(title)s.%(ext)s'),  # Use original title
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        # Get the actual filename from yt_dlp's output
        filename = Path(ydl.prepare_filename(info))
        audio_path = filename.with_suffix('.mp3')

        verify_audio_file(audio_path)

        return info.get("title", "unknown_title"), audio_path

def download_instagram_video(url, output_dir="static/downloads"):
    """Download Instagram video as MP4."""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    ydl_opts = {
        'format': 'bestvideo+bestaudio/best',
        'outtmpl': str(output_path / '%(title)s.%(ext)s'),
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        # Get the actual filename from yt_dlp's output
        video_path = output_path / f"{sanitize_filename(info.get('title', 'unknown_title'))}.mp4"

        if not video_path.exists():
            raise RuntimeError(f"Video file {video_path} does not exist.")

        return info.get("title", "unknown_title"), str(video_path).replace("\\", "/")


def transcribe_audio(audio_path):
    """Transcribe audio using OpenAI Whisper."""
    try:
        model = whisper.load_model("base")
        result = model.transcribe(str(audio_path))
        return result['text']
    except Exception as e:
        raise RuntimeError(f"Failed to transcribe audio: {e}")

def save_to_db(video_title, mp3_file, transcription_file, transcription, platform, category):
    """Save video details to the SQLite database."""
    conn = sqlite3.connect('videos.db')
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO videos (video_title, mp3_file_link, transcription_file_link, transcription, platform, category)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (
        video_title,
        str(mp3_file).replace("\\", "/") if mp3_file else None,
        str(transcription_file).replace("\\", "/") if transcription_file else None,
        transcription,
        platform,
        category
    ))
    conn.commit()
    conn.close()

def get_all_videos():
    """Retrieve all video records from the database."""
    conn = sqlite3.connect('videos.db')
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM videos')
    videos = cursor.fetchall()
    conn.close()
    return videos

def search_videos_by_category(category):
    """Retrieve videos by category."""
    conn = sqlite3.connect('videos.db')
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM videos WHERE category = ?', (category,))
    videos = cursor.fetchall()
    conn.close()
    return videos

def delete_video(video_id):
    """Delete a video record from the database and its associated files."""
    conn = sqlite3.connect('videos.db')
    cursor = conn.cursor()
    cursor.execute('SELECT mp3_file_link, transcription_file_link FROM videos WHERE id = ?', (video_id,))
    result = cursor.fetchone()

    if result:
        mp3_file, transcription_file = result
        # Delete the files
        if mp3_file and os.path.exists(mp3_file):
            os.remove(mp3_file)
        if transcription_file and os.path.exists(transcription_file):
            os.remove(transcription_file)

        # Delete the record from the database
        cursor.execute('DELETE FROM videos WHERE id = ?', (video_id,))
        conn.commit()

    conn.close()

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        url = request.form['url']
        platform = request.form.get('platform', 'youtube')
        category = request.form.get('category', 'Uncategorized')

        try:
            if platform == 'youtube':
                # Download YouTube video and transcribe
                video_title, audio_path = download_video(url)
                audio_path = Path(audio_path)  # Ensure it's a Path object
                transcription = transcribe_audio(audio_path)

                # Save transcription to a file
                transcription_file = audio_path.with_suffix('.txt')
                with open(transcription_file, 'w', encoding='utf-8') as f:
                    f.write(transcription)

                # Save details to database
                save_to_db(video_title, str(audio_path), str(transcription_file), transcription, platform, category)

            elif platform == 'instagram':
                # Download Instagram video
                video_title, video_path = download_instagram_video(url)
                video_path = Path(video_path)  # Ensure it's a Path object

                # Save details to database
                save_to_db(video_title, str(video_path), None, None, platform, category)

        except Exception as e:
            return f"An error occurred: {e}", 500

        return redirect(url_for('index'))

    # Search functionality
    search_category = request.args.get('category', None)
    if search_category:
        videos = search_videos_by_category(search_category)
    else:
        videos = get_all_videos()

    return render_template('index.html', videos=videos)

@app.route('/delete/<int:video_id>', methods=['POST'])
def delete(video_id):
    try:
        delete_video(video_id)
    except Exception as e:
        return f"An error occurred: {e}", 500

    return redirect(url_for('index'))

if __name__ == "__main__":
    app.run(debug=True)
