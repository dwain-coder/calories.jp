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
):
    """Parse MAFF recipe ingredients and resolve them to MEXT items."""
    from . import build_site
    build_site.build_links(limit=limit, report=report, rebuild=rebuild)


@app.command("build-search")
def build_search_cmd():
    """Rebuild the FTS5 search index over the clean corpus."""
    from . import build_site
    build_site.build_search()


@app.command("build-sitemaps")
def build_sitemaps_cmd():
    """Write sitemap-en.xml / sitemap-ja.xml under data/sitemaps/."""
    from . import build_site
    build_site.build_sitemaps()


@app.command("build-site")
def build_site_cmd():
    """Run all site builders in order: names, pages, links, search, sitemaps."""
    from . import build_site
    build_site.build_names()
    build_site.build_pages()
    build_site.build_links()
    build_site.build_search()
    build_site.build_sitemaps()


if __name__ == '__main__':
    app()
