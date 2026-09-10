import os
import yaml
from pathlib import Path
import typer
from rich.console import Console
from rich.table import Table
from rich.prompt import Confirm
from typing import Optional

from ..database.db import init_db, register_dataset, log_file, update_file_status, save_checksums, get_dataset_by_name
from ..downloaders import get_downloader
from ..utils.disk import get_free_space, format_bytes, check_space_available
from ..utils.manifest import create_manifest
from ..validators.checksum import calculate_checksums
from ..extractors.archive import extract_archive

app = typer.Typer(help="Dataset Manager for Japanese NLP Datasets")
console = Console()

CONFIG_PATH = Path("config/datasets.yaml")
DATA_DIR = Path("data")
RAW_DIR = DATA_DIR / "raw"
EXTRACT_DIR = DATA_DIR / "extracted"

def load_config():
    if not CONFIG_PATH.exists():
        console.print(f"[red]Config file not found at {CONFIG_PATH}[/red]")
        raise typer.Exit(1)
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

@app.command()
def init():
    """Initialize the database and directories"""
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    EXTRACT_DIR.mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "metadata").mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "licenses").mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "logs").mkdir(parents=True, exist_ok=True)
    init_db()
    
    config = load_config()
    for ds in config.get('datasets', []):
        register_dataset(ds['name'], ds)
    console.print("[green]Initialization complete.[/green]")

@app.command()
def list_datasets(all: bool = False):
    """List enabled datasets"""
    config = load_config()
    table = Table(title="Datasets")
    table.add_column("Name", style="cyan")
    table.add_column("Source", style="magenta")
    table.add_column("Enabled", style="green")
    table.add_column("Priority", justify="right")
    table.add_column("Est. Size (MB)", justify="right")

    for ds in config.get('datasets', []):
        if all or ds.get('enabled', False):
            enabled_str = "[green]Yes[/green]" if ds.get('enabled') else "[red]No[/red]"
            table.add_row(
                ds['name'],
                ds.get('source', ''),
                enabled_str,
                str(ds.get('priority', 0)),
                str(ds.get('estimated_size_mb', 0))
            )
    console.print(table)

@app.command()
def download_next():
    """Downloads the next enabled dataset according to priority."""
    config = load_config()
    datasets = config.get('datasets', [])
    # Filter enabled
    enabled_ds = [ds for ds in datasets if ds.get('enabled', False)]
    # Sort by priority
    enabled_ds.sort(key=lambda x: x.get('priority', 999))
    
    if not enabled_ds:
        console.print("[yellow]No enabled datasets found.[/yellow]")
        raise typer.Exit()
        
    for ds_config in enabled_ds:
        name = ds_config['name']
        row = get_dataset_by_name(name)
        if not row:
            console.print(f"[yellow]Dataset {name} not found in DB. Run 'init' first.[/yellow]")
            continue
            
        # Check if already fully processed
        ds_raw_dir = RAW_DIR / name
        manifest_path = ds_raw_dir / "manifest.json"
        
        if manifest_path.exists():
            console.print(f"[blue]Skipping {name}, already fully processed.[/blue]")
            continue
            
        # Check if downloaded but not processed (e.g. manual drop)
        if ds_raw_dir.exists() and any(f.is_file() for f in ds_raw_dir.iterdir() if f.name != 'manifest.json'):
            console.print(f"[blue]Found existing files for {name}, processing without downloading...[/blue]")
            _do_download(ds_config, row['id'], skip_download=True)
        else:
            # We found the next one to download
            console.print(f"\\n[bold cyan]Next dataset to download: {name}[/bold cyan]")
            _do_download(ds_config, row['id'])
        
        console.print(f"\\n[bold green]Dataset {name} processed successfully.[/bold green]")
        break

