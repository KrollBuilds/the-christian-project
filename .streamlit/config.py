import os
from pathlib import Path

import toml

CONFIG_PATH = Path(__file__).with_suffix('.toml')


def update_streamlit_port() -> None:
    if not CONFIG_PATH.exists():
        return
    data = toml.loads(CONFIG_PATH.read_text())
    override = os.getenv("STREAMLIT_SERVER_PORT") or os.getenv("PORT")
    if override:
        data.setdefault("server", {})["port"] = int(override)
        CONFIG_PATH.write_text(toml.dumps(data))


update_streamlit_port()
