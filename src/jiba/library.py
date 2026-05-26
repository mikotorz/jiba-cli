"""Read and write iTunes Music Library XML files."""
import plistlib
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional
import platform

from .models import Track


# Well-known library paths per platform
DEFAULT_LIBRARY_PATHS = {
    'Windows': [
        Path.home() / 'Music' / 'iTunes' / 'iTunes Music Library.xml',
    ],
    'Darwin': [
        Path.home() / 'Music' / 'Music' / 'Music Library.xml',       # macOS 10.15+ Music.app
        Path.home() / 'Music' / 'iTunes' / 'iTunes Music Library.xml',  # Legacy iTunes
    ],
    'Linux': [
        Path.home() / '.wine' / 'drive_c' / 'Program Files (x86)' / 'iTunes' / 'iTunes Music Library.xml',
    ],
}


def get_default_library_path() -> Optional[Path]:
    """Return the default iTunes Music Library.xml path for the current OS."""
    system = platform.system()
    paths = DEFAULT_LIBRARY_PATHS.get(system, [])
    for p in paths:
        resolved = p.expanduser().resolve()
        if resolved.exists():
            return resolved
    return None


def read_library(path: Optional[str] = None) -> list[Track]:
    """Parse an iTunes Music Library XML and return all tracks.

    Args:
        path: Path to the library XML. If None, auto-detects.

    Returns:
        List of Track objects.

    Raises:
        FileNotFoundError: If library file can't be found.
        ValueError: If file isn't a valid iTunes library XML.
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
    """Create a timestamped backup of a file.

    Args:
        path: Path to the file to back up.

    Returns:
        Path to the backup file.
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
    """Write tracks back to an iTunes Library XML, preserving original structure.

    If template_path is given, reads the original plist and updates only
    the Tracks dictionary, preserving playlists and other metadata.
    If backup is True and the output file already exists, creates a timestamped
    backup before overwriting.

    Args:
        tracks: List of tracks to write.
        output_path: Path for the output XML.
        template_path: Optional path to original XML for structure preservation.
        backup: Whether to create a backup if the output file exists.
    """
    if backup and output_path.exists():
        backup_file(output_path)

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
