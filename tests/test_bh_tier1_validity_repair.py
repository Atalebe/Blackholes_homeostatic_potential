import importlib.util
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

SCRIPT=Path(__file__).parents[1]/"scripts"/"41_execute_bh_tier1_validity_repair.py"
spec=importlib.util.spec_from_file_location("repair",SCRIPT);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


def test_time_weighted_fraction_differs_from_row_fraction():
    d=pd.DataFrame({"t":[0.,1.,10.],"inside":[True,False,True]})
    assert abs(m.time_weighted_fraction(d,"t","inside")-.1)<1e-12
    assert d.inside.mean()==2/3


def test_right_endpoint_probe_value():
    d=pd.DataFrame({"t":[0.,1.,10.],"inside":[True,False,True]})
    t=d.t.to_numpy(); y=d.inside.to_numpy(); dt=np.diff(t)
    right=float(np.sum(dt*y[1:])/np.sum(dt))
    assert abs(right-.9)<1e-12


def test_axis_reconstruction_is_exact():
    h=np.array([1.,2.,4.]);med=np.array([2.,2.,2.]);s=-np.abs(h-med)
    assert np.max(np.abs((-np.abs(h-med))-s))==0


def test_dispersion_metrics():
    x=pd.Series([0.,1.,2.,3.])
    assert m.dispersion(x,"variance")>0
    assert m.dispersion(x,"mad2")==1.0
    assert m.dispersion(x,"iqr2")>0


def test_bridge_requires_explicit_shared_mapping():
    with tempfile.TemporaryDirectory() as d:
        root=Path(d)
        (root/"data").mkdir()
        pd.DataFrame({"bh_id":[1,2],"subhalo_id":[11,22]}).to_csv(root/"data/mapping.csv",index=False)
        cfg={"dependence_bridge":{"scan_roots":["data"],"id_candidates":["bh_id","subhalo_id","host_id"],"max_csv_bytes":100000}}
        inventory,bridge,verdict=m.dependence_bridge(root,cfg)
        assert len(inventory)==1
        assert len(bridge)==2
        assert verdict["verdict"]=="bridge_candidate_requires_uniqueness_review"


def test_categorical_group_thresholds_are_numeric():
    group=pd.Series(pd.Categorical(["a","a","b","b"]))
    coordinate=pd.Series([0.1,0.2,0.8,0.9])
    frame=pd.DataFrame({"group":group,"coordinate":coordinate})
    thresholds=frame.groupby("group",observed=False)["coordinate"].quantile([0.25,0.75]).unstack()
    low=pd.to_numeric(frame["group"].map(thresholds[0.25]),errors="coerce").astype(float)
    high=pd.to_numeric(frame["group"].map(thresholds[0.75]),errors="coerce").astype(float)
    inside=(coordinate.astype(float)>=low)&(coordinate.astype(float)<=high)
    assert inside.dtype==bool


def test_tng_camelcase_aliases_are_discovered():
    with tempfile.TemporaryDirectory() as d:
        root=Path(d);(root/"data").mkdir()
        pd.DataFrame({"BHID":[1,2],"SubhaloID":[11,22],"SubhaloGrNr":[7,8]}).to_csv(root/"data/map.csv",index=False)
        cfg={"dependence_bridge":{"scan_roots":["data"],"id_candidates":[],"id_aliases":{"bh_id":["bhid"],"subhalo_id":["subhaloid"],"host_id":["subhalogrnr"]},"max_csv_bytes":100000}}
        inventory,bridge,verdict=m.dependence_bridge(root,cfg,{1,2})
        assert set(verdict["dependency_columns"])=={"subhalo_id","host_id"}
        assert verdict["coverage_fraction"]==1.0