def _do_download(ds_config, db_id, skip_download=False):
    name = ds_config['name']
    downloader_name = ds_config.get('downloader')
    downloader = get_downloader(downloader_name)
    
    if not downloader:
        console.print(f"[red]Downloader '{downloader_name}' not found.[/red]")
        raise typer.Exit(1)
        
    ds_raw_dir = RAW_DIR / name
    
    if not skip_download:
        est_size = downloader.get_estimated_size(ds_config)
        free_space = get_free_space(RAW_DIR)
        
        console.print(f"Estimated size: {format_bytes(est_size)}")
        console.print(f"Free space: {format_bytes(free_space)}")
        
        # We multiply by 2.5 to account for both download and extraction space roughly
        if not check_space_available(est_size * 2.5, RAW_DIR):
            console.print("[bold red]Insufficient disk space to download and extract![/bold red]")
            raise typer.Exit(1)
            
        ds_raw_dir.mkdir(parents=True, exist_ok=True)
    
    # Register file in DB
    file_id = log_file(db_id, name, str(ds_raw_dir), original_url=ds_config.get('dataset_id') or ds_config.get('url'))
    update_file_status(file_id, 'downloading')
    
    if not skip_download:
        # Download
        success = downloader.download(ds_config, ds_raw_dir)
        
        from ..database.db import log_provenance
        log_provenance(db_id, ds_config.get('license', 'Unknown'), ds_config.get('url', ''), success)
        
        if not success:
            update_file_status(file_id, 'error')
            console.print("[red]Download failed![/red]")
            raise typer.Exit(1)
            
    update_file_status(file_id, 'downloaded')
    
    # Validation
    console.print("[cyan]Calculating checksums...[/cyan]")
    total_size = 0
    # For HF, it downloads multiple files, we should probably checksum all or the main ones
    # Simplified: we pick the first non-hidden file for checksum or just total size
    # In a real scenario we might loop over all files
    ds_files = [f for f in ds_raw_dir.rglob('*') if f.is_file() and not f.name.startswith('.')]
    
    extracted_count = 0
    extraction_status = 'pending'
    if ds_config.get('extract', False):
        console.print("[cyan]Extracting files...[/cyan]")
        ds_extract_dir = EXTRACT_DIR / name
        ds_extract_dir.mkdir(parents=True, exist_ok=True)
        extraction_success = True
        
        for f in ds_files:
            if not extract_archive(f, ds_extract_dir):
                # not an archive or failed, but might be normal data file
                pass
            
        extracted_files = [f for f in ds_extract_dir.rglob('*') if f.is_file()]
        extracted_count = len(extracted_files)
        extraction_status = 'completed' if extracted_count > 0 else 'failed/none'
        console.print(f"[green]Extracted {extracted_count} files.[/green]")

    # Create manifest
    file_metadata = {
        "filename": name,
        "sha256": "multi-file" if len(ds_files) > 1 else "tbd",
        "md5": "multi-file" if len(ds_files) > 1 else "tbd",
        "size": sum(f.stat().st_size for f in ds_files),
        "extraction_status": extraction_status,
        "extracted_files_count": extracted_count,
        "sqlite_id": db_id
    }
    
    if len(ds_files) == 1:
        sha256, md5, size = calculate_checksums(ds_files[0])
        file_metadata['sha256'] = sha256
        file_metadata['md5'] = md5
        file_metadata['size'] = size
        save_checksums(file_id, sha256, md5)
        
    create_manifest(ds_config, file_metadata, ds_raw_dir)
    update_file_status(file_id, 'completed', file_metadata['size'])
    console.print("[green]Manifest generated and database updated.[/green]")

