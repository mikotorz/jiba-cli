"""
The command-line interface entry point.

This file defines all the commands you can type at the terminal:
  jiba scan     — detect romanized/translated tracks in your library
  jiba apply    — write the corrections a scan found back to the library
  jiba rollback — undo the last apply by restoring a backup
  jiba reverse  — detect japanized tracks and look up the original English titles
  jiba detect   — quick one-off test: classify a single title

Built with Click (a library for building CLI tools) and Rich (for the colored
tables and progress bars you see in the terminal). Each command is a Python
function decorated with @cli.command() — that's how Click knows to expose it
as a subcommand.
"""
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn
from rich.panel import Panel

from .library import read_library, get_default_library_path, backup_file
from .models import Correction, Classification
from .detector import analyze_title

console = Console()


@click.group()
def cli():
    """jiba-cli — Restore original language titles in Apple Music/iTunes."""
    pass


def _resolve_library(library_path: str | None) -> Path:
    """Resolve library path from argument or auto-detection."""
    if library_path:
        p = Path(library_path).expanduser().resolve()
        if not p.exists():
            raise click.UsageError(f"Library file not found: {p}")
        return p
    detected = get_default_library_path()
    if detected:
        return detected
    raise click.UsageError(
        "iTunes Music Library.xml not found. "
        "Use --library-path to specify its location."
    )


@cli.command()
@click.option('--library-path', '-l', default=None,
              help='Path to iTunes Music Library.xml (auto-detects default)')
@click.option('--dry-run', '-n', is_flag=True, default=False,
              help='Scan only, do not write changes')
@click.option('--auto-write', '-w', is_flag=True, default=False,
              help='Write changes automatically without review')
@click.option('--target-languages', '-t', default='ja,zh,ko',
              help='Comma-separated target language codes (default: ja,zh,ko)')
@click.option('--output', '-o', default=None,
              help='Output corrections JSON file path')
@click.option('--verbose', '-v', is_flag=True, default=False,
              help='Show detailed per-track analysis')
@click.option('--match', '-m', is_flag=True, default=False,
              help='Also look up original titles via MusicBrainz/iTunes')
