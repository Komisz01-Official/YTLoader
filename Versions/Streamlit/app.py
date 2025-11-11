import streamlit as st
import yt_dlp
import os
import re
import pandas as pd
from typing import List, Dict, Set
import time
import requests
from io import BytesIO
from PIL import Image
import subprocess
import logging
import sys

# Suppress yt-dlp and other library warnings
logging.getLogger('yt_dlp').setLevel(logging.ERROR)
os.environ['PYTHONWARNINGS'] = 'ignore'

def get_app_data_path():
    """Get the proper application data directory with downloads folder"""
    if getattr(sys, 'frozen', False):
        # Running as compiled executable - use the executable's directory
        base_path = os.path.dirname(sys.executable)
    else:
        # Running as script - use current directory
        base_path = os.path.dirname(__file__)
    
    # Create downloads folder in the application directory
    downloads_path = os.path.join(base_path, "downloads")
    os.makedirs(downloads_path, exist_ok=True)
    return downloads_path

def get_default_download_path():
    """Get user's default Downloads folder"""
    # Try to get user's Downloads folder
    user_downloads = os.path.join(os.path.expanduser("~"), "Downloads")
    if os.path.exists(user_downloads):
        # Create a subfolder for our app
        app_downloads = os.path.join(user_downloads, "YouTubePlaylistDownloads")
        os.makedirs(app_downloads, exist_ok=True)
        return app_downloads
    
    # Fallback to app directory
    return get_app_data_path()

