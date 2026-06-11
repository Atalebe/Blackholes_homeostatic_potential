from pathlib import Path
import re
import numpy as np
import pandas as pd
from astropy.io import fits

runtime_csv = Path("outputs/tables/manga_sample_runtime_table.csv")
dapall_fits = Path("data/external/manga/dr17/catalogs/dapall-v3_1_1-3.1.0.fits")

out_csv = Path("outputs/tables/manga_sample_runtime_table_augmented.csv")
out_map_csv = Path("outputs/tables/manga_dap_channel_map.csv")

runtime = pd.read_csv(runtime_csv).copy()
runtime["plateifu"] = runtime["plateifu"].astype(str).str.strip()

def to_native_array(arr):
    arr = np.asarray(arr)
    if arr.dtype.kind in ("S", "U", "O"):
        return arr
    dt = arr.dtype
    if dt.byteorder == ">" or (dt.byteorder == "=" and not dt.isnative):
        arr = arr.byteswap().view(dt.newbyteorder("="))
    else:
        arr = arr.astype(dt.newbyteorder("="), copy=False)
    return arr

def channel_map_from_header(header, prefix):
    mapping = {}
    pat = re.compile(rf"^{prefix}(\d+)$")
    for k, v in header.items():
        m = pat.match(k)
        if m:
            idx = int(m.group(1)) - 1
            mapping[str(v).strip()] = idx
    return mapping

def resolve_name(mapping, candidates):
    keys = list(mapping.keys())
    kl = {k.lower(): k for k in keys}
    for cand in candidates:
        if cand.lower() in kl:
            return kl[cand.lower()]
    for cand in candidates:
        for k in keys:
            if cand.lower() in k.lower() or k.lower() in cand.lower():
                return k
    return None

with fits.open(dapall_fits, memmap=True) as hdul:
    h0 = hdul[0].header
    h1 = hdul[1].header
    data = hdul[1].data

    spi_map = {}
    spi_map.update(channel_map_from_header(h0, "SPI"))
    spi_map.update(channel_map_from_header(h1, "SPI"))

    elg_map = {}
    elg_map.update(channel_map_from_header(h0, "ELG"))
    elg_map.update(channel_map_from_header(h1, "ELG"))

    spi_name = resolve_name(spi_map, ["Dn4000", "D4000"])
    oiii_name = resolve_name(elg_map, ["OIII-5008", "OIII-5007"])
    ha_name = resolve_name(elg_map, ["Ha-6564", "Ha-6563", "Halpha"])

    if spi_name is None:
        raise RuntimeError(f"Could not resolve D4000/Dn4000 channel from SPI map: {list(spi_map)[:20]}")
    if oiii_name is None:
        raise RuntimeError(f"Could not resolve OIII channel from ELG map: {list(elg_map)[:20]}")
    if ha_name is None:
        raise RuntimeError(f"Could not resolve Halpha channel from ELG map: {list(elg_map)[:20]}")

    plateifu = pd.Series(to_native_array(data["PLATEIFU"])).astype(str).str.strip()

    specindex_1re = to_native_array(data["SPECINDEX_1RE"])
    em_gflux_1re = to_native_array(data["EMLINE_GFLUX_1RE"])
    em_gsb_1re = to_native_array(data["EMLINE_GSB_1RE"])

    aug = pd.DataFrame({
        "plateifu": plateifu,
        "dn4000_1re": specindex_1re[:, spi_map[spi_name]],
        "oiii5008_gflux_1re": em_gflux_1re[:, elg_map[oiii_name]],
        "ha_gflux_1re": em_gflux_1re[:, elg_map[ha_name]],
        "ha_gsb_1re": em_gsb_1re[:, elg_map[ha_name]],
    })

    channel_map = pd.DataFrame([
        {"kind": "SPI", "resolved_name": spi_name, "index0": spi_map[spi_name], "new_column": "dn4000_1re"},
        {"kind": "ELG", "resolved_name": oiii_name, "index0": elg_map[oiii_name], "new_column": "oiii5008_gflux_1re"},
        {"kind": "ELG", "resolved_name": ha_name, "index0": elg_map[ha_name], "new_column": "ha_gflux_1re / ha_gsb_1re"},
    ])
    channel_map.to_csv(out_map_csv, index=False)

merged = runtime.merge(aug, on="plateifu", how="left")
merged.to_csv(out_csv, index=False)

print(f"[ok] wrote {out_csv}")
print(f"[ok] wrote {out_map_csv}")
print(channel_map.to_string(index=False))
print(merged[[
    "plateifu","dn4000_1re","oiii5008_gflux_1re","ha_gflux_1re","ha_gsb_1re"
]].head().to_string(index=False))