@app.command()
def transform():
    """Run data transformation pipeline into Phase 2 schema"""
    from ..database.db import get_db_connection
    from ..transformers.usda import USDAFoodKeeperTransformer
    from ..transformers.usda_fdc import USDAFDCTransformer
    from ..transformers.openfoodfacts import OpenFoodFactsTransformer
    from ..transformers.mext import MEXTTransformer
    from ..transformers.llm import LLMMarkdownTransformer
    from ..transformers.maff_cuisines import MAFFCuisinesTransformer
    from ..transformers.wikipedia import WikipediaTransformer
    from ..transformers.wikidata import WikidataTransformer
    
    config = load_config()
    datasets = config.get('datasets', [])
    enabled_ds = [ds for ds in datasets if ds.get('enabled', False)]
    
    if not enabled_ds:
        console.print("[yellow]No enabled datasets found to transform.[/yellow]")
        raise typer.Exit()
        
    conn = get_db_connection()
    
    for ds_config in enabled_ds:
        name = ds_config['name']
        ds_raw_dir = RAW_DIR / name
        ds_extract_dir = EXTRACT_DIR / name
        manifest_path = ds_raw_dir / "manifest.json"
        
        if not manifest_path.exists() and not (ds_raw_dir.exists() and any(ds_raw_dir.iterdir())):
            console.print(f"[yellow]Skipping {name}: not processed yet.[/yellow]")
            continue
            
        console.print(f"\n[bold cyan]Transforming dataset: {name}[/bold cyan]")
        
        # Dispatch to the correct transformer based on dataset name
        if name == "usda_foodkeeper":
            transformer = USDAFoodKeeperTransformer(conn)
            raw_paths = [f for f in ds_raw_dir.glob("*.xlsx")]
            if raw_paths:
                transformer.transform(ds_config, raw_paths[0])
                
        elif name == "usda_fooddata_central":
            transformer = USDAFDCTransformer(conn)
            if ds_extract_dir.exists():
                transformer.transform(ds_config, ds_extract_dir)
            else:
                transformer.transform(ds_config, ds_raw_dir)
                
        elif name == "openfoodfacts":
            transformer = OpenFoodFactsTransformer(conn)
            if ds_raw_dir.exists():
                transformer.transform(ds_config, ds_raw_dir)
                
        elif name == "mext_food_composition_2023":
            transformer = MEXTTransformer(conn)
            raw_paths = [f for f in ds_raw_dir.glob("*.xlsx")]
            if raw_paths:
                transformer.transform(ds_config, raw_paths[0])
                
        elif name in ["caa_food_labeling_standards", "maff_refrigerator_guide", "tokyo_nerima_food_labeling", "fda_food_code"]:
            transformer = LLMMarkdownTransformer(conn)
            raw_paths = [f for f in ds_raw_dir.glob("*.md")]
            if raw_paths:
                transformer.transform(ds_config, raw_paths[0])

        elif name == "maff_regional_cuisines":
            # Crawls HTML directly (no downloaded file). See run_maff_cuisines.py for phased runs.
            MAFFCuisinesTransformer(conn).transform(ds_config, ds_raw_dir)
                
        elif name == "wikipedia_ja_food":
            transformer = WikipediaTransformer(conn)
            if ds_raw_dir.exists():
                transformer.transform(ds_config, ds_raw_dir)
                
        elif name == "wikidata_japan_foods":
            transformer = WikidataTransformer(conn)
            transformer.transform(ds_config, ds_raw_dir)
            
        else:
            console.print(f"[yellow]No transformer logic configured for {name}[/yellow]")
            
    conn.close()
    console.print("\n[bold green]Transformation pipeline complete.[/bold green]")

@app.command()
def serve(port: int = 0):
    """Run the FastAPI REST server."""
    # Hosted platforms hand the port over in $PORT and health-check that port.
    port = port or int(os.environ.get("PORT", 8000))
    import uvicorn
    console.print(f"[bold green]Starting API Server on port {port}...[/bold green]")
    uvicorn.run("dataset_manager.api.server:app", host="0.0.0.0", port=port, reload=False)


# ---- Public-site builders (all idempotent) ----

@app.command("site-init")
def site_init():
    """Create the additive public-site tables (item_names, site_pages, ...)."""
    from . import build_site
    conn = build_site.get_conn()
    from ..database.site_schema import create_site_tables
    create_site_tables(conn)
    conn.close()
    console.print("[green]Site tables ready.[/green]")


@app.command("build-names")
def build_names_cmd(limit: Optional[int] = typer.Option(None, help="Cap LLM translations (testing)")):
    """Populate item_names: JA display names, official FDC EN names + portions, LLM EN translations."""
    from . import build_site
    build_site.build_names(limit=limit)


@app.command("build-pages")
def build_pages_cmd():
    """Generate site_pages slugs + titles + meta descriptions."""
    from . import build_site
    build_site.build_pages()


@app.command("build-links")
def build_links_cmd(
    limit: Optional[int] = typer.Option(None, help="Cap dishes processed (testing)"),
    report: bool = typer.Option(False, help="Print coverage report only"),
    rebuild: bool = typer.Option(False, help="Discard existing links and re-resolve"),
    refresh_aliases: bool = typer.Option(
        False, "--refresh-aliases",
        help="Re-point existing links at the curated vocabulary's current answer"),
    refresh_quantities: bool = typer.Option(
        False, "--refresh-quantities",
        help="Re-parse stored quantity strings with the current parser"),
):
    """Parse MAFF recipe ingredients and resolve them to MEXT items."""
    from . import build_site
    if refresh_aliases:
        build_site.refresh_aliases()
        return
    if refresh_quantities:
        build_site.refresh_quantities()
        return
    build_site.build_links(limit=limit, report=report, rebuild=rebuild)


