"""Prepare the game's window icon: the project's own icon when the build ships one, else the player's extracted
control icon converted locally. No game image is bundled."""
import os
from pathlib import Path
import tempfile


def project_icon():
    """The icon this build ships (engage_setup/art/engage-icon.ico), or None in a source checkout without it."""
    candidate = Path(__file__).resolve().parent / 'art' / 'engage-icon.ico'
    return candidate if candidate.is_file() else None


def prepare_icon(source, destination):
    bundled = project_icon()
    if bundled is not None:
        destination = Path(destination)
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            with bundled.open('rb') as src, destination.open('wb') as dst:
                dst.write(src.read())
            return True
        except OSError:
            return False  # Cosmetic metadata must not prevent a playable installation.
    source, destination = Path(source), Path(destination)
    if not source.is_file():
        return False
    try:
        from PIL import Image
    except ImportError:
        return False  # CLI-only source environments may omit optional icon conversion.
    temporary = None
    try:
        with Image.open(source) as image:
            if image.format != 'JPEG' or image.width != image.height or not 16 <= image.width <= 4096:
                return False
            fd, temporary = tempfile.mkstemp(prefix='.engage-icon-', suffix='.ico', dir=destination.parent)
            os.close(fd)
            image.convert('RGBA').save(temporary, format='ICO', sizes=[(n, n) for n in (16, 24, 32, 48, 64, 128, 256)])
        os.replace(temporary, destination)
        return True
    except (OSError, ValueError, Image.DecompressionBombError):
        return False  # Cosmetic metadata must not prevent a playable installation.
    finally:
        if temporary:
            Path(temporary).unlink(missing_ok=True)
