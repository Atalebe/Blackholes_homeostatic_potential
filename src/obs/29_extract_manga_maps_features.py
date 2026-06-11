from pathlib import Path
import re
import numpy as np
import pandas as pd
from astropy.io import fits
from src.utils.config import load_yaml


cfg = load_yaml(CONFIG_PATH)
manifest = pd.read_csv(cfg["data"]["manifest_csv"]).copy()


def safe_get(row, key, default=None):
    return row[key] if key in row.index else default


def normalize_name(x):
    if x is None:
        return ""
    s = str(x).strip().lower()
    s = s.replace("_", "").replace("-", "").replace(" ", "")
    return s


def header_channel_lookup(header):
    """
    Build a mapping from normalized channel name -> zero-based plane index.
    This is intentionally permissive because MaNGA headers vary a bit.
    """
    lookup = {}

    for k, v in header.items():
        if not isinstance(v, str):
            continue

        kk = str(k).strip().upper()
        vv = normalize_name(v)

        idx = None

        # Common style: C1='Hb-4862', C2='OIII-4960', ...
        m = re.fullmatch(r"C(\d+)", kk)
        if m:
            idx = int(m.group(1)) - 1

        # Defensive fallbacks
        if idx is None:
            m = re.fullmatch(r"CHAN(\d+)", kk)
            if m:
                idx = int(m.group(1)) - 1

        if idx is None:
            m = re.fullmatch(r"PLANE(\d+)", kk)
            if m:
                idx = int(m.group(1)) - 1

        if idx is not None and vv != "":
            lookup[vv] = idx

    return lookup


def resolve_channel_index(header, aliases, fallback_index=None):
    lut = header_channel_lookup(header)

    for alias in aliases:
        key = normalize_name(alias)
        if key in lut:
            return lut[key]

    # second pass, substring matching
    for alias in aliases:
        key = normalize_name(alias)
        for name, idx in lut.items():
            if key in name or name in key:
                return idx

    return fallback_index


def get_extension_data(hdul, extname):
    if extname not in hdul:
        raise KeyError(f"Extension '{extname}' not found.")
    data = np.asarray(hdul[extname].data, dtype=float)
    header = hdul[extname].header
    return data, header


def get_extension_mask(hdul, extname):
    mask_name = f"{extname}_MASK"
    if mask_name not in hdul:
        return None
    m = np.asarray(hdul[mask_name].data)
    return m


def extract_map_channel(hdul, extname, aliases=None, fallback_index=None):
    """
    Returns a 2D float array and a same-shape boolean valid mask.
    For 3D maps, selects the requested channel plane.
    For 2D maps, returns directly.
    """
    data, header = get_extension_data(hdul, extname)
    mask = get_extension_mask(hdul, extname)

    if data.ndim == 2:
        arr = data.astype(float)
        valid = np.isfinite(arr)
        if mask is not None and mask.ndim == 2:
            valid &= (mask == 0)
        return arr, valid

    if data.ndim != 3:
        raise ValueError(f"Unexpected ndim={data.ndim} for extension '{extname}'.")

    idx = resolve_channel_index(header, aliases or [], fallback_index=fallback_index)
    if idx is None:
        raise KeyError(
            f"Could not resolve channel for extension '{extname}' with aliases={aliases}."
        )
    if idx < 0 or idx >= data.shape[0]:
        raise IndexError(
            f"Resolved channel index {idx} out of bounds for extension '{extname}' "
            f"with shape {data.shape}."
        )

    arr = data[idx].astype(float)
    valid = np.isfinite(arr)

    if mask is not None:
        if mask.ndim == 3:
            valid &= (mask[idx] == 0)
        elif mask.ndim == 2:
            valid &= (mask == 0)

    return arr, valid