@app.command("build-search")
def build_search_cmd():
    """Rebuild the FTS5 search index over the clean corpus."""
    from . import build_site
    build_site.build_search()


@app.command("build-ranks")
def build_ranks_cmd():
    """Precompute where each food sits among its own category, per nutrient."""
    from . import build_site
    from .build_ranks import MIN_PEERS, build_nutrient_ranks

    conn = build_site.get_conn()
    try:
        stats = build_nutrient_ranks(conn)
    finally:
        conn.close()
    console.print(
        f"[green]nutrient_ranks[/green]: {stats['ranked']:,} ranks over "
        f"{stats['groups']} category/nutrient groups ({stats['codes']} nutrients); "
        f"{stats['skipped_thin_groups']:,} values sat in groups under {MIN_PEERS} peers")


@app.command("build-sitemaps")
def build_sitemaps_cmd():
    """Write sitemap-en.xml / sitemap-ja.xml under data/sitemaps/."""
    from . import build_site
    build_site.build_sitemaps()


@app.command("import-menus")
def import_menus_cmd(
    csv_path: str = typer.Argument(..., help="The frozen menu CSV to import"),
    imported_at: Optional[str] = typer.Option(
        None, help="Snapshot date shown on every shop page (default: today)"),
):
    """Import the restaurant-menu snapshot into shops / shop_menu_items.

    A dated snapshot, not a feed: scraped descriptions and store photos are not
    imported, and every rejected row is reported rather than repaired.
    """
    from pathlib import Path
    from ..extractors.menus import import_menus
    from . import build_site

    path = Path(csv_path)
    if not path.exists():
        console.print(f"[red]No such file: {path}[/red]")
        raise typer.Exit(1)

    conn = build_site.get_conn()
    try:
        stats = import_menus(conn, path.read_text(encoding="utf-8"), imported_at=imported_at)
    finally:
        conn.close()

    console.print(
        f"[green]Imported {stats['shops']} shops / {stats['items']} items[/green] "
        f"(kept {stats['matches_kept']} existing matches)")
    console.print(
        f"  read {stats['rows']} rows — dropped: blank {stats['blank']}, "
        f"non-food {stats['non_food']}, menu-section rows {stats['section_label']}; "
        f"collapsed {stats['duplicates']} duplicates; {stats['no_price']} rows have no usable price")


@app.command("match-menus")
def match_menus_cmd(
    limit: Optional[int] = typer.Option(None, help="Cap dishes processed (testing)"),
    rebuild: bool = typer.Option(False, help="Discard existing matches and re-resolve"),
    no_llm: bool = typer.Option(False, "--no-llm", help="Deterministic pass only, spend nothing"),
):
    """Resolve menu dishes to composition-table entries (never to a model's number)."""
    from . import build_shops, build_site
    conn = build_site.get_conn()
    try:
        build_shops.match_items(conn, limit=limit, rebuild=rebuild, use_llm=not no_llm)
    finally:
        conn.close()


@app.command("chain-status")
def chain_status_cmd(stale_after: int = typer.Option(30, help="Warn past this many days")):
    """Which chains we hold figures for, and how stale each one is."""
    from ..extractors.chains import CHAINS, chain_status
    from . import build_site

    conn = build_site.get_conn()
    try:
        rows = chain_status(conn)
    finally:
        conn.close()

    if not rows:
        console.print("[yellow]No chain nutrition imported yet.[/yellow]")
        return
    for r in rows:
        age = r["days_since_fetch"]
        tone = "red" if age is not None and age > stale_after else "green"
        console.print(
            f"[{tone}]{r['chain']}[/{tone}]: {r['figures']} figures · "
            f"chain published {r['source_updated'] or '?'} · "
            f"we fetched {r['fetched_at']}"
            + (f" ({age}d ago)" if age is not None else ""))
    missing = [k for k, c in CHAINS.items()
               if c.shop_name not in {r["chain"] for r in rows}]
    if missing:
        console.print(f"[yellow]registered but never imported: {', '.join(missing)}[/yellow]")


