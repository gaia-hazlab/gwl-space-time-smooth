"""Runtime precondition checks for fetchers with an out-of-band dependency (credentials or an
optional package) that argparse/import alone cannot verify.

These exist because the current failure modes are late and/or unclear:

- ``fetch_smap.py`` / ``fetch_merra2.py`` call ``earthaccess.login(strategy="netrc")`` after
  already importing ``earthaccess``/``h5py``; if ``~/.netrc`` has no NASA Earthdata entry, that
  raises ``earthaccess.exceptions.LoginStrategyUnavailable`` -- a reasonably specific message, but
  as a raw traceback from inside a third-party library, with no repo-specific guidance.
- ``fetch_earth2studio.py`` imports ``torch`` and ``earth2studio`` directly; neither is a declared
  pixi dependency (deliberately -- see that module's docstring), so ``pixi run ai-precip`` fails
  with a bare ``ModuleNotFoundError`` that names neither the missing extra nor the install command
  already documented in the module docstring.

Call these as the FIRST thing inside a fetcher's entry point (its ``main()`` or the function CLI
calls into) -- never at module import time. Importing a fetcher module must stay side-effect-free
(no network/credential lookups) so the offline test suite can still import it during collection.
"""

from __future__ import annotations

import importlib.util
import netrc
import os


def require_netrc(hostname: str, *, task: str, note: str = "") -> None:
    """Exit with an actionable message if ``~/.netrc`` (or ``$NETRC``) has no entry for ``hostname``.

    Mirrors exactly what ``earthaccess.login(strategy="netrc")`` checks (this repo's fetchers call
    that strategy specifically, not ``"all"``, so an ``EARTHDATA_USERNAME``/``PASSWORD`` env var
    pair is NOT a substitute here -- do not tell the user otherwise).
    """
    netrc_path = os.environ.get("NETRC") or os.path.expanduser("~/.netrc")
    try:
        auth = netrc.netrc(netrc_path).authenticators(hostname)
    except FileNotFoundError:
        raise SystemExit(
            f"{task}: no {netrc_path} found. This fetcher authenticates to NASA Earthdata via "
            f"~/.netrc (strategy='netrc'); add a 'machine {hostname} login <user> password <pass>' "
            f"line for your Earthdata account (register at https://urs.earthdata.nasa.gov/)."
            + (f" {note}" if note else "")
        ) from None
    except netrc.NetrcParseError as exc:
        raise SystemExit(f"{task}: {netrc_path} exists but could not be parsed ({exc}).") from exc
    if auth is None:
        raise SystemExit(
            f"{task}: {netrc_path} exists but has no 'machine {hostname}' entry for your "
            f"NASA Earthdata credentials." + (f" {note}" if note else "")
        )


def require_importable(module_name: str, *, task: str, install_hint: str) -> None:
    """Exit with an actionable message if ``module_name`` cannot be imported.

    Uses ``importlib.util.find_spec`` rather than an actual import, so this stays cheap and does
    not itself trigger whatever heavy/GPU-only side effects the real import would have.
    """
    if importlib.util.find_spec(module_name) is None:
        raise SystemExit(f"{task}: '{module_name}' is not installed. {install_hint}")