def scan(library_path, dry_run, auto_write, target_languages, output, verbose, match):
    """Scan library and propose language title corrections."""
    lib_path = _resolve_library(library_path)

    with console.status("[bold green]Reading library...", spinner="dots"):
        tracks = read_library(str(lib_path))

    target_langs = [l.strip() for l in target_languages.split(',')]

    console.print(Panel(
        f"[bold]Library:[/] {lib_path}\n"
        f"[bold]Tracks:[/] {len(tracks)}\n"
        f"[bold]Target:[/] {', '.join(target_langs)}\n"
        f"[bold]Mode:[/] {'[yellow]dry-run[/]' if dry_run else '[green]live[/]'}",
        title="jiba scan"
    ))

    # Analyze all tracks
    classifications = {}
    cjk_count = 0
    romanized_count = 0

    with Progress() as progress:
        task = progress.add_task("[cyan]Analyzing tracks...", total=len(tracks))
        for t in tracks:
            result = analyze_title(t.name, t.artist)
            classifications[t.track_id] = result
            if result.classification == Classification.ORIGINAL:
                cjk_count += 1
            if result.is_romanized_candidate:
                romanized_count += 1
            progress.update(task, advance=1)

    # Summary table
    stats_table = Table(title="Scan Summary")
    stats_table.add_column("Metric", style="cyan")
    stats_table.add_column("Count", style="bold")
    stats_table.add_row("Total tracks", str(len(tracks)))
    stats_table.add_row("Already in original script", str(cjk_count))
    stats_table.add_row("Potentially romanized/translated", str(romanized_count))
    stats_table.add_row("Skipped (unknown/non-target)", str(
        len(tracks) - cjk_count - romanized_count
    ))
    console.print(stats_table)

    # Candidates table
    romanized_tracks = [t for t in tracks if classifications[t.track_id].is_romanized_candidate]
    if romanized_tracks:
        detail_table = Table(title="Romanized/Translated Candidates")
        detail_table.add_column("ID", style="dim", width=6)
        detail_table.add_column("Title", style="yellow")
        detail_table.add_column("Artist")
        detail_table.add_column("Lang")
        detail_table.add_column("Confidence")

        for t in romanized_tracks:
            r = classifications[t.track_id]
            detail_table.add_row(
                str(t.track_id),
                t.name[:55],
                t.artist[:40],
                r.language or "?",
                f"{r.confidence:.0%}"
            )
        console.print(detail_table)

    # Run matching if requested
    if match and romanized_tracks:
        console.print("\n[bold]Looking up original titles...[/]")
        from .orchestrator import match_tracks, save_corrections

        corrections = match_tracks(
            romanized_tracks,
            target_langs=target_langs,
            progress_callback=None,
        )

        if corrections:
            match_table = Table(title=f"Found {len(corrections)} Corrections")
            match_table.add_column("Track", style="yellow")
            match_table.add_column("Field")
            match_table.add_column("Original → Corrected")
            match_table.add_column("Source")
            match_table.add_column("Confidence")

            track_map = {t.track_id: t for t in tracks}
            for c in corrections:
                track = track_map.get(c.track_id)
                track_name = track.name if track else f"ID {c.track_id}"
                match_table.add_row(
                    track_name[:30],
                    c.field,
                    f"{c.original_value[:25]} → [green]{c.corrected_value[:25]}[/]",
                    c.source,
                    f"{c.confidence:.0%}"
                )
            console.print(match_table)

            # Save to JSON if output specified
            if output:
                save_corrections(corrections, Path(output))
                console.print(f"[green]✓[/] Corrections saved to [cyan]{output}[/]")

            if not dry_run and auto_write:
                console.print("[yellow]Auto-write not yet implemented. Use: jiba apply[/]")
        else:
            console.print("[yellow]No corrections found via MusicBrainz/iTunes.[/]")

    elif not match and romanized_tracks:
        console.print(
            "\n[bold]Next:[/] Run [cyan]jiba scan --match[/] or [cyan]jiba match[/] "
            "to look up original titles via MusicBrainz"
        )


@cli.command()
@click.option('--corrections', '-c', required=True,
              help='Path to corrections JSON file from jiba scan')
@click.option('--library-path', '-l', default=None,
              help='Path to iTunes Music Library.xml (auto-detects default)')
@click.option('--dry-run', '-n', is_flag=True, default=False,
              help='Preview changes without writing')
def apply(corrections, library_path, dry_run):
    """Apply corrections to the iTunes library."""
    from .orchestrator import load_corrections
    from .library import write_library

    # Load corrections
    corr_path = Path(corrections)
    if not corr_path.exists():
        raise click.UsageError(f"Corrections file not found: {corr_path}")

    corrections_list = load_corrections(corr_path)
    if not corrections_list:
        console.print("[yellow]No corrections to apply.[/]")
        return

    # Load library
    lib_path = _resolve_library(library_path)
    tracks = read_library(str(lib_path))
    track_map = {t.track_id: t for t in tracks}

    # Preview changes
    apply_table = Table(title=f"Applying {len(corrections_list)} Corrections")
    apply_table.add_column("Track", style="yellow")
    apply_table.add_column("Field")
    apply_table.add_column("From")
    apply_table.add_column("→ To")
    apply_table.add_column("Confidence")

    for c in corrections_list:
        track = track_map.get(c.track_id)
        track_name = track.name if track else f"ID {c.track_id}"
        apply_table.add_row(
            track_name[:30],
            c.field,
            c.original_value[:25],
            f"[green]{c.corrected_value[:25]}[/]",
            f"{c.confidence:.0%}"
        )
    console.print(apply_table)

    if dry_run:
        console.print("[yellow]Dry-run mode — no changes written.[/]")
        return

    # Apply corrections
    modified_count = 0
    for c in corrections_list:
        track = track_map.get(c.track_id)
        if not track:
            continue
        if c.field == "name":
            track.name = c.corrected_value
        elif c.field == "artist":
            track.artist = c.corrected_value
        elif c.field == "album":
            track.album = c.corrected_value
        elif c.field == "album_artist":
            track.album_artist = c.corrected_value
        modified_count += 1

    # Write back
    if click.confirm(f"Write {modified_count} changes to library? (backup will be created)"):
        backup_path = backup_file(lib_path)
        write_library(tracks, lib_path, template_path=lib_path, backup=False)
        console.print(f"[green]✓[/] {modified_count} corrections written.")
        console.print(f"[dim]Backup: {backup_path}[/]")
    else:
        console.print("[yellow]Cancelled.[/]")


