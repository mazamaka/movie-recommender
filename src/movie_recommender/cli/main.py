"""CLI interface for movie-recommender."""
import asyncio

import typer
from rich.console import Console

app = typer.Typer(name="movie-recommender", help="Smart movie recommender")
console = Console()


@app.command()
def sync() -> None:
    """Sync watch history from Lampa."""
    import httpx

    console.print("[bold]Checking sync status...[/bold]")
    try:
        resp = httpx.get("http://localhost:9000/api/v1/sync/health", timeout=5)
        data = resp.json()
        console.print(f"[green]History: {data.get('history_count', 0)} items[/green]")
        for k, v in data.get("bookmarks", {}).items():
            console.print(f"  {k}: {v} items")
    except Exception as e:
        console.print(f"[red]Sync server not available: {e}[/red]")


@app.command()
def recommend(top_n: int = 5) -> None:
    """Generate and publish movie recommendations."""
    from movie_recommender.pipeline.runner import run_pipeline

    console.print(f"[bold]Running recommendation pipeline (top {top_n})...[/bold]")
    results = asyncio.run(run_pipeline(top_n))
    console.print(f"[green]Published {len(results)} recommendations[/green]")
    for r in results:
        m = r["movie"]
        t = r["torrent"]
        console.print(
            f"  {r['score']:.0%} | {m.get('title_ru', '?')} ({m.get('year', '?')}) "
            f"| {t.get('quality', '?')} | {t.get('seeders', 0)} seeds"
        )


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
def serve(host: str = "0.0.0.0", port: int = 9000) -> None:
    """Start the API server."""
    import uvicorn

    console.print(f"[bold]Starting server on {host}:{port}...[/bold]")
    uvicorn.run("movie_recommender.app:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    app()
