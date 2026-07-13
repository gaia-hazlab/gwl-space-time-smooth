"""Zarr staging to UW Kopah (S3-compatible), following the gaia-cli conventions.

Zarr, not netCDF, is the staging format: a Zarr store is chunked and readable *lazily over the
network*, so a consumer pulls only the bytes it needs. That matters most for the SVM: the USGS
CVM17 grid is a **6.2 GB netCDF that must be downloaded in full** before a single Vs30 value can be
read. Staged as chunked Zarr on Kopah, the same extraction reads only the Puget/Cascades window and
only the shallow depth levels.

Conventions are deliberately identical to ``gaia-hazlab/gaia-cli`` (``src/gaia_cli/io.py``) so the
stores interoperate: **obstore + zarr.storage.ObjectStore, zarr_format=3, consolidated=False**, ~10 MB
chunks, credentials from ``AWS_PROFILE``.

Kopah specifics (see gaia-hazlab/skypilot-hyak/docs/kopah.md):

    export AWS_ACCESS_KEY_ID=...        # from UW IT when the Kopah account is created
    export AWS_SECRET_ACCESS_KEY=...
    export AWS_ENDPOINT_URL=https://s3.kopah.uw.edu     # NOT an AWS endpoint
    # or put endpoint_url + keys in an ~/.aws/config profile and set AWS_PROFILE

Bucket layout (global namespace, so paths are prefixed by project):

    s3://gaia/soil-twin/static/vs30_90m.zarr        derived 90 m Vs30
    s3://gaia/soil-twin/static/svm_cvm17.zarr       staged SVM shallow-Vs grid (from the 6.2 GB nc)
    s3://gaia/soil-twin/forecast/<model>/<init>.zarr  AI rainfall forcing (FuXi et al.)
"""

from __future__ import annotations

import logging
import os

import numpy as np
import xarray as xr

logger = logging.getLogger("zarr_store")

KOPAH_ENDPOINT = "https://s3.kopah.uw.edu"
GAIA_BUCKET = "s3://gaia/soil-twin"
_CHUNK_TARGET_BYTES = 10 * 1024 * 1024          # 10 MB, matching gaia-cli


def is_remote(path):
    return str(path).startswith("s3://")


def check_s3_env(path):
    """Fail early (before any compute) if S3 credentials are not configured."""
    if not is_remote(path):
        return
    has_profile = "AWS_PROFILE" in os.environ
    has_keys = "AWS_ACCESS_KEY_ID" in os.environ and "AWS_SECRET_ACCESS_KEY" in os.environ
    if not (has_profile or has_keys):
        raise ValueError(
            "Writing to S3 needs credentials: set AWS_PROFILE, or AWS_ACCESS_KEY_ID + "
            "AWS_SECRET_ACCESS_KEY. For Kopah also set "
            f"AWS_ENDPOINT_URL={KOPAH_ENDPOINT} (see skypilot-hyak/docs/kopah.md)."
        )
    if "kopah" in os.environ.get("AWS_ENDPOINT_URL", "") or is_remote(path):
        if "AWS_ENDPOINT_URL" not in os.environ:
            logger.warning("AWS_ENDPOINT_URL is unset; for Kopah it must be %s", KOPAH_ENDPOINT)


def store_for_path(path):
    """A Zarr-compatible store for a local path or an ``s3://`` URL (Kopah or AWS).

    Mirrors ``gaia_cli.io._zarr_store_for_path`` but honours ``AWS_ENDPOINT_URL`` so the same code
    targets Kopah instead of AWS.
    """
    path = str(path)
    if not is_remote(path):
        return path
    from obstore.auth.boto3 import Boto3CredentialProvider
    from obstore.store import from_url
    from zarr.storage import ObjectStore

    kw = {"credential_provider": Boto3CredentialProvider(), "region": "us-west-2"}
    endpoint = os.environ.get("AWS_ENDPOINT_URL")
    if endpoint:
        kw["endpoint"] = endpoint                 # Kopah: https://s3.kopah.uw.edu
        kw["virtual_hosted_style_request"] = False
    return ObjectStore(from_url(path, **kw))


def _encoding(ds):
    """Chunk each variable to ~10 MB (gaia-cli's target); tiny arrays stay single-chunk.

    A variable that is **already dask-chunked** keeps the caller's chunking: overriding it would make
    one Zarr chunk span several dask chunks, which xarray rejects outright because writing it in
    parallel can corrupt data. The caller chunked it on purpose (see stage_svm_zarr).
    """
    enc = {}
    for name, v in ds.data_vars.items():
        if v.size == 0:
            continue
        if v.chunks is not None:                  # dask-backed: defer to the caller's chunks
            continue
        itemsize = max(v.dtype.itemsize, 1)
        if v.nbytes <= _CHUNK_TARGET_BYTES:
            enc[name] = {"chunks": v.shape}       # single chunk: to_zarr won't re-chunk
            continue
        # chunk the leading axis, keep the trailing (spatial) dims whole where possible
        trailing = int(np.prod(v.shape[1:])) if v.ndim > 1 else 1
        per_step = max(trailing * itemsize, 1)
        n_lead = max(1, min(v.shape[0], _CHUNK_TARGET_BYTES // per_step))
        enc[name] = {"chunks": (n_lead,) + v.shape[1:]}
    return enc


def write_zarr(ds, path, mode="w"):
    """Write a Dataset to Zarr, locally or to Kopah/S3. Returns the path."""
    check_s3_env(path)
    store = store_for_path(path)
    ds.to_zarr(store, mode=mode, zarr_format=3, consolidated=False, encoding=_encoding(ds))
    logger.info("wrote zarr %s (%s)", path, ", ".join(ds.data_vars))
    return path


def open_zarr(path):
    """Open a Zarr store from a local path or Kopah/S3, lazily (no full download)."""
    return xr.open_dataset(store_for_path(path), engine="zarr", consolidated=False)