@cli.command()
@click.option('--library-path', '-l', default=None,
              help='Path to iTunes Music Library.xml')
def rollback(library_path):
    """Restore library from most recent backup."""
    lib_path = _resolve_library(library_path)
    backup_dir = lib_path.parent
    backups = sorted(backup_dir.glob(f"{lib_path.stem}_*.bak{lib_path.suffix}"))

    if not backups:
        console.print("[red]No backups found.[/]")
        return

    latest = backups[-1]
    console.print(f"Found backup: [cyan]{latest.name}[/] ({latest.stat().st_size / 1024:.0f} KB)")

    if click.confirm(f"Restore {lib_path.name} from this backup?"):
        import shutil
        shutil.copy2(latest, lib_path)
        console.print(f"[green]✓[/] Restored from {latest.name}")


@cli.command()
@click.argument('title')
@click.argument('artist', default='')
def detect(title, artist):
    """Detect if a track title is romanized/translated."""
    result = analyze_title(title, artist)
    console.print(Panel(
        f"[bold]Title:[/] {title}\n"
        f"[bold]Artist:[/] {artist or '(none)'}\n"
        f"[bold]Classification:[/] [yellow]{result.classification.name}[/]\n"
        f"[bold]Language:[/] {result.language or 'unknown'}\n"
        f"[bold]Confidence:[/] {result.confidence:.0%}\n"
        f"[bold]Has CJK:[/] {'[green]Yes[/]' if result.has_cjk else '[red]No[/]'}\n"
        f"[bold]Romanized:[/] {'[green]Yes[/]' if result.is_romanized_candidate else '[red]No[/]'}\n"
        f"[bold]Japanized:[/] {'[green]Yes[/]' if result.is_japanized_candidate else '[red]No[/]'}",
        title="Language Analysis"
    ))


@cli.command()
@click.option('--library-path', '-l', default=None,
              help='Path to iTunes Music Library.xml (auto-detects default)')
@click.option('--dry-run', '-n', is_flag=True, default=False,
              help='Scan only, do not write changes')
@click.option('--auto-write', '-w', is_flag=True, default=False,
              help='Write changes automatically without review')
@click.option('--output', '-o', default=None,
              help='Output corrections JSON file path')
@click.option('--verbose', '-v', is_flag=True, default=False,
              help='Show detailed per-track analysis')
@click.option('--match', '-m', is_flag=True, default=False,
              help='Look up original English titles via MusicBrainz/iTunes')