def choose_rre_plane(data3d):
    """
    Heuristic choice of the SPX_ELLCOO plane that most likely stores radius in Re.
    We prefer a plane with:
    - finite center near zero
    - positive dynamic range
    - max value not absurd
    """
    ny = data3d.shape[1]
    nx = data3d.shape[2]
    cy = ny // 2
    cx = nx // 2

    best_i = 0
    best_score = None

    for i in range(data3d.shape[0]):
        a = np.asarray(data3d[i], dtype=float)
        good = np.isfinite(a)
        if good.sum() == 0:
            continue

        vals = a[good]
        center = a[cy, cx] if np.isfinite(a[cy, cx]) else np.nan
        vmax = np.nanmax(vals)
        vmed = np.nanmedian(vals)

        score = 0.0

        # center near zero is good
        if np.isfinite(center):
            score += abs(center)

        # want a map that reaches beyond the center
        if np.isfinite(vmax):
            score += abs(vmax - 2.0)

        # penalize obviously coordinate-like weird planes
        if vmax < 0.2 or vmax > 50:
            score += 100.0

        # mild preference for typical Re-like medians
        if np.isfinite(vmed):
            score += 0.25 * abs(vmed - 1.0)

        if best_score is None or score < best_score:
            best_score = score
            best_i = i

    return best_i


def get_rre_map(hdul):
    """
    Returns a 2D map of elliptical radius in units of Re.
    Preferred source: SPX_ELLCOO plane heuristic.
    Fallback: pixel radius normalized to outer finite footprint.
    """
    if "SPX_ELLCOO" in hdul:
        data = np.asarray(hdul["SPX_ELLCOO"].data, dtype=float)
        if data.ndim == 2:
            rre = data
            if np.isfinite(rre).sum() > 0:
                return rre
        elif data.ndim == 3:
            i = choose_rre_plane(data)
            rre = np.asarray(data[i], dtype=float)
            if np.isfinite(rre).sum() > 0:
                return rre

    # fallback, pixel-space radius normalized to outer footprint
    ref = None
    for ext in ["STELLAR_SIGMA", "SPECINDEX", "EMLINE_GFLUX"]:
        if ext in hdul:
            ref = np.asarray(hdul[ext].data, dtype=float)
            break

    if ref is None:
        raise RuntimeError("Could not construct fallback radial map, no reference extension found.")

    if ref.ndim == 3:
        ref2 = ref[0]
    else:
        ref2 = ref

    ny, nx = ref2.shape
    yy, xx = np.indices((ny, nx))
    cy = (ny - 1) / 2.0
    cx = (nx - 1) / 2.0
    rr = np.sqrt((yy - cy) ** 2 + (xx - cx) ** 2)

    good = np.isfinite(ref2)
    if good.sum() == 0:
        raise RuntimeError("Fallback radial map failed, no finite reference pixels found.")

    scale = np.nanpercentile(rr[good], 95)
    if not np.isfinite(scale) or scale <= 0:
        scale = np.nanmax(rr[good])
    if not np.isfinite(scale) or scale <= 0:
        scale = 1.0

    return rr / scale


def annulus_masks(rre):
    """
    Simple central/mid/outer annuli in Re units.
    Chosen to reproduce sensible small-n central zones and wider outer zones.
    """
    cen = np.isfinite(rre) & (rre >= 0.0) & (rre < 0.5)
    mid = np.isfinite(rre) & (rre >= 0.5) & (rre < 1.0)
    out = np.isfinite(rre) & (rre >= 1.0) & (rre < 1.5)
    return cen, mid, out


def summarize_map(arr, valid, rre, prefix):
    cen_mask, mid_mask, out_mask = annulus_masks(rre)

    def masked_values(region_mask):
        m = region_mask & valid & np.isfinite(arr)
        vals = arr[m]
        vals = vals[np.isfinite(vals)]
        return vals

    vcen = masked_values(cen_mask)
    vmid = masked_values(mid_mask)
    vout = masked_values(out_mask)

    cen = float(np.nanmedian(vcen)) if len(vcen) > 0 else np.nan
    mid = float(np.nanmedian(vmid)) if len(vmid) > 0 else np.nan
    out = float(np.nanmedian(vout)) if len(vout) > 0 else np.nan

    return {
        f"{prefix}_cen": cen,
        f"{prefix}_mid": mid,
        f"{prefix}_out": out,
        f"{prefix}_ncen": float(len(vcen)),
        f"{prefix}_nmid": float(len(vmid)),
        f"{prefix}_nout": float(len(vout)),
        f"{prefix}_delta_out_minus_cen": (
            float(out - cen) if np.isfinite(out) and np.isfinite(cen) else np.nan
        ),
    }


