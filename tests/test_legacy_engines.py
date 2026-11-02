"""The deterministic suites of the v0.3-v0.5 dossier, run against the ported modules."""

import hashlib
import importlib.util
from pathlib import Path

import pytest

from diotima.legacy import motore_v04

LEGACY = Path(__file__).resolve().parents[1] / "src" / "diotima" / "legacy"


def _load(name):
    spec = importlib.util.spec_from_file_location(f"legacy_{name}", LEGACY / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_logic_engine_v03_all_checks_pass():
    checks = _load("motore_v03").esegui_test()
    failed = [c for c in checks if not c["ok"]]
    assert len(checks) == 35
    assert not failed, failed


def test_audit_sheet_f2_all_checks_pass():
    checks = _load("scheda_f2").esegui_test_f2()
    failed = [c for c in checks if not c["ok"]]
    assert len(checks) == 34
    assert not failed, failed


@pytest.mark.parametrize(
    ("p_max", "conf", "k", "n_min"),
    [(0.04, 0.85, 1, 83), (0.05, 0.95, 0, 58)],
)
def test_planner_exact_minimum_sample(p_max, conf, k, n_min):
    r = motore_v04.plan_custom_sample_size(
        profilo="personalizzato", p_max=p_max, confidenza=conf, k_max_override=k, n_custom=60
    )
    assert r["n_minimo_richiesto_per_k"] == n_min
    assert r["piano_adeguato"] is (60 >= n_min)


def test_l0_sha256_gate(tmp_path):
    (tmp_path / "doc.xml").write_bytes(b"<p>text</p>")
    (tmp_path / "empty.xml").write_bytes(b"")
    good = hashlib.sha256(b"<p>text</p>").hexdigest()
    check = motore_v04.verifica_integrita_primario_sha256
    assert check("doc.xml", good, base_dir=tmp_path)["esito_verifica"] == "SHA256_VERIFICATO_COINCIDENTE"
    assert check("doc.xml", "0" * 64, base_dir=tmp_path)["esito_verifica"] == "SHA256_MISMATCH_RT07"
    missing = check("absent.xml", good, base_dir=tmp_path)
    assert missing["esito_verifica"] == "FILE_PRIMARIO_NON_ACQUISITO" and not missing["errore_E8"]
    assert check("empty.xml", good, base_dir=tmp_path)["errore_E8"] is True
    with pytest.raises(ValueError):
        check("../../etc/passwd", good, base_dir=tmp_path)
