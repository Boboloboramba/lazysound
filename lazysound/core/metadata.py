"""Audio metadata reading and writing via mutagen."""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import mutagen
from mutagen.easyid3 import EasyID3
from mutagen.flac import FLAC
from mutagen.id3 import ID3NoHeaderError
from mutagen.mp4 import MP4
from mutagen.mp3 import MP3
from mutagen.aiff import AIFF
from mutagen.wave import WAVE
from mutagen.apev2 import APEv2
from mutagen.oggvorbis import OggVorbis
from mutagen.oggopus import OggOpus
from mutagen.oggflac import OggFLAC

from lazysound.core.scanner import AudioFile


# Standard metadata fields across formats
STANDARD_FIELDS: list[tuple[str, str]] = [
    ("title", "Title"),
    ("artist", "Artist"),
    ("album", "Album"),
    ("albumartist", "Album Artist"),
    ("tracknumber", "Track #"),
    ("discnumber", "Disc #"),
    ("date", "Date"),
    ("genre", "Genre"),
    ("composer", "Composer"),
    ("performer", "Performer"),
    ("copyright", "Copyright"),
    ("encodedby", "Encoded By"),
    ("isrc", "ISRC"),
    ("musicbrainz_trackid", "MusicBrainz ID"),
]

# Technical/readonly fields
TECH_FIELDS: list[tuple[str, str]] = [
    ("duration", "Duration"),
    ("bitrate", "Bitrate"),
    ("sample_rate", "Sample Rate"),
    ("channels", "Channels"),
    ("bits_per_sample", "Bits/Sample"),
    ("format", "Format"),
    ("file_size", "File Size"),
]


@dataclass
class AudioMetadata:
    """Unified metadata representation for any audio format."""

    path: Path
    format_name: str = ""
    writable: bool = True
    tags: dict[str, str] = field(default_factory=dict)
    technical: dict[str, str] = field(default_factory=dict)
    raw_tags: dict[str, list[str]] = field(default_factory=dict)
    error: str | None = None

    @property
    def display_name(self) -> str:
        return self.path.stem

    def get_tag(self, key: str, default: str = "") -> str:
        return self.tags.get(key, default)

    def set_tag(self, key: str, value: str) -> None:
        self.tags[key] = value

    def remove_tag(self, key: str) -> None:
        self.tags.pop(key, None)


def _format_duration(seconds: float) -> str:
    """Format seconds into HH:MM:SS or MM:SS."""
    if seconds < 0:
        return "Unknown"
    total = int(seconds)
    hours = total // 3600
    minutes = (total % 3600) // 60
    secs = total % 60
    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def _format_bitrate(audio: mutagen.FileType) -> str:
    """Extract bitrate from audio file."""
    try:
        if hasattr(audio, "info"):
            br = getattr(audio.info, "bitrate", None)
            if br:
                if br >= 1000:
                    return f"{br / 1000:.0f} kbps"
                return f"{br} bps"
    except Exception:
        pass
    return "Unknown"


def _format_sample_rate(audio: mutagen.FileType) -> str:
    try:
        if hasattr(audio, "info"):
            sr = getattr(audio.info, "sample_rate", None)
            if sr:
                if sr >= 1000:
                    return f"{sr / 1000:.1f} kHz"
                return f"{sr} Hz"
    except Exception:
        pass
    return "Unknown"


def _format_channels(audio: mutagen.FileType) -> str:
    try:
        if hasattr(audio, "info"):
            ch = getattr(audio.info, "channels", None)
            if ch is not None:
                channel_names = {1: "Mono", 2: "Stereo", 6: "5.1", 8: "7.1"}
                return channel_names.get(ch, f"{ch} ch")
    except Exception:
        pass
    return "Unknown"


def _extract_vorbis_tags(audio: mutagen.FileType) -> dict[str, str]:
    """Extract tags from Vorbis Comment (FLAC, Ogg, Opus)."""
    tags: dict[str, str] = {}
    if audio.tags is None:
        return tags
    # VCFLACDict iterates tuples; use keys()
    for key in list(audio.tags.keys()):
        try:
            key_lower = str(key).lower()
            values = audio.tags[key]
            if values:
                tags[key_lower] = values[0] if isinstance(values, list) else str(values)
        except Exception:
            continue
    return tags