class YouTubePlaylistDownloader:
    def __init__(self, download_path=None):
        if download_path is None:
            # Default to user's Downloads folder with our app subfolder
            self.download_path = get_default_download_path()
        else:
            self.download_path = download_path
        
        self.create_download_directory()
        self.ffmpeg_available = self.check_ffmpeg()
    
    def create_download_directory(self):
        """Create download directory if it doesn't exist"""
        if not os.path.exists(self.download_path):
            os.makedirs(self.download_path)
    
    def check_ffmpeg(self):
        """Check if FFmpeg is available (silent check)"""
        try:
            result = subprocess.run(['ffmpeg', '-version'], 
                                  capture_output=True, text=True, timeout=5)
            return result.returncode == 0
        except:
            return False
    
    def is_valid_playlist_url(self, url):
        """Check if the URL is a valid YouTube playlist URL"""
        playlist_pattern = r'^(https?://)?(www\.)?(youtube\.com|youtu\.?be)/playlist\?list=([a-zA-Z0-9_-]+)'
        return re.match(playlist_pattern, url) is not None
    
    def get_playlist_info(self, playlist_url):
        """Get information about the playlist and all videos"""
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': True,
        }
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                playlist_info = ydl.extract_info(playlist_url, download=False)
                return playlist_info
        except Exception as e:
            st.error(f"Error getting playlist info: {e}")
            return None
    
    def get_video_thumbnail(self, video_id, quality='maxresdefault'):
        """Get video thumbnail from YouTube"""
        try:
            thumbnail_url = f"https://i.ytimg.com/vi/{video_id}/{quality}.jpg"
            response = requests.get(thumbnail_url, timeout=10)
            
            if response.status_code == 200:
                image = Image.open(BytesIO(response.content))
                return image
        except:
            pass
        return None
    
    def progress_hook(self, d, status_container, video_title, console_content, update_console):
        """Progress hook for real-time download feedback"""
        if d['status'] == 'downloading':
            percent = d.get('_percent_str', '').strip()
            speed = d.get('_speed_str', '').strip()
            eta = d.get('_eta_str', '').strip()
            
            if percent and speed:
                status_text = f"📥 {video_title[:50]}... | {percent} | {speed} | ETA: {eta}"
                status_container.text(status_text)
                
        elif d['status'] == 'finished':
            filename = d.get('filename', '')
            file_ext = filename.split('.')[-1] if '.' in filename else 'file'
            status_container.text(f"✅ {video_title[:50]}... | Download completed (.{file_ext})")
            
        elif d['status'] == 'error':
            status_container.text(f"❌ {video_title[:50]}... | Download failed")
    
    def download_videos(self, video_urls: List[str], selected_indices: Set[int], 
                       audio_only: bool = False, quality: str = 'best'):
        """Download selected videos with real-time feedback"""
        if not video_urls:
            st.error("No videos selected for download")
            return False
        
        # Configure download options - SIMPLIFIED and RELIABLE
        ydl_opts = {
            'outtmpl': os.path.join(self.download_path, '%(title)s.%(ext)s'),
            # Basic settings for reliability
            'quiet': False,
            'no_warnings': False,
            'ignoreerrors': True,  # Continue on errors
            # Retry settings
            'retries': 10,
            'fragment_retries': 10,
            'file_access_retries': 3,
            # Timeout settings
            'socket_timeout': 30,
            'extract_timeout': 60,
            # Format selection
            'format': 'best[height<=720]/best[height<=480]/best' if not audio_only else 'bestaudio/best',
            # Force overwrite
            'overwrites': True,
            # Skip problematic formats
            'extract_flat': False,
        }
        
        if audio_only:
            if self.ffmpeg_available:
                ydl_opts.update({
                    'format': 'bestaudio/best',
                    'postprocessors': [{
                        'key': 'FFmpegExtractAudio',
                        'preferredcodec': 'mp3',
                        'preferredquality': '192',
                    }]
                })
            else:
                ydl_opts['format'] = 'bestaudio[ext=m4a]/bestaudio/best'
        else:
            quality_map = {
                'best': 'best[height<=1080]/best[height<=720]/best',
                '1080p': 'best[height<=1080]',
                '720p': 'best[height<=720]',
                '480p': 'best[height<=480]',
                '360p': 'best[height<=360]',
            }
            ydl_opts['format'] = quality_map.get(quality, 'best[height<=720]/best')
        
        success_count = 0
        total_count = len(selected_indices)
        
        if total_count == 0:
            st.error("No videos selected")
            return False
        
        # Create a console-like output area
        st.subheader("📊 Download Console")
        console_output = st.empty()
        
        # Create progress bar
        progress_bar = st.progress(0)
        overall_status = st.empty()
        
        # Initialize console content
        console_content = []
        
        def update_console():
            console_output.markdown(
                f"<div style='background-color: #000; color: #0f0; padding: 10px; border-radius: 5px; font-family: monospace; height: 300px; overflow-y: auto;'>{'<br>'.join(console_content)}</div>", 
                unsafe_allow_html=True
            )
        
        # Add initial message
        console_content.append("🚀 Starting download process...")
        console_content.append(f"📁 Downloading {total_count} videos to: {self.download_path}")
        console_content.append("⚡ Using reliable download settings")
        if audio_only:
            console_content.append("🎵 Format: Audio" + (" (MP3)" if self.ffmpeg_available else " (M4A)"))
        else:
            console_content.append(f"🎬 Format: Video ({quality})")
        console_content.append("─" * 50)
        update_console()
        
        for i, idx in enumerate(sorted(selected_indices)):
            if idx < len(video_urls):
                video_url = video_urls[idx]
                video_title = st.session_state.video_data[idx]['title']
                
                # Update overall progress
                overall_status.text(f"Processing {i+1}/{total_count}: {video_title[:60]}...")
                progress_bar.progress((i) / total_count)
                
                # Add to console
                console_content.append(f"📥 [{i+1}/{total_count}] Starting: {video_title}")
                update_console()
                
                try:
                    # Create individual progress hook for this video
                    status_container = st.empty()
                    
                    def create_hook(container, title):
                        return lambda d: self.progress_hook(d, container, title, console_content, update_console)
                    
                    # Set progress hook for this download
                    current_ydl_opts = ydl_opts.copy()
                    current_ydl_opts['progress_hooks'] = [create_hook(status_container, video_title)]
                    
                    # SIMPLE DIRECT DOWNLOAD - NO THREADING
                    console_content.append(f"🔗 [{i+1}/{total_count}] Connecting to: {video_url}")
                    update_console()
                    
                    with yt_dlp.YoutubeDL(current_ydl_opts) as ydl:
                        info = ydl.extract_info(video_url, download=True)
                        
                    # Check if file was actually downloaded
                    filename = ydl.prepare_filename(info)
                    if os.path.exists(filename):
                        success_count += 1
                        file_size = os.path.getsize(filename)
                        file_size_mb = f"{file_size / 1024 / 1024:.1f}MB"
                        console_content.append(f"✅ [{i+1}/{total_count}] SUCCESS: {video_title} ({file_size_mb})")
                        status_container.text(f"✅ {video_title[:50]}... | Download completed")
                    else:
                        console_content.append(f"❌ [{i+1}/{total_count}] FAILED: {video_title} - File not created")
                        status_container.text(f"❌ {video_title[:50]}... | File not created")
                    
                except Exception as e:
                    # Add detailed error message to console
                    error_msg = str(e)
                    console_content.append(f"❌ [{i+1}/{total_count}] ERROR: {video_title}")
                    console_content.append(f"   Details: {error_msg}")
                    status_container.text(f"❌ {video_title[:50]}... | Error: {error_msg[:50]}")
                
                # Update progress bar
                progress_bar.progress((i + 1) / total_count)
                
                # Small delay to make console readable
                time.sleep(1)
        
        # Final summary
        progress_bar.progress(100)
        overall_status.text("")
        
        console_content.append("─" * 50)
        if success_count == total_count:
            console_content.append(f"🎉 ALL DOWNLOADS COMPLETED SUCCESSFULLY! ({success_count}/{total_count})")
            st.balloons()
        elif success_count > 0:
            console_content.append(f"⚠️ PARTIAL SUCCESS: {success_count}/{total_count} downloads completed")
            console_content.append(f"❌ {total_count - success_count} downloads failed")
        else:
            console_content.append(f"💥 ALL DOWNLOADS FAILED! (0/{total_count})")
        
        console_content.append(f"📁 Files saved to: {self.download_path}")
        update_console()
        
        return success_count > 0