def reverse(library_path, dry_run, auto_write, output, verbose, match):
    """Restore original (English) titles for Japanized tracks.

    Apple Music sometimes auto-converts Western song titles to Japanese
    (katakana/kanji). This command detects those tracks and restores
    the original English names.
    """
    lib_path = _resolve_library(library_path)

    with console.status("[bold green]Reading library...", spinner="dots"):
        tracks = read_library(str(lib_path))

    console.print(Panel(
        f"[bold]Library:[/] {lib_path}\n"
        f"[bold]Tracks:[/] {len(tracks)}\n"
        f"[bold]Mode:[/] {'[yellow]reverse (JP→EN)[/]'}\n"
        f"[bold]Write:[/] {'[yellow]dry-run[/]' if dry_run else '[green]live[/]'}",
        title="jiba reverse"
    ))

    # Analyze all tracks
    classifications = {}
    total_original = 0
    japanized_count = 0

    with Progress() as progress:
        task = progress.add_task("[cyan]Analyzing tracks...", total=len(tracks))
        for t in tracks:
            result = analyze_title(t.name, t.artist)
            classifications[t.track_id] = result
            if result.classification == Classification.ORIGINAL:
                total_original += 1
            if result.is_japanized_candidate:
                japanized_count += 1
            progress.update(task, advance=1)

    # Summary table
    stats_table = Table(title="Reverse Scan Summary")
    stats_table.add_column("Metric", style="cyan")
    stats_table.add_column("Count", style="bold")
    stats_table.add_row("Total tracks", str(len(tracks)))
    stats_table.add_row("Original script tracks", str(total_original))
    stats_table.add_row("Japanized candidates (JP→EN needed)", str(japanized_count))
    stats_table.add_row("Skipped (romanized/unknown)", str(
        len(tracks) - total_original - japanized_count
    ))
    console.print(stats_table)

    # Candidates table
    japanized_tracks = [t for t in tracks if classifications[t.track_id].is_japanized_candidate]
    if japanized_tracks:
        detail_table = Table(title="Japanized Track Candidates")
        detail_table.add_column("ID", style="dim", width=6)
        detail_table.add_column("Title", style="yellow")
        detail_table.add_column("Artist")
        detail_table.add_column("Confidence")

        for t in japanized_tracks:
            r = classifications[t.track_id]
            detail_table.add_row(
                str(t.track_id),
                t.name[:55],
                t.artist[:40],
                f"{r.confidence:.0%}"
            )
        console.print(detail_table)

        if verbose:
            for t in japanized_tracks:
                r = classifications[t.track_id]
                console.print(f"  [dim]#{t.track_id}[/] [yellow]{t.name}[/] by [cyan]{t.artist}[/]")

    # Run reverse matching if requested
    if match and japanized_tracks:
        console.print("\n[bold]Looking up original English titles...[/]")
        from .orchestrator import reverse_tracks, save_corrections

        corrections = reverse_tracks(
            japanized_tracks,
            progress_callback=None,
        )

        if corrections:
            match_table = Table(title=f"Found {len(corrections)} Reversed Corrections")
            match_table.add_column("Track", style="yellow")
            match_table.add_column("Japanized → Original")
            match_table.add_column("Source")
            match_table.add_column("Confidence")

            track_map = {t.track_id: t for t in tracks}
            for c in corrections:
                track = track_map.get(c.track_id)
                track_name = track.name if track else f"ID {c.track_id}"
                match_table.add_row(
                    track_name[:30],
                    f"{c.original_value[:25]} → [green]{c.corrected_value[:25]}[/]",
                    c.source,
                    f"{c.confidence:.0%}"
                )
            console.print(match_table)

            # Save to JSON if output specified
            if output:
                save_corrections(corrections, Path(output))
                console.print(f"[green]✓[/] Corrections saved to [cyan]{output}[/]")

            if not dry_run and auto_write:
                console.print("[yellow]Auto-write not yet implemented. Use: jiba apply[/]")
        else:
            console.print("[yellow]No English titles found via MusicBrainz/iTunes.[/]")

    elif not match and japanized_tracks:
        console.print(
            "\n[bold]Next:[/] Run [cyan]jiba reverse --match[/] "
            "to look up original English titles via MusicBrainz/iTunes"
        )

    if not japanized_tracks:
        console.print("[green]No Japanized tracks found — all clear![/]")