def _extract_id3_tags(audio: MP3) -> dict[str, str]:
    """Extract tags from ID3v2 (MP3)."""
    tags: dict[str, str] = {}
    try:
        easy = EasyID3(audio.filename)
        for key in easy:
            vals = easy[key]
            if vals:
                tags[key] = vals[0] if isinstance(vals, list) else str(vals)
    except (ID3NoHeaderError, Exception):
        pass
    # Also try raw ID3 for extra fields
    if audio.tags:
        id3 = audio.tags
        field_map = {
            "TIT2": "title",
            "TPE1": "artist",
            "TALB": "album",
            "TPE2": "albumartist",
            "TRCK": "tracknumber",
            "TPOS": "discnumber",
            "TDRC": "date",
            "TDRL": "date",
            "TYER": "date",
            "TCON": "genre",
            "TCOM": "composer",
            "TPE3": "performer",
            "TCOP": "copyright",
    "TENC": "encodedby",
            "TSRC": "isrc",
            "UFID:http://musicbrainz.org": "musicbrainz_trackid",
        }
        for frame_id, tag_key in field_map.items():
            if tag_key not in tags and frame_id in id3:
                val = id3[frame_id]
                text = val.text[0] if hasattr(val, "text") and val.text else str(val)
                tags[tag_key] = str(text)
    return tags


def _extract_mp4_tags(audio: MP4) -> dict[str, str]:
    """Extract tags from MP4/M4A."""
    tags: dict[str, str] = {}
    if not audio.tags:
        return tags
    atom_map = {
        "\xa9nam": "title",
        "\xa9ART": "artist",
        "\xa9alb": "album",
        "aART": "albumartist",
        "trkn": "tracknumber",
        "disk": "discnumber",
        "\xa9day": "date",
        "\xa9gen": "genre",
        "\xa9wrt": "composer",
        "\xa9too": "encodedby",
        "cprt": "copyright",
        "isrc": "isrc",
    }
    for atom, tag_key in atom_map.items():
        if atom in audio.tags:
            val = audio.tags[atom]
            if isinstance(val, list) and val:
                v = val[0]
                if isinstance(v, tuple):
                    v = f"{v[0]}/{v[1]}" if len(v) > 1 else str(v[0])
                tags[tag_key] = str(v)
            elif val:
                tags[tag_key] = str(val)
    return tags


def _extract_apev2_tags(audio: APEv2) -> dict[str, str]:
    """Extract APEv2 tags."""
    tags: dict[str, str] = {}
    if not audio.tags:
        return tags
    for key in list(audio.tags.keys()):
        try:
            tags[str(key).lower()] = str(audio.tags[key])
        except Exception:
            continue
    return tags


def _extract_id3_or_apev2(audio: mutagen.FileType) -> dict[str, str]:
    """Extract ID3 or APEv2 tags from WAV/AIFF and map to standard keys."""
    tags: dict[str, str] = {}
    if audio.tags is None:
        return tags
    id3_frame_map = {
        "tit2": "title",
        "tpe1": "artist",
        "talb": "album",
        "tpe2": "albumartist",
        "trck": "tracknumber",
        "tpos": "discnumber",
        "tdrc": "date",
        "tdrl": "date",
        "tyer": "date",
        "tcon": "genre",
        "tcom": "composer",
        "tpe3": "performer",
        "tcop": "copyright",
        "tenc": "encodedby",
        "tsrc": "isrc",
    }
    try:
        if hasattr(audio.tags, "getall"):
            for key in list(audio.tags.keys()):
                try:
                    key_low = str(key).lower().strip()
                    std_key = id3_frame_map.get(key_low, key_low)
                    vals = audio.tags.getall(key)
                    if vals:
                        v = vals[0]
                        text = v.text[0] if hasattr(v, "text") and v.text else str(v)
                        tags[std_key] = str(text)
                except Exception:
                    continue
            if tags:
                return tags
    except Exception:
        pass
    for key in list(audio.tags.keys()):
        try:
            k = str(key).lower()
            std = id3_frame_map.get(k, k)
            tags[std] = str(audio.tags[key])
        except Exception:
            continue
    return tags


