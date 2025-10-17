# src/cli.py
import click
from pipeline import AutoFuzzPipeline


@click.group()
def cli():
    """Auto-Fuzz CLI — Seed parsing, registration, listing, and fuzzing."""
    pass


@cli.command()
@click.option("--dbc", required=True, type=click.Path(exists=True), help="Path to DBC file.")
@click.option("--db", default="seeds.db", type=click.Path(), help="SQLite DB file path.")
def register(dbc, db):
    """Register seeds from a DBC file into the database."""
    click.echo(f"[+] Parsing DBC file: {dbc}")
    count = AutoFuzzPipeline.register_seeds(dbc, db)
    click.echo(f"[✓] {count} seeds registered into '{db}'")


@cli.command()
@click.option("--db", default="seeds.db", type=click.Path(), help="SQLite DB file path.")
def list(db):
    """List all registered seeds."""
    seeds = AutoFuzzPipeline.list_seeds(db)
    if not seeds:
        click.echo("[!] No seeds found in the database.")
        return

    click.echo(f"[+] Registered Seeds ({len(seeds)} total):")
    click.echo("-" * 60)
    for s in seeds:
        click.echo(f"  [{s.id:03}] {s.signal_name:<25} | priority={s.priority:<2} | msg_id={hex(s.message_id)}")
    click.echo("-" * 60)


@cli.command()
@click.option("--db", default="seeds.db", type=click.Path(), help="SQLite DB file path.")
def run(db):
    """Run the Auto-Fuzz pipeline."""
    pipeline = AutoFuzzPipeline(db)
    pipeline.run()


if __name__ == "__main__":
    cli()