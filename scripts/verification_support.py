"""Keep failed verification workspaces available for inspection."""

from contextlib import contextmanager
from pathlib import Path
from shutil import rmtree
from tempfile import mkdtemp


@contextmanager
def verification_directory(prefix: str, requested: Path | None = None):
    if requested is None:
        directory = Path(mkdtemp(prefix=prefix))
    else:
        directory = requested.resolve()
        directory.mkdir(parents=True, exist_ok=False)
    try:
        yield directory
    except BaseException:
        print(f"Verification failed; evidence retained at {directory}", flush=True)
        raise
    else:
        if requested is None:
            rmtree(directory)