def read_metadata(audio_file: AudioFile) -> AudioMetadata:
    """Read metadata from an audio file.

    Args:
        audio_file: AudioFile to read metadata from.

    Returns:
        AudioMetadata with tags and technical info populated.
    """
    meta = AudioMetadata(path=audio_file.path, format_name=audio_file.format_name)

    if not audio_file.path.exists():
        meta.error = "File not found"
        return meta

    try:
        audio = mutagen.File(str(audio_file.path), easy=False)
    except Exception as e:
        meta.error = f"Cannot read file: {e}"
        meta.writable = False
        return meta

    if audio is None:
        meta.error = "Unsupported format"
        meta.writable = False
        return meta

    # Technical info
    meta.technical["format"] = audio_file.format_name
    meta.technical["file_size"] = audio_file.size_display
    if hasattr(audio, "info"):
        duration = getattr(audio.info, "length", None)
        if duration is not None:
            meta.technical["duration"] = _format_duration(duration)
        meta.technical["bitrate"] = _format_bitrate(audio)
        meta.technical["sample_rate"] = _format_sample_rate(audio)
        meta.technical["channels"] = _format_channels(audio)
        bps = getattr(audio.info, "bits_per_sample", None)
        if bps:
            meta.technical["bits_per_sample"] = str(bps)

    # Extract tags based on format
    format_type = type(audio)
    try:
        if isinstance(audio, (OggVorbis, OggOpus, OggFLAC, FLAC)):
            meta.tags = _extract_vorbis_tags(audio)
        elif isinstance(audio, MP3):
            meta.tags = _extract_id3_tags(audio)
        elif isinstance(audio, MP4):
            meta.tags = _extract_mp4_tags(audio)
        elif isinstance(audio, APEv2):
            meta.tags = _extract_apev2_tags(audio)
        elif isinstance(audio, (WAVE, AIFF)):
            meta.tags = _extract_id3_or_apev2(audio)
        else:
            # Generic fallback
            if audio.tags:
                for key in list(audio.tags.keys()):
                    try:
                        meta.tags[str(key).lower()] = str(audio.tags[key])
                    except Exception:
                        continue
    except Exception as e:
        meta.error = f"Error reading tags: {e}"

    # Store raw for reference
    meta.raw_tags = {k: [v] for k, v in meta.tags.items()}

    return meta