def main():
    st.set_page_config(
        page_title="YouTube Playlist Downloader",
        page_icon="🎵",
        layout="wide",
        initial_sidebar_state="expanded"
    )
    
    # Custom CSS for clean UI
    st.markdown("""
    <style>
    .main > div { padding: 1rem; }
    .stButton > button { width: 100%; }
    .video-card {
        padding: 1rem; margin: 0.5rem 0; border: 1px solid #ddd; border-radius: 0.5rem;
        background-color: #f9f9f9; display: flex; align-items: center; gap: 1rem;
    }
    .video-info { flex: 1; }
    .video-title { font-weight: bold; margin-bottom: 0.5rem; }
    .video-duration { color: #666; font-size: 0.9rem; }
    .success-box {
        padding: 1rem; background-color: #d4edda; border: 1px solid #c3e6cb;
        border-radius: 0.5rem; color: #155724; margin: 1rem 0;
    }
    @media (max-width: 768px) {
        .main > div { padding: 0.5rem; }
        .video-card { flex-direction: column; text-align: center; }
    }
    </style>
    """, unsafe_allow_html=True)
    
    st.title("🎵 YouTube Playlist Downloader")
    st.markdown("Download your favorite playlists with ease!")
    
    # Initialize downloader
    downloader = YouTubePlaylistDownloader()
    
    # Sidebar with dynamic folder selection
    with st.sidebar:
        st.header("⚙️ Settings")
        
        # Dynamic download folder selection
        st.subheader("📁 Download Location")
        current_folder = downloader.download_path
        st.info(f"Current: `{current_folder}`")
        
        # Show folder options
        st.write("**Quick Options:**")
        col1, col2 = st.columns(2)
        
        with col1:
            if st.button("📂 User Downloads", use_container_width=True, help="Save to your Downloads folder"):
                new_path = get_default_download_path()
                downloader.download_path = new_path
                st.success(f"✅ Set to: `{new_path}`")
                st.rerun()
        
        with col2:
            if st.button("🔄 App Folder", use_container_width=True, help="Save to app installation folder"):
                new_path = get_app_data_path()
                downloader.download_path = new_path
                st.success(f"✅ Set to: `{new_path}`")
                st.rerun()
        
        # Custom folder selection
        st.write("**Custom Folder:**")
        if st.button("🎯 Choose Custom Folder", use_container_width=True):
            try:
                import tkinter as tk
                from tkinter import filedialog
                root = tk.Tk()
                root.withdraw()
                root.attributes('-topmost', True)
                selected_folder = filedialog.askdirectory(
                    title="Select Download Folder",
                    initialdir=os.path.expanduser("~")
                )
                if selected_folder:
                    # Create a downloads subfolder in the selected location
                    downloads_subfolder = os.path.join(selected_folder, "YouTubeDownloads")
                    os.makedirs(downloads_subfolder, exist_ok=True)
                    downloader.download_path = downloads_subfolder
                    st.success(f"✅ Set to: `{downloads_subfolder}`")
                    st.rerun()
            except Exception as e:
                st.error(f"Could not open folder dialog: {e}")
        
        # Open folder button
        if st.button("📂 Open Download Folder", use_container_width=True):
            try:
                os.startfile(downloader.download_path)
            except:
                st.error("Could not open folder")
        
        st.divider()
        
        playlist_url = st.text_input(
            "📺 Playlist URL",
            placeholder="https://www.youtube.com/playlist?list=..."
        )
        
        download_type = st.radio(
            "📥 Download as:",
            ["Video", "Audio Only"],
            index=0
        )
        
        if download_type == "Video":
            quality = st.selectbox(
                "🎬 Video Quality:",
                ["best", "1080p", "720p", "480p", "360p"],
                index=1
            )
        else:
            quality = "best"
        
        audio_only = download_type == "Audio Only"
    
    # Initialize session state
    if 'selected_videos' not in st.session_state:
        st.session_state.selected_videos = set()
    if 'select_all_clicked' not in st.session_state:
        st.session_state.select_all_clicked = False
    if 'clear_all_clicked' not in st.session_state:
        st.session_state.clear_all_clicked = False
    if 'video_data' not in st.session_state:
        st.session_state.video_data = []
    if 'video_urls' not in st.session_state:
        st.session_state.video_urls = []
    
    # Main content area
    if playlist_url:
        if not downloader.is_valid_playlist_url(playlist_url):
            st.error("❌ Please enter a valid YouTube playlist URL")
            st.info("💡 Example: https://www.youtube.com/playlist?list=PLxxxxxxxxxxxxxx")
        else:
            with st.spinner("🔍 Fetching playlist information..."):
                playlist_info = downloader.get_playlist_info(playlist_url)
            
            if playlist_info:
                # Display playlist info
                st.subheader("📋 Playlist Information")
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("Playlist", playlist_info.get('title', 'Unknown'))
                with col2:
                    st.metric("Videos", playlist_info.get('playlist_count', 0))
                with col3:
                    st.metric("Channel", playlist_info.get('uploader', 'Unknown'))
                
                # Get videos
                videos = playlist_info.get('entries', [])
                if videos:
                    st.subheader("🎬 Select Videos to Download")
                    st.info("✅ Check the boxes next to videos you want to download")
                    
                    # Prepare video data
                    video_data = []
                    video_urls = []
                    
                    # Progress for thumbnails
                    thumbnail_progress = st.progress(0)
                    status_text = st.empty()
                    
                    for i, video in enumerate(videos):
                        if video:
                            video_id = video.get('id')
                            video_url = f"https://www.youtube.com/watch?v={video_id}"
                            video_urls.append(video_url)
                            
                            # Convert duration to readable format
                            duration = video.get('duration')
                            if duration and duration != 'Unknown':
                                minutes, seconds = divmod(duration, 60)
                                hours, minutes = divmod(minutes, 60)
                                if hours > 0:
                                    duration_str = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
                                else:
                                    duration_str = f"{minutes:02d}:{seconds:02d}"
                            else:
                                duration_str = "Unknown"
                            
                            # Get thumbnail
                            status_text.text(f"Loading thumbnails... ({i+1}/{len(videos)})")
                            thumbnail = downloader.get_video_thumbnail(video_id)
                            thumbnail_progress.progress((i + 1) / len(videos))
                            
                            video_data.append({
                                'index': i,
                                'id': video_id,
                                'title': video.get('title', 'Unknown Title'),
                                'duration': duration_str,
                                'url': video_url,
                                'thumbnail': thumbnail
                            })
                    
                    status_text.text("")
                    thumbnail_progress.empty()
                    
                    # Store in session state
                    st.session_state.video_data = video_data
                    st.session_state.video_urls = video_urls
                    
                    # Selection controls
                    col1, col2, col3 = st.columns([1, 1, 2])
                    with col1:
                        select_all = st.button("✅ Select All", key="select_all_btn", use_container_width=True)
                    with col2:
                        clear_all = st.button("❌ Clear All", key="clear_all_btn", use_container_width=True)
                    
                    # Handle select all/clear all buttons
                    if select_all:
                        st.session_state.selected_videos = set(range(len(video_data)))
                        st.session_state.select_all_clicked = True
                        st.session_state.clear_all_clicked = False
                        st.rerun()
                    
                    if clear_all:
                        st.session_state.selected_videos = set()
                        st.session_state.clear_all_clicked = True
                        st.session_state.select_all_clicked = False
                        st.rerun()
                    
                    # Display selection status
                    if st.session_state.select_all_clicked:
                        st.success("✅ All videos selected!")
                        st.session_state.select_all_clicked = False
                    
                    if st.session_state.clear_all_clicked:
                        st.info("🗑️ All selections cleared!")
                        st.session_state.clear_all_clicked = False
                    
                    # Display videos with checkboxes and thumbnails
                    st.write(f"**Selected: {len(st.session_state.selected_videos)}/{len(video_data)} videos**")
                    
                    # Create a form to handle checkbox state properly
                    with st.form("video_selection_form"):
                        # Create checkboxes and handle their state
                        for i, video in enumerate(video_data):
                            col1, col2, col3 = st.columns([1, 2, 10])
                            
                            with col1:
                                # Checkbox with proper state management
                                is_checked = st.checkbox(
                                    "Select",
                                    key=f"video_checkbox_{i}",
                                    value=(i in st.session_state.selected_videos),
                                    label_visibility="collapsed"
                                )
                            
                            with col2:
                                # Display thumbnail
                                if video['thumbnail']:
                                    st.image(
                                        video['thumbnail'],
                                        width=120,
                                        caption=""
                                    )
                                else:
                                    st.image(
                                        "https://via.placeholder.com/120x68/333333/FFFFFF?text=No+Thumbnail",
                                        width=120,
                                        caption="No thumbnail available"
                                    )
                            
                            with col3:
                                # Video info
                                st.markdown(f"""
                                <div class="video-info">
                                    <div class="video-title">{video['title']}</div>
                                    <div class="video-duration">⏱️ {video['duration']}</div>
                                </div>
                                """, unsafe_allow_html=True)
                        
                        # Update selections when form is submitted
                        submitted = st.form_submit_button("Update Selections", use_container_width=True)
                        if submitted:
                            # Re-read all checkbox states
                            new_selections = set()
                            for i in range(len(video_data)):
                                checkbox_key = f"video_checkbox_{i}"
                                if checkbox_key in st.session_state and st.session_state[checkbox_key]:
                                    new_selections.add(i)
                            
                            st.session_state.selected_videos = new_selections
                            st.rerun()
                    
                    # Download section
                    st.subheader("🚀 Download")
                    
                    if st.session_state.selected_videos:
                        st.success(f"✅ {len(st.session_state.selected_videos)} videos selected")
                        
                        if st.button("📥 Start Download", type="primary", use_container_width=True):
                            success = downloader.download_videos(
                                st.session_state.video_urls, 
                                st.session_state.selected_videos, 
                                audio_only, 
                                quality
                            )
                    else:
                        st.warning("⚠️ Please select at least one video to download")
                
                else:
                    st.error("❌ No videos found in this playlist")
            else:
                st.error("❌ Could not fetch playlist information. Please check the URL and try again.")
    
    else:
        # Welcome message
        st.markdown("""
        ## 📋 How to Use:
        
        1. **📺 Enter Playlist URL** in the sidebar
        2. **📥 Choose Format** - Video or Audio Only
        3. **🎬 Select Quality** if downloading videos
        4. **✅ Pick Videos** you want to download
        5. **🚀 Download** and enjoy!
        
        ## 🔧 Features:
        - ✅ Download entire playlists or individual videos
        - 🎵 Audio downloads (MP3 when possible)
        - 📱 Mobile-friendly interface
        - 🎯 Selective video downloading
        - ⚡ Real-time progress tracking
        - 🖼️ Video thumbnails
        - 📁 Flexible download locations
        
        ## 📁 Download Locations:
        - **User Downloads**: `YourPC/Downloads/YouTubePlaylistDownloads/`
        - **App Folder**: `ProgramFiles/AppName/downloads/`
        - **Custom**: Any folder you choose
        
        ## 💡 Example Playlist URL:
        `https://www.youtube.com/playlist?list=PLrENygEx3ZZlv0132vVd6nO1nO0WCbR9V`
        """)

if __name__ == "__main__":
    main()
