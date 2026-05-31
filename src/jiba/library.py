"""
Read and write iTunes Music Library XML files.

iTunes/Apple Music stores its library as an XML file in a format called
"plist" (property list). This file contains all your tracks, playlists,
and metadata in a structured text format that we can read and write with
Python's built-in plistlib.

This file is responsible for three things:
  1. Finding the library file on disk (auto-detecting the default location
     for Windows, macOS, and Linux).
  2. Reading the library into a list of Track objects (one per song).
  3. Writing changes back to the library, after creating a timestamped
     backup so you can undo the change if something goes wrong.
"""
import plistlib
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional
import platform

from .models import Track


# Default locations where iTunes/Music.app stores the library XML on each platform.
# We check these paths in order and use the first one that actually exists.
DEFAULT_LIBRARY_PATHS = {
    'Windows': [
        Path.home() / 'Music' / 'iTunes' / 'iTunes Music Library.xml',
    ],
    'Darwin': [  # macOS
        Path.home() / 'Music' / 'Music' / 'Music Library.xml',       # macOS 10.15+ Music.app
        Path.home() / 'Music' / 'iTunes' / 'iTunes Music Library.xml',  # Legacy iTunes
    ],
    'Linux': [
        Path.home() / '.wine' / 'drive_c' / 'Program Files (x86)' / 'iTunes' / 'iTunes Music Library.xml',
    ],
}


def get_default_library_path() -> Optional[Path]:
    """
    Find the iTunes/Music library XML on this computer.

    Checks the well-known default locations for Windows, macOS, and Linux.
    Returns the path if found, or None if not found.
    """
    system = platform.system()
    paths = DEFAULT_LIBRARY_PATHS.get(system, [])
    for p in paths:
        resolved = p.expanduser().resolve()
        if resolved.exists():
            return resolved
    return None


def read_library(path: Optional[str] = None) -> list[Track]:
    """
    Parse an iTunes Music Library XML and return every track as a Track object.

    If no path is given, tries to find the library automatically.
    Each entry in the XML's 'Tracks' dictionary becomes one Track object.

    Raises FileNotFoundError if the library file can't be located.
    Raises ValueError if the file isn't a valid iTunes library XML.
    """
    if path:
        lib_path = Path(path).expanduser().resolve()
    else:
        detected = get_default_library_path()
        if detected:
            lib_path = detected
        else:
            raise FileNotFoundError(
                "iTunes Music Library.xml not found. "
                "Specify --library-path or place the file in a standard location."
            )

    if not lib_path.exists():
        raise FileNotFoundError(f"Library file not found: {lib_path}")

    try:
        with open(lib_path, 'rb') as f:
            plist = plistlib.load(f)
    except Exception as e:
        raise ValueError(f"Failed to parse library XML: {e}")

    tracks_dict = plist.get('Tracks', {})
    if not isinstance(tracks_dict, dict):
        raise ValueError("Library XML has no 'Tracks' key or it's not a dict")

    # Convert each raw dictionary entry into a typed Track object
    tracks = []
    for track_id_str, track_dict in tracks_dict.items():
        try:
            track_id = int(track_id_str)
        except (ValueError, TypeError):
            continue

        track = Track(
            track_id=track_id,
            name=str(track_dict.get('Name', '') or ''),
            artist=str(track_dict.get('Artist', '') or ''),
            album=str(track_dict.get('Album', '') or ''),
            album_artist=str(track_dict.get('Album Artist', '') or ''),
            persistent_id=str(track_dict.get('Persistent ID', '') or ''),
            track_type=track_dict.get('Track Type'),
            location=track_dict.get('Location'),
            file_folder_count=track_dict.get('File Folder Count'),
            library_folder_count=track_dict.get('Library Folder Count'),
        )
        tracks.append(track)

    return tracks


def backup_file(path: Path) -> Path:
    """
    Create a timestamped copy of a file before modifying it.

    For example, 'iTunes Music Library.xml' becomes
    'iTunes Music Library_20240315_142500.bak.xml'.
    Returns the path to the backup file.
    """
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_path = path.with_name(f"{path.stem}_{timestamp}.bak{path.suffix}")
    shutil.copy2(path, backup_path)
    return backup_path


def write_library(
    tracks: list[Track],
    output_path: Path,
    template_path: Optional[Path] = None,
    backup: bool = True,
) -> None:
    """
    Write a list of Track objects back to an iTunes Library XML file.

    To avoid losing playlists and other settings, if template_path is given
    we read the original XML first and only replace the 'Tracks' section,
    leaving everything else (playlists, library version, etc.) intact.

    If backup=True and the output file already exists, a timestamped backup
    is created before anything is overwritten.
    """
    if backup and output_path.exists():
        backup_file(output_path)

    # Start from the original plist structure so we preserve playlists etc.,
    # or create a minimal skeleton if no template was provided.
    if template_path:
        with open(template_path, 'rb') as f:
            plist = plistlib.load(f)
    else:
        plist = {
            'Major Version': 1,
            'Minor Version': 1,
            'Application Version': '1.0',
            'Date': '',
            'Tracks': {},
            'Playlists': [],
        }

    # Rebuild the Tracks dictionary from our Track objects
    tracks_dict = {}
    for track in tracks:
        td = {
            'Track ID': track.track_id,
            'Name': track.name,
            'Artist': track.artist,
            'Album': track.album,
            'Album Artist': track.album_artist,
            'Persistent ID': track.persistent_id,
        }
        if track.track_type:
            td['Track Type'] = track.track_type
        if track.location:
            td['Location'] = track.location
        if track.file_folder_count is not None:
            td['File Folder Count'] = track.file_folder_count
        if track.library_folder_count is not None:
            td['Library Folder Count'] = track.library_folder_count
        tracks_dict[str(track.track_id)] = td

    plist['Tracks'] = tracks_dict

    with open(output_path, 'wb') as f:
        plistlib.dump(plist, f)