def write_metadata(meta: AudioMetadata) -> str | None:
    """Write modified metadata back to the file.

    Args:
        meta: AudioMetadata with modified tags.

    Returns:
        Error message if failed, None on success.
    """
    if not meta.writable:
        return "File format is not writable"

    if not meta.path.exists():
        return "File not found"

    try:
        audio = mutagen.File(str(meta.path), easy=False)
    except Exception as e:
        return f"Cannot open file: {e}"

    if audio is None:
        return "Unsupported format"

    format_type = type(audio)

    try:
        if isinstance(audio, (OggVorbis, OggOpus, OggFLAC, FLAC)):
            if audio.tags is None:
                audio.add_tags()
            for key, value in meta.tags.items():
                audio.tags[key] = [value]
            # Remove tags that were deleted
            existing_keys = set(audio.tags.keys())
            new_keys = set(meta.tags.keys())
            for key in existing_keys - new_keys:
                del audio.tags[key]

        elif isinstance(audio, MP3):
            audio.delall("T*")
            audio.delall("TDRC")
            audio.delall("TYER")
            audio.delall("TDRL")
            for tag_key, value in meta.tags.items():
                if tag_key == "title":
                    audio.add("TIT2", encoding=3, text=value)
                elif tag_key == "artist":
                    audio.add("TPE1", encoding=3, text=value)
                elif tag_key == "album":
                    audio.add("TALB", encoding=3, text=value)
                elif tag_key == "albumartist":
                    audio.add("TPE2", encoding=3, text=value)
                elif tag_key == "tracknumber":
                    audio.add("TRCK", encoding=3, text=value)
                elif tag_key == "discnumber":
                    audio.add("TPOS", encoding=3, text=value)
                elif tag_key == "date":
                    audio.add("TDRC", encoding=3, text=value)
                elif tag_key == "genre":
                    audio.add("TCON", encoding=3, text=value)
                elif tag_key == "composer":
                    audio.add("TCOM", encoding=3, text=value)
                elif tag_key == "performer":
                    audio.add("TPE3", encoding=3, text=value)
                elif tag_key == "copyright":
                    audio.add("TCOP", encoding=3, text=value)
                elif tag_key == "encodedby":
                    audio.add("TENC", encoding=3, text=value)
                elif tag_key == "isrc":
                    audio.add("TSRC", encoding=3, text=value)

        elif isinstance(audio, MP4):
            if audio.tags is None:
                audio.tags = {}
            reverse_map = {
                "title": "\xa9nam",
                "artist": "\xa9ART",
                "album": "\xa9alb",
                "albumartist": "aART",
                "tracknumber": "trkn",
                "discnumber": "disk",
                "date": "\xa9day",
                "genre": "\xa9gen",
                "composer": "\xa9wrt",
                "encodedby": "\xa9too",
                "copyright": "cprt",
            }
            for tag_key, value in meta.tags.items():
                atom = reverse_map.get(tag_key)
                if atom:
                    if atom in ("trkn", "disk"):
                        try:
                            parts = value.split("/")
                            num = int(parts[0])
                            total = int(parts[1]) if len(parts) > 1 else 0
                            audio.tags[atom] = [(num, total)]
                        except ValueError:
                            audio.tags[atom] = [(1, 0)]
                    else:
                        audio.tags[atom] = [value]
            # Remove deleted
            existing_atoms = set(audio.tags.keys())
            new_atoms = {reverse_map[k] for k in meta.tags if k in reverse_map}
            for atom in existing_atoms - new_atoms:
                if atom in reverse_map.values():
                    del audio.tags[atom]

        elif isinstance(audio, APEv2):
            if audio.tags is None:
                audio.add_tags()
            for key, value in meta.tags.items():
                audio.tags[key] = value
            existing = set(audio.tags.keys())
            for key in existing - set(meta.tags.keys()):
                del audio.tags[key]

        elif isinstance(audio, (WAVE, AIFF)):
            # WAV/AIFF store ID3 (like MP3) but via audio.tags
            if audio.tags is None:
                audio.add_tags()
            # clear existing text frames
            try:
                for k in list(audio.tags.keys()):
                    if isinstance(k, str) and k.startswith("T"):
                        del audio.tags[k]
            except Exception:
                pass
            # map standard keys to ID3 frames (same as MP3)
            id3_map = {
                "title": ("TIT2", 3),
                "artist": ("TPE1", 3),
                "album": ("TALB", 3),
                "albumartist": ("TPE2", 3),
                "tracknumber": ("TRCK", 3),
                "discnumber": ("TPOS", 3),
                "date": ("TDRC", 3),
                "genre": ("TCON", 3),
                "composer": ("TCOM", 3),
                "performer": ("TPE3", 3),
                "copyright": ("TCOP", 3),
                "encodedby": ("TENC", 3),
                "isrc": ("TSRC", 3),
            }
            # choose add target: MP3 uses audio.add, AIFF/WAVE use audio.tags.add
            def _add_frame(frame_id: str, encoding: int, text: str) -> None:
                # try audio.add first (MP3), then audio.tags.add (AIFF/WAVE)
                for target in (audio, getattr(audio, "tags", None)):
                    if target is not None and hasattr(target, "add"):
                        try:
                            target.add(frame_id, encoding=encoding, text=text)  # type: ignore
                            return
                        except TypeError:
                            # some add signatures differ
                            try:
                                from mutagen.id3 import TIT2, TPE1, TALB  # noqa

                                # fallback via explicit frame class
                                pass
                            except Exception:
                                pass
                        except Exception:
                            continue
                # fallback: direct dict assignment with Frame object
                try:
                    from mutagen.id3 import TIT2, TPE1, TALB, TPE2, TRCK, TPOS, TDRC, TCON, TCOM, TPE3, TCOP, TENC, TSRC, TXXX

                    frame_cls = {
                        "TIT2": TIT2,
                        "TPE1": TPE1,
                        "TALB": TALB,
                        "TPE2": TPE2,
                        "TRCK": TRCK,
                        "TPOS": TPOS,
                        "TDRC": TDRC,
                        "TCON": TCON,
                        "TCOM": TCOM,
                        "TPE3": TPE3,
                        "TCOP": TCOP,
                        "TENC": TENC,
                        "TSRC": TSRC,
                    }.get(frame_id)
                    if frame_cls:
                        audio.tags[frame_id] = frame_cls(encoding=encoding, text=text)
                    else:
                        audio.tags[frame_id] = text  # type: ignore
                except Exception:
                    pass

            def _add_txxx(desc: str, text: str) -> None:
                try:
                    from mutagen.id3 import TXXX

                    frame = TXXX(encoding=3, desc=desc, text=text)
                    # AIFF/WAVE use tags.add
                    if hasattr(audio.tags, "add"):
                        audio.tags.add(frame)  # type: ignore
                    elif hasattr(audio, "add"):
                        audio.add(frame)  # type: ignore
                    else:
                        audio.tags["TXXX:" + desc] = frame  # type: ignore
                except Exception:
                    pass

            for tag_key, value in meta.tags.items():
                frame_id_enc = id3_map.get(tag_key)
                if frame_id_enc:
                    frame_id, enc = frame_id_enc
                    try:
                        _add_frame(frame_id, enc, value)
                    except Exception:
                        _add_txxx(tag_key, value)
                else:
                    _add_txxx(tag_key, value)

        else:
            return f"Writing not supported for format: {type(audio).__name__}"

        audio.save()
        return None

    except Exception as e:
        return f"Error writing metadata: {e}"
