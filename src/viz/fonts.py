"""Register the Inter typeface with matplotlib for the science+AI demo look.

The repo bundles the Inter OFL TTFs under ``fonts/`` (Regular / Medium / Bold). This helper
registers them with matplotlib's font manager and sets Inter as the default sans-serif. It is
idempotent and degrades gracefully: if the TTFs are missing (e.g. a fresh checkout without the
fonts) it falls back to DejaVu Sans and warns, so figure scripts never crash on the font.
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger("viz.fonts")

_FONTS_DIR = Path(__file__).resolve().parents[2] / "fonts"
_registered = False


def register_inter(fonts_dir: Path | str = _FONTS_DIR, fallback: str = "DejaVu Sans",
                   size: float = 13.0) -> str:
    """Register bundled Inter TTFs and set them as the matplotlib sans-serif default.

    Returns the resolved family name ("Inter" when the TTFs are present, else ``fallback``).
    Sets ``font.family='sans-serif'`` with the chosen family first so titles/labels use it.
    """
    global _registered
    import matplotlib as mpl
    from matplotlib import font_manager as fm

    fonts_dir = Path(fonts_dir)
    family = fallback
    ttfs = sorted(fonts_dir.glob("Inter-*.ttf")) if fonts_dir.exists() else []
    if ttfs:
        if not _registered:
            for ttf in ttfs:
                try:
                    fm.fontManager.addfont(str(ttf))
                except Exception as exc:                       # corrupt TTF - keep the fallback
                    logger.warning("could not register %s: %s", ttf.name, exc)
        names = {fm.FontProperties(fname=str(t)).get_name() for t in ttfs}
        family = "Inter" if "Inter" in names else (sorted(names)[0] if names else fallback)
        _registered = True
    else:
        logger.warning("Inter TTFs not found in %s; falling back to %s", fonts_dir, fallback)

    mpl.rcParams.update({
        "font.family": "sans-serif",
        "font.sans-serif": [family, fallback, "DejaVu Sans"],
        "font.size": size,
        "axes.titleweight": "bold",
        "axes.titlecolor": "#1a1a2e",
    })
    return family
