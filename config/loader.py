import os
import yaml

def load_config(path: str = None) -> dict:
    """Load config YAML. If none given, load default.yaml."""
    base_dir = os.path.dirname(__file__)
    default_path = os.path.join(base_dir, "default.yaml")

    if path is None:
        path = default_path

    with open(path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    return cfg