def extract_one_maps_file(maps_path):
    with fits.open(maps_path, memmap=True) as hdul:
        rre = get_rre_map(hdul)

        dn4000, dn4000_valid = extract_map_channel(
            hdul,
            "SPECINDEX",
            aliases=["Dn4000", "D4000"],
            fallback_index=44,
        )

        oiii5008, oiii5008_valid = extract_map_channel(
            hdul,
            "EMLINE_GFLUX",
            aliases=["OIII-5008", "OIII5008", "oiii5008"],
            fallback_index=16,
        )

        ha_flux, ha_flux_valid = extract_map_channel(
            hdul,
            "EMLINE_GFLUX",
            aliases=["Ha-6564", "Halpha", "Ha6564", "ha6564"],
            fallback_index=23,
        )

        ha_gew, ha_gew_valid = extract_map_channel(
            hdul,
            "EMLINE_GEW",
            aliases=["Ha-6564", "Halpha", "Ha6564", "ha6564"],
            fallback_index=23,
        )

        stellar_sigma, stellar_sigma_valid = extract_map_channel(
            hdul,
            "STELLAR_SIGMA",
            aliases=None,
            fallback_index=None,
        )

    out = {}
    out.update(summarize_map(dn4000, dn4000_valid, rre, "dn4000"))
    out.update(summarize_map(oiii5008, oiii5008_valid, rre, "oiii5008_gflux"))
    out.update(summarize_map(ha_flux, ha_flux_valid, rre, "ha_gflux"))
    out.update(summarize_map(ha_gew, ha_gew_valid, rre, "ha_gew"))
    out.update(summarize_map(stellar_sigma, stellar_sigma_valid, rre, "stellar_sigma"))
    return out


rows = []

for _, r in manifest.iterrows():
    maps_path = Path(str(safe_get(r, "maps_local_path", "")))

    row_out = {
        "plateifu": safe_get(r, "plateifu"),
        "role": safe_get(r, "role", "parent"),
        "matched_to": safe_get(r, "matched_to", safe_get(r, "plateifu")),
        "match_rank": safe_get(r, "match_rank", 0),
        "has_legacy_bh_overlay": safe_get(r, "has_legacy_bh_overlay", False),
        "legacy_logMbh": safe_get(r, "legacy_logMbh", np.nan),
        "maps_found": False,
        "maps_local_path": str(maps_path),
        "extract_error": np.nan,
    }

    # initialize all expected numeric outputs
    for prefix in [
        "dn4000",
        "oiii5008_gflux",
        "ha_gflux",
        "ha_gew",
        "stellar_sigma",
    ]:
        row_out[f"{prefix}_cen"] = np.nan
        row_out[f"{prefix}_mid"] = np.nan
        row_out[f"{prefix}_out"] = np.nan
        row_out[f"{prefix}_ncen"] = np.nan
        row_out[f"{prefix}_nmid"] = np.nan
        row_out[f"{prefix}_nout"] = np.nan
        row_out[f"{prefix}_delta_out_minus_cen"] = np.nan

    # missing file is not an extraction error, it just means not downloaded yet
    if str(maps_path) in {"", "."} or not maps_path.exists():
        rows.append(row_out)
        continue

    row_out["maps_found"] = True

    try:
        feats = extract_one_maps_file(maps_path)
        row_out.update(feats)
    except Exception as e:
        row_out["extract_error"] = str(e)

    rows.append(row_out)

out = pd.DataFrame(rows)

features_csv = Path(cfg["outputs"]["features_csv"])
summary_csv = Path(cfg["outputs"]["summary_csv"])
features_csv.parent.mkdir(parents=True, exist_ok=True)

out.to_csv(features_csv, index=False)

summary = pd.DataFrame([{
    "manifest_rows": len(out),
    "maps_found_n": int(out["maps_found"].fillna(False).sum()),
    "rows_extracted_n": int(((out["maps_found"].fillna(False)) & (out["extract_error"].isna())).sum()),
    "rows_with_errors": int(out["extract_error"].notna().sum()),
}])

summary.to_csv(summary_csv, index=False)

print(f"[ok] wrote {features_csv}")
print(f"[ok] wrote {summary_csv}")
print(summary.to_string(index=False))
print(out.head(10).to_string(index=False))
