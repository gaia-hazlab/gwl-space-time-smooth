#!/usr/bin/env zsh
# Stage the SVM / CVM17 shallow-Vs grid and derive the 90 m Vs30 layer.
#
#   Soil Velocity Model  : Grant, Wirth & Stone (2025), Seismica, doi:10.26443/seismica.v4i2.1672
#   USGS data release    : "A 3-D Seismic Velocity Model for Cascadia with Shallow Soils &
#                           Topography, v1.7", doi:10.5066/P14HJ3IC
#
# Only CVM17_L01.nc carries the near-surface layer we need:
#   CVM17_L01.nc  6.2 GB  200 m horiz / 10 m vert,  0-100 m depth   <-- Layer 0, the one for Vs30
#   CVM17_L2.nc   3.6 GB  300 m horiz / 300 m vert, 1500-9900 m     (mid crust, not useful here)
#   CVM17_L3.nc   0.8 GB  900 m horiz / 900 m vert, 10800-59400 m   (deep crust, not useful here)
#
# NOTE: ScienceBase gates the large S3 files behind a captcha, so the download CANNOT be scripted.
# This script opens the download page, waits for the file, verifies it, reports the depth
# convention, then runs the extraction + figure.
#
# Usage:  ./scripts/stage_svm.zsh

set -euo pipefail

ITEM_URL="https://www.sciencebase.gov/catalog/item/65b40c6ad34e36a390458d76"
DEST="data/raw/CVM17_L01.nc"
EXPECTED_BYTES=6179597898          # from the ScienceBase item manifest

cd "${0:A:h}/.."                   # repo root, wherever the script is called from
mkdir -p data/raw

# ----------------------------------------------------------------- 1. obtain the file
if [[ -f "$DEST" ]]; then
  have=$(stat -f%z "$DEST")        # macOS stat; use `stat -c%s` on GNU/Linux
  print -- "Found $DEST (${have} bytes)"
else
  cat <<EOF

CVM17_L01.nc is not staged, and ScienceBase requires a captcha for this file, so it
cannot be fetched from the command line. Download it by hand:

  1. Opening: $ITEM_URL
  2. Under "Attached Files", download  CVM17_L01.nc  (6.2 GB)
  3. Move it to:  $(pwd)/$DEST

EOF
  [[ "$(uname)" == "Darwin" ]] && open "$ITEM_URL"
  print -n -- "Press RETURN once CVM17_L01.nc is in place (Ctrl-C to abort)... "
  read -r
  [[ -f "$DEST" ]] || { print -u2 -- "ERROR: $DEST still not found."; exit 1; }
  have=$(stat -f%z "$DEST")
fi

# ----------------------------------------------------------------- 2. verify it is intact
if [[ "$have" -ne "$EXPECTED_BYTES" ]]; then
  print -u2 -- "ERROR: size mismatch. expected $EXPECTED_BYTES bytes, got $have."
  print -u2 -- "The download is probably truncated or is the captcha HTML page. Re-download."
  exit 1
fi
# netCDF4 is HDF5: the file must start with the \x89HDF magic, not '<!doctype'
magic=$(head -c 4 "$DEST" | xxd -p)
if [[ "$magic" != "89484446" ]]; then
  print -u2 -- "ERROR: $DEST is not an HDF5/netCDF4 file (magic=$magic). Likely a saved HTML page."
  exit 1
fi
print -- "OK: size and HDF5 magic verified."

# ----------------------------------------------------------------- 3. report the depth convention
# This is the load-bearing question: with topography in the model, 'the top 30 m' must be measured
# from the GROUND SURFACE, not from sea level. Print the schema + the actual near-surface structure.
print -- "\n--- schema / depth convention -------------------------------------------------"
pixi run python scripts/inspect_svm_depth.py "$DEST"
print -- "-------------------------------------------------------------------------------\n"

# ----------------------------------------------------------------- 4. derive Vs30 + redraw the figure
# The extraction is surface-referenced: per column it finds the ground surface (shallowest valid
# sample) and integrates the travel time 30 m BELOW it, so topography is handled correctly.
print -- "Deriving the 90 m Vs30 layer from the SVM shallow grid..."
pixi run vs30 --svm-nc "$DEST" --vs-var vs --depth-name z

print -- "Regenerating the static-layer catalog figure..."
pixi run static-layers

print -- "\nDone. Updated:"
print -- "  data/processed/vs30_90m.tif        (Vs30 from the SVM, 90 m EPSG:5070)"
print -- "  docs/twin/assets/static_layers.png (figure now shows the SVM Vs30)"
