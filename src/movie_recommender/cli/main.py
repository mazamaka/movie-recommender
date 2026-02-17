"""CLI interface for movie-recommender."""
import asyncio

import typer
from rich.console import Console

app = typer.Typer(name="movie-recommender", help="Smart movie recommender")
console = Console()


@app.command()
def sync() -> None:
    """Sync watch history from Lampa."""
    from movie_recommender.ingest.lampa_parser import sync_history

    console.print("[bold]Syncing watch history...[/bold]")
    history = asyncio.run(sync_history())
    console.print(f"[green]Synced {len(history)} items[/green]")


@app.command()
def recommend(top_n: int = 10) -> None:
    """Generate movie recommendations."""
    console.print(f"[bold]Generating top {top_n} recommendations...[/bold]")
    console.print("[yellow]Not implemented yet[/yellow]")


@app.command()
def search(query: str, year: int | None = None) -> None:
    """Search torrents for a movie."""
    from movie_recommender.search.aggregator import TorrentAggregator

    console.print(f"[bold]Searching: {query}[/bold]")
    agg = TorrentAggregator()
    results = asyncio.run(agg.search_all(query, year))

    for r in results[:10]:
        console.print(f"  {r.seeders:>4} seeds | {r.quality:>6} | {r.size_gb:>6.1f} GB | {r.title[:80]}")

    if not results:
        console.print("[red]No results found[/red]")


@app.command()
def publish(count: int = 5) -> None:
    """Publish recommendations to Telegram."""
    console.print(f"[bold]Publishing {count} recommendations...[/bold]")
    console.print("[yellow]Not implemented yet[/yellow]")


@app.command()
def run(daemon: bool = False) -> None:
    """Run the full pipeline."""
    if daemon:
        console.print("[bold]Starting daemon mode...[/bold]")
    else:
        console.print("[bold]Running single pipeline cycle...[/bold]")
    console.print("[yellow]Not implemented yet[/yellow]")


if __name__ == "__main__":
    app()
