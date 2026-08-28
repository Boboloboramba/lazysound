"""Reaper .RPP project file parser."""

from __future__ import annotations

from pathlib import Path

from lazysound.daw.base import DAWParser, DAWProject, register_parser


class ReaperParser(DAWParser):
    """Parser for Reaper .RPP project files."""

    @property
    def name(self) -> str:
        return "Reaper"

    @property
    def extensions(self) -> list[str]:
        return [".rpp"]

    def parse(self, path: Path) -> DAWProject | None:
        if not path.exists():
            return None

        project = DAWProject(
            path=path,
            daw_name="Reaper",
            format_name="Reaper Project",
        )

        try:
            content = path.read_text(errors="replace")
        except Exception:
            return None

        tracks: list[str] = []
        markers: list[tuple[float, str]] = []
        regions: list[tuple[float, float, str]] = []
        referenced_files: list[Path] = []
        bpm = 0.0
        sample_rate = 0

        lines = content.split("\n")
        current_section = ""

        for line in lines:
            stripped = line.strip()

            # Tempo
            if stripped.startswith("<TEMPO "):
                try:
                    parts = stripped.split()
                    if len(parts) >= 3:
                        bpm = float(parts[2])
                except (ValueError, IndexError):
                    pass

            # Sample rate
            elif stripped.startswith("<REAPER_CFG "):
                # Sample rate is in the audio config section
                pass

            # Track names
            elif stripped.startswith("<TRACK "):
                current_section = "track"
            elif stripped.startswith("NAME ") and current_section == "track":
                name = stripped[5:].strip().strip('"')
                if name:
                    tracks.append(name)
                current_section = ""

            # Markers
            elif stripped.startswith("<Marker "):
                try:
                    parts = stripped.split()
                    # <Marker id position name
                    if len(parts) >= 4:
                        pos = float(parts[2])
                        name = parts[3].strip('"')
                        markers.append((pos, name))
                except (ValueError, IndexError):
                    pass

            # Regions
            elif stripped.startswith("<Region "):
                try:
                    parts = stripped.split()
                    # <Region id start end name
                    if len(parts) >= 5:
                        start = float(parts[2])
                        end = float(parts[3])
                        name = parts[4].strip('"')
                        regions.append((start, end, name))
                except (ValueError, IndexError):
                    pass

            # Referenced files
            elif stripped.startswith("<SOURCE ") or "FILE " in stripped:
                # Try to extract file paths
                for part in stripped.split():
                    p = Path(part.strip('"'))
                    if p.is_file():
                        referenced_files.append(p)

        project.tracks = tracks
        project.markers = markers
        project.regions = regions
        project.bpm = bpm
        project.sample_rate = sample_rate
        project.referenced_files = referenced_files

        return project


register_parser(ReaperParser())
