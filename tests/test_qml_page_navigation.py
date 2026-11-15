"""Direct page navigation operates on the existing dashboard snapshot."""

import subprocess
from pathlib import Path


def test_page_navigation_runtime() -> None:
    subprocess.run(
        ["node", str(Path(__file__).parent / "qml/page_navigation.cjs")],
        check=True, capture_output=True, text=True,
    )
