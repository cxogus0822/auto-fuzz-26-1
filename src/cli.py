# src/cli.py
import click
from pipeline import AutoFuzzPipeline


@click.group()
def cli():
    """Auto-Fuzz CLI — Seed registration, listing, and fuzzing."""
    pass


# 1. 시드 등록
@cli.command()
@click.option("--dbc", required=True, type=click.Path(exists=True), help="Path to DBC file.")
@click.option("--db", default="seeds.db", help="SQLite DB file path.")
def register(dbc, db):
    """Register seeds from a DBC file into the database."""
    click.echo(f"[+] Parsing DBC file: {dbc}")
    count = AutoFuzzPipeline.register_seeds(dbc, db)
    click.echo(f"[✓] {count} seeds registered into '{db}'")



# 2. 시드 목록 보기
@cli.command()
@click.option("--db", default="seeds.db", help="SQLite DB file path.")
def list(db):
    """List all registered seeds."""
    seeds = AutoFuzzPipeline.list_seeds(db)
    if not seeds:
        click.echo("[!] No seeds found.")
        return
    click.echo(f"[+] {len(seeds)} seeds loaded:")
    click.echo("-" * 60)
    for s in seeds:
        click.echo(f"[{s.id:03}] {s.signal_name:<25} | msg_id={hex(s.message_id)} | priority={s.priority}")
    click.echo("-" * 60)



# 3. 퍼징 실행
@cli.command()
@click.option("--db", default="seeds.db", help="SQLite DB file path.")
@click.option("--channel", default="vcan0", help="CAN channel (default: vcan0)")
@click.option("--can", is_flag=True, help="Enable actual CAN interface (otherwise stub mode).")
@click.option("--can-id", default="0x6A6", help="CAN ID (hex string, default: 0x6A6)")
def run(db, channel, can, can_id):
    """Run Auto-Fuzz pipeline."""
    try:
        can_id_int = int(can_id, 16)
        click.echo(f"[✓] Using CAN ID {hex(can_id_int)} (Tx/Rx)")
    except ValueError:
        click.echo("[!] Invalid CAN ID format. Use hex like 0x6A6.")
        return

    can_iface = None
    if can:
        from interface.can_interface import CANInterface
        can_iface = CANInterface(channel=channel, can_id=can_id_int)
        click.echo(f"[+] CAN Interface initialized on '{channel}' (ID={hex(can_id_int)})")
        click.echo("    • Seeds with message_id will use that ID for sending.")
        click.echo("    • Others will use this default fallback ID.")

    pipeline = AutoFuzzPipeline(db, can_iface=can_iface)
    pipeline.run()


if __name__ == "__main__":
    cli()