@app.command("import-chain-nutrition")
def import_chain_nutrition_cmd(
    chain: str = typer.Argument("all", help="Chain key, or 'all'"),
):
    """Import per-dish calories as published by the chains themselves."""
    from ..extractors.chains import CHAINS, import_chain
    from . import build_site

    keys = list(CHAINS) if chain == "all" else [chain]
    unknown = [k for k in keys if k not in CHAINS]
    if unknown:
        console.print(f"[red]Unknown chain(s): {', '.join(unknown)}. "
                      f"Known: {', '.join(CHAINS)}[/red]")
        raise typer.Exit(1)

    conn = build_site.get_conn()
    try:
        for key in keys:
            stats = import_chain(conn, CHAINS[key])
            console.print(
                f"[green]{stats['chain']}[/green]: {stats['published_rows']} published rows "
                f"(chain updated {stats['source_updated'] or 'unknown'}) -> linked to "
                f"{stats['linked']} of {stats['menu_items']} menu items "
                f"({stats['linked_exact']} by exact name, "
                f"{stats['ambiguous_skipped']} refused as ambiguous)")
            if not stats["was_empty"]:
                # A refresh, not a first import: say what the chain actually moved.
                console.print(
                    f"  changes: {len(stats['added'])} new, {len(stats['removed'])} withdrawn, "
                    f"{len(stats['changed'])} figures revised")
                for name, was, now in stats["changed"][:10]:
                    console.print(f"    {name}: {was:.0f} -> {now:.0f} kcal")
                if len(stats["changed"]) > 10:
                    console.print(f"    ... and {len(stats['changed']) - 10} more")
    finally:
        conn.close()


@app.command("sync-posts")
def sync_posts_cmd(
    url: str = typer.Option(None, "--url", help="WordPress base URL (default: $WP_URL)"),
):
    """Pull blog posts from WordPress into the post store."""
    from ..blog import sync as blog_sync
    try:
        stats = blog_sync.sync(url)
    except Exception as e:
        console.print(f"[bold red]sync failed:[/bold red] {e}")
        raise typer.Exit(1)
    console.print(f"[bold green]fetched {stats['fetched']}, stored {stats['stored']}, "
                  f"removed {stats['removed']}[/bold green]")


@app.command("build-shops")
def build_shops_cmd(report: bool = typer.Option(False, help="Print coverage + gate report only")):
    """Build shop_pages: slugs, titles, and the index gate."""
    from . import build_shops, build_site
    conn = build_site.get_conn()
    try:
        if report:
            build_shops.report(conn)
        else:
            build_shops.build_pages(conn)
    finally:
        conn.close()


@app.command("build-site")
def build_site_cmd():
    """Run all site builders in order: names, pages, links, ranks, search, sitemaps."""
    from . import build_site
    from .build_ranks import build_nutrient_ranks
    build_site.build_names()
    build_site.build_pages()
    build_site.build_links()
    conn = build_site.get_conn()
    try:
        build_nutrient_ranks(conn)
    finally:
        conn.close()
    build_site.build_search()
    build_site.build_sitemaps()


@app.command("precompute-nutrition")
def precompute_nutrition_cmd(
    shop_id: int = typer.Option(None, "--shop-id", "-s", help="Specific shop ID to precompute"),
    limit: int = typer.Option(None, "--limit", "-l", help="Limit number of dishes to process"),
):
    """Precompute and store verified nutritional values for menu items."""
    from . import build_site
    from .precompute_nutrition import precompute_menu_nutrition
    conn = build_site.get_conn()
    try:
        console.print("[cyan]Precomputing menu item nutrition across corpus...[/cyan]")
        stats = precompute_menu_nutrition(conn, shop_id=shop_id, limit=limit)
        console.print(
            f"[green]Completed![/green] Processed {stats['total']} items:\n"
            f"  - Official Chain (Tier 1): {stats['chain']}\n"
            f"  - Direct Government Table (Tier 2): {stats['table']}\n"
            f"  - MEXT Culinary Calculation (Tier 3): {stats['mext_calc']}\n"
            f"  - Unresolved: {stats['unresolved']}"
        )
    finally:
        conn.close()


if __name__ == '__main__':
    app()
