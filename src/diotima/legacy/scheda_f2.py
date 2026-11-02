#!/usr/bin/env python3
"""
Diotima F2 v0.5 — scheda CSV a 22 colonne, validatore/parser e bridge verso motore v0.3.

Sola libreria standard Python 3.11+. Nessuna dipendenza esterna, nessuna chiamata di rete.
Il modulo estende la scheda F2 con `estratto_fedele` e `polarita_fonte` (protocollo §11),
valida il foglio in modalità template/esecuzione, verifica SHA-256 reali su disco e
costruisce un foglio compatibile con `motore_v0.3.metriche3` e `motore_v0.3.accettazione3`.
"""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import io
import pathlib
import re
import sys
from typing import Any, Dict, List, Optional, Tuple

_PACKAGE_DIR = pathlib.Path(__file__).resolve().parent
_PROJECT_DIR = _PACKAGE_DIR.parent
MOTORE_V03 = _PACKAGE_DIR / "motore_v03.py"

CSV_SCHEDA_V02 = _PACKAGE_DIR / "data" / "scheda_audit_v0.2.csv"
CSV_SCHEDA_V05 = _PACKAGE_DIR / "data" / "scheda_audit_v0.5.csv"

HEADER_ATTESO_20 = [
    "tipo_riga",
    "id",
    "documento_id",
    "voce_o_affermazione",
    "tipo_unita",
    "source_kind",
    "verification_status",
    "stato_accesso",
    "identita_ok",
    "hash_file",
    "posizione_dichiarata",
    "posizione_verificata",
    "link_risolvibile",
    "esito",
    "tipo_errore",
    "tempo_min",
    "lettore",
    "revisione_indipendente",
    "adjudicazione",
    "note",
]
HEADER_ATTESO_22 = HEADER_ATTESO_20 + ["estratto_fedele", "polarita_fonte"]

ESTRATTO_FEDELE_AMMESSI = ("sì", "no")
POLARITA_AMMESSE = ("a_favore", "contraria", "mista")
SI_NO_AMMESSI = ("sì", "no")

STATI_ORDINARI = ("supporta", "parziale", "contrasta", "insufficiente", "verifica non possibile")
STATO_BUDGET = "non_valutata_budget"
GIUDICABILI = ("supporta", "parziale", "contrasta", "insufficiente")
CODICI_AMMESSI = {"E1", "E2", "E3", "E4", "E5", "E6", "E7", "E8"}
FEDELTA_ERR = {"E1", "E2", "E3", "E6"}
BLOCCANTI = {"E1", "E2", "E7"}

STATI_ACCESSO_DOC = ("metadato", "abstract", "full text", "non disponibile")
IDENTITA_AMMESSI = ("sì", "no", "")
SOURCE_KIND_AMMESSI = ("primary_excerpt", "dossier_paraphrase")
VERIFICATION_STATUS_AMMESSI = ("verified_primary", "unverified_primary")
ESITO_BUDGET = STATO_BUDGET

_ESEMPIO_MARKER = "RIGA DI ESEMPIO ILLUSTRATIVO"
_HEX64_RE = re.compile(r"^[0-9a-fA-F]{64}$")


# ============================================================================
# Caricamento del motore v0.3 e utilità di parsing
# ============================================================================

def _carica_motore_v03():
    spec = importlib.util.spec_from_file_location("diotima_motore_v03_f2", MOTORE_V03)
    if spec is None or spec.loader is None:
        raise ImportError(f"Impossibile caricare il motore v0.3 da {MOTORE_V03}")
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def _split_errs(testo: str) -> Tuple[set, bool]:
    codici = [c.strip() for c in (testo or "").split(",") if c.strip()]
    duplicati = len(codici) != len(set(codici))
    return set(codici), duplicati


def _parse_text(text: str) -> List[List[str]]:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if text.startswith("\ufeff"):
        text = text[1:]
    reader = csv.reader(io.StringIO(text), delimiter=";", quotechar='"')
    righe: List[List[str]] = []
    for row in reader:
        if not row:
            continue
        if len(row) == 1 and row[0].strip() == "":
            continue
        righe.append(list(row))
    return righe


def _leggi_da_path_csv(percorso: pathlib.Path) -> List[List[str]]:
    if not percorso.exists():
        raise FileNotFoundError("File CSV scheda non trovato su disco")
    if not percorso.is_file():
        raise ValueError("Percorso CSV scheda non punta a un file regolare")
    try:
        contenuto = percorso.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as exc:
        raise ValueError(f"Impossibile leggere il file CSV scheda ({type(exc).__name__})") from exc
    return _parse_text(contenuto)


def _leggi_righe(lines_or_path: Any, sorgente_tipo: Optional[str] = None) -> List[List[str]]:
    if sorgente_tipo not in (None, "path", "testo"):
        raise ValueError("sorgente_tipo deve essere None, 'path' o 'testo'")
    if sorgente_tipo == "path":
        if not isinstance(lines_or_path, (str, pathlib.Path)):
            raise TypeError("Con sorgente_tipo='path' lines_or_path deve essere str o pathlib.Path")
        if isinstance(lines_or_path, str) and not lines_or_path.strip():
            raise ValueError("Percorso CSV scheda vuoto")
        return _leggi_da_path_csv(pathlib.Path(lines_or_path))
    if sorgente_tipo == "testo":
        if not isinstance(lines_or_path, str):
            raise TypeError("Con sorgente_tipo='testo' lines_or_path deve essere str")
        return _parse_text(lines_or_path)
    if isinstance(lines_or_path, pathlib.Path):
        return _leggi_da_path_csv(lines_or_path)
    if isinstance(lines_or_path, str):
        if "\n" in lines_or_path or ";" in lines_or_path:
            return _parse_text(lines_or_path)
        if not lines_or_path.strip():
            return []
        percorso = pathlib.Path(lines_or_path)
        return _leggi_da_path_csv(percorso)
    if isinstance(lines_or_path, (list, tuple)):
        if not lines_or_path:
            return []
        if all(isinstance(x, str) for x in lines_or_path):
            return _parse_text("\n".join(lines_or_path))
        return [list(x) for x in lines_or_path]
    raise TypeError("lines_or_path deve essere pathlib.Path, str, list o tuple")


def _risultato_validazione(
    valido: bool,
    schema_csv: str,
    modalita: str,
    n_colonne: int,
    righe_documento: int,
    righe_unita: int,
    righe_esempio: int,
    hash_verificati_su_disco: int,
    errori: List[str],
) -> Dict[str, Any]:
    return {
        "valido": valido,
        "schema_csv": schema_csv,
        "modalita": modalita,
        "n_colonne": n_colonne,
        "righe_documento": righe_documento,
        "righe_unita": righe_unita,
        "righe_esempio": righe_esempio,
        "hash_verificati_su_disco": hash_verificati_su_disco,
        "errori": errori,
    }


# ============================================================================
# Verifica SHA-256 reale su disco
# ============================================================================

def verifica_sha256_documento(
    file_path: str | pathlib.Path,
    expected_sha256: str,
    base_dir: Optional[str | pathlib.Path] = None,
) -> Dict[str, Any]:
    if not isinstance(expected_sha256, str) or not _HEX64_RE.match(expected_sha256):
        raise ValueError("expected_sha256 deve essere una stringa esadecimale di 64 caratteri (0-9a-fA-F)")
    if isinstance(file_path, bool) or not isinstance(file_path, (str, pathlib.Path)):
        raise ValueError("file_path deve essere str o pathlib.Path")
    raw_fp = str(file_path).strip()
    if not raw_fp:
        raise ValueError("RT-07: file_path documento vuoto")

    base: Optional[pathlib.Path] = None
    if base_dir is not None:
        if isinstance(base_dir, bool) or not isinstance(base_dir, (str, pathlib.Path)):
            raise ValueError("base_dir deve essere str o pathlib.Path")
        raw_base = str(base_dir).strip()
        if not raw_base:
            raise ValueError("RT-07: corpus_base_dir vuoto o composto da soli spazi bianchi")
        base = pathlib.Path(raw_base).expanduser().resolve()

    percorso = pathlib.Path(raw_fp).expanduser()
    if base is None:
        # R08 + AL-08: senza base_dir esplicito, vietati segmenti '..', path relativi CWD-dipendenti
        # e percorsi fuori dal perimetro del repository (_PROJECT_DIR).
        if ".." in percorso.parts:
            raise ValueError("Path traversal bloccato: segmento '..' non ammesso senza corpus_base_dir")
        if not percorso.is_absolute():
            raise ValueError(
                "Path traversal / dipendenza CWD bloccata: percorso relativo non ammesso senza corpus_base_dir esplicito"
            )
    else:
        if not percorso.is_absolute():
            percorso = base / percorso

    try:
        risolto = percorso.resolve()
    except OSError:
        return {
            "ok": False,
            "esito": "percorso primario non risolvibile su disco (E8)",
            "sha256_atteso": expected_sha256.lower(),
            "sha256_calcolato": None,
            "bytes": None,
            "errore_E8": True,
            "file_acquisito": False,
        }

    radice_confine = base if base is not None else _PROJECT_DIR.resolve()
    if not risolto.is_relative_to(radice_confine):
        raise ValueError(
            "Path traversal bloccato: il percorso del documento esce dal perimetro consentito (RT-07)"
        )

    if not risolto.exists():
        # ME-01: file assente su disco = mancata acquisizione (RT-VNP, errore_E8=False), allineato al motore L0.
        return {
            "ok": False,
            "esito": "file primario non acquisito su disco (RT-VNP)",
            "sha256_atteso": expected_sha256.lower(),
            "sha256_calcolato": None,
            "bytes": None,
            "errore_E8": False,
            "file_acquisito": False,
        }
    if not risolto.is_file():
        return {
            "ok": False,
            "esito": "percorso primario non punta a un file regolare (E8)",
            "sha256_atteso": expected_sha256.lower(),
            "sha256_calcolato": None,
            "bytes": None,
            "errore_E8": True,
            "file_acquisito": False,
        }

    try:
        dimensione = risolto.stat().st_size
    except OSError:
        return {
            "ok": False,
            "esito": "impossibile leggere i metadati del file primario (E8)",
            "sha256_atteso": expected_sha256.lower(),
            "sha256_calcolato": None,
            "bytes": None,
            "errore_E8": True,
            "file_acquisito": False,
        }

    if dimensione <= 0:
        return {
            "ok": False,
            "esito": "file vuoto (0 byte): E8",
            "sha256_atteso": expected_sha256.lower(),
            "sha256_calcolato": None,
            "bytes": 0,
            "errore_E8": True,
            "file_acquisito": False,
        }

    digest = hashlib.sha256()
    try:
        with risolto.open("rb") as fh:
            while True:
                blocco = fh.read(1024 * 1024)
                if not blocco:
                    break
                digest.update(blocco)
    except OSError:
        return {
            "ok": False,
            "esito": "lettura binaria del file primario non riuscita (E8)",
            "sha256_atteso": expected_sha256.lower(),
            "sha256_calcolato": None,
            "bytes": dimensione,
            "errore_E8": True,
            "file_acquisito": False,
        }

    calcolato = digest.hexdigest()
    ok = calcolato == expected_sha256.lower()
    return {
        "ok": ok,
        "esito": "hash SHA-256 verificato" if ok else "hash SHA-256 non coincidente",
        "sha256_atteso": expected_sha256.lower(),
        "sha256_calcolato": calcolato,
        "bytes": dimensione,
        "errore_E8": False,
        "file_acquisito": True,
    }


def _path_documento(
    doc_id: str,
    doc_file_map: Optional[Dict[str, str]],
    base_dir: Optional[pathlib.Path],
) -> Tuple[Optional[pathlib.Path], Optional[str]]:
    if doc_file_map is not None:
        if doc_id not in doc_file_map:
            return None, f"RT-07: doc_file_map privo del documento acquisito {doc_id}"
        val = doc_file_map[doc_id]
        if not isinstance(val, (str, pathlib.Path)) or not str(val).strip():
            return None, f"RT-07: percorso vuoto o non valido in doc_file_map per {doc_id}"
        return pathlib.Path(val), None
    if base_dir is not None:
        base = pathlib.Path(base_dir)
        if not base.exists() or not base.is_dir():
            return None, f"RT-07: corpus_base_dir inesistente o non directory per {doc_id}"
        candidati = [
            p
            for p in sorted(base.rglob("*"))
            if p.is_file()
            and (p.name == doc_id or p.name.startswith(doc_id + "_") or p.stem == doc_id)
        ]
        if len(candidati) == 1:
            return candidati[0], None
        if not candidati:
            return None, f"RT-07: file primario non trovato nel corpus per {doc_id}"
        return None, f"RT-07: file primario ambiguo per {doc_id}: {len(candidati)} candidati"
    return None, None


def _verifica_documenti_su_disco(
    docs_rows: List[Tuple[int, Dict[str, str]]],
    corpus_base_dir: Optional[pathlib.Path],
    doc_file_map: Optional[Dict[str, str]],
) -> Tuple[Dict[str, Dict[str, Any]], List[str], int]:
    risultati: Dict[str, Dict[str, Any]] = {}
    errori: List[str] = []
    verificati_ok = 0
    if corpus_base_dir is None and doc_file_map is None:
        return risultati, errori, verificati_ok

    if corpus_base_dir is not None:
        if isinstance(corpus_base_dir, bool) or not isinstance(corpus_base_dir, (str, pathlib.Path)) or not str(corpus_base_dir).strip():
            return risultati, ["RT-07: corpus_base_dir vuoto o non valido"], 0
        base: Optional[pathlib.Path] = pathlib.Path(str(corpus_base_dir).strip())
    else:
        base = None
    for idx, row in docs_rows:
        doc_id = row.get("id", "")
        accesso = row.get("stato_accesso", "")
        errs, _ = _split_errs(row.get("tipo_errore", ""))
        if accesso not in ("full text", "abstract") or "E8" in errs:
            continue
        percorso, errore_path = _path_documento(doc_id, doc_file_map, base)
        if errore_path is not None:
            errori.append(f"Riga {idx} ({doc_id}): {errore_path}")
            continue
        if percorso is None:
            continue
        try:
            esito = verifica_sha256_documento(percorso, row.get("hash_file", ""), base_dir=base)
        except ValueError as exc:
            errori.append(f"Riga {idx} ({doc_id}): RT-07 {exc}")
            continue
        risultati[doc_id] = esito
        if esito["ok"]:
            verificati_ok += 1
        else:
            errori.append(
                f"Riga {idx} ({doc_id}): RT-07 {esito['esito']} "
                f"(atteso {esito['sha256_atteso']}, calcolato {esito['sha256_calcolato']})"
            )
    return risultati, errori, verificati_ok


# ============================================================================
# Validatore scheda F2 v0.5
# ============================================================================

def valida_csv_scheda_f2(
    lines_or_path: Any,
    modalita: str = "template",
    stop: Optional[str] = None,
    accetta_v02_20col: bool = False,
    corpus_base_dir: Optional[str | pathlib.Path] = None,
    doc_file_map: Optional[Dict[str, str]] = None,
    richiedi_verifica_disco: bool = False,
    sorgente_tipo: Optional[str] = None,
) -> Dict[str, Any]:
    if modalita not in ("template", "esecuzione"):
        raise ValueError("modalita deve essere 'template' o 'esecuzione'")
    if stop is not None and stop != "S2":
        raise ValueError("stop deve essere None o 'S2'")
    if not isinstance(accetta_v02_20col, bool):
        raise ValueError("accetta_v02_20col deve essere un booleano (True/False)")
    if not isinstance(richiedi_verifica_disco, bool):
        raise ValueError("richiedi_verifica_disco deve essere un booleano (True/False)")
    if doc_file_map is not None and not isinstance(doc_file_map, dict):
        raise ValueError("doc_file_map deve essere un dizionario {doc_id: percorso}")

    righe = _leggi_righe(lines_or_path, sorgente_tipo=sorgente_tipo)
    if not righe:
        return _risultato_validazione(False, "invalido", modalita, 0, 0, 0, 0, 0, ["File CSV vuoto"])

    header = list(righe[0])
    n_colonne = len(header)
    errori: List[str] = []

    if header == HEADER_ATTESO_22:
        schema_csv = "v0.5-22col"
        expected = 22
        colonne = HEADER_ATTESO_22
    elif header == HEADER_ATTESO_20 and accetta_v02_20col:
        schema_csv = "v0.2-20col"
        expected = 20
        colonne = HEADER_ATTESO_20
        if modalita == "esecuzione":
            errori.append(
                "F2: schema v0.2 a 20 colonne non ammesso in esecuzione; "
                "richiesto il foglio v0.5 a 22 colonne con estratto_fedele e polarita_fonte"
            )
    else:
        messaggio = (
            "Header non conforme: attese 22 colonne v0.5 specifiche"
            if not accetta_v02_20col
            else "Header non conforme: attese 22 colonne v0.5 oppure 20 colonne v0.2"
        )
        return _risultato_validazione(
            False, "invalido", modalita, n_colonne, 0, 0, 0, 0, [f"{messaggio}, trovate {n_colonne}"]
        )

    stati_validi = set(STATI_ORDINARI)
    if stop == "S2":
        stati_validi.add(STATO_BUDGET)

    docs_rows: List[Tuple[int, Dict[str, str]]] = []
    unit_rows: List[Tuple[int, Dict[str, str]]] = []
    righe_esempio = 0

    for idx, cols in enumerate(righe[1:], start=2):
        if len(cols) != expected:
            errori.append(f"Riga {idx}: numero colonne = {len(cols)} != {expected}")
            continue
        row = dict(zip(colonne, cols))
        if schema_csv == "v0.2-20col":
            row["estratto_fedele"] = ""
            row["polarita_fonte"] = ""

        if _ESEMPIO_MARKER in row.get("note", ""):
            righe_esempio += 1
            if modalita == "esecuzione":
                errori.append(
                    f"Riga {idx} ({row.get('id', '')}): riga di esempio non rimossa prima dell'esecuzione (F2)"
                )

        tipo_riga = row.get("tipo_riga", "")
        if tipo_riga == "DOCUMENTO":
            docs_rows.append((idx, row))
            accesso = row.get("stato_accesso", "")
            identita = row.get("identita_ok", "")
            errs, duplicati = _split_errs(row.get("tipo_errore", ""))

            if not row.get("id", ""):
                errori.append(f"Riga {idx}: DOCUMENTO privo di id")
            if accesso not in STATI_ACCESSO_DOC:
                errori.append(f"Riga {idx}: stato_accesso DOCUMENTO non valido '{accesso}'")
            if identita not in IDENTITA_AMMESSI:
                errori.append(f"Riga {idx}: identita_ok non valido '{identita}'")
            if modalita == "esecuzione" and identita not in ("sì", "no"):
                errori.append(f"Riga {idx}: identita_ok obbligatorio ('sì' o 'no') in esecuzione")
            if duplicati:
                errori.append(f"Riga {idx}: tipo_errore contiene codici duplicati '{row.get('tipo_errore', '')}'")
            invalidi = sorted(errs - CODICI_AMMESSI)
            if invalidi:
                errori.append(f"Riga {idx}: codici tipo_errore non validi {invalidi}")

            if accesso in ("full text", "abstract") and "E8" not in errs:
                hash_file = row.get("hash_file", "")
                if not hash_file:
                    errori.append(f"Riga {idx}: documento leggibile privo di hash_file (RT-07)")
                elif modalita == "esecuzione" and not _HEX64_RE.match(hash_file):
                    errori.append(
                        f"Riga {idx}: hash_file non è uno SHA-256 esadecimale a 64 caratteri (RT-07)"
                    )

            if schema_csv == "v0.5-22col":
                if row.get("estratto_fedele", "") != "":
                    errori.append(f"Riga {idx}: DOCUMENTO non ammette estratto_fedele (F2)")
                if row.get("polarita_fonte", "") != "":
                    errori.append(f"Riga {idx}: DOCUMENTO non ammette polarita_fonte (F2)")

        elif tipo_riga == "UNITA":
            unit_rows.append((idx, row))
            esito = row.get("esito", "")
            errs, duplicati = _split_errs(row.get("tipo_errore", ""))

            if row.get("source_kind", "") not in SOURCE_KIND_AMMESSI:
                errori.append(f"Riga {idx}: source_kind non valido '{row.get('source_kind', '')}'")
            if row.get("verification_status", "") not in VERIFICATION_STATUS_AMMESSI:
                errori.append(
                    f"Riga {idx}: verification_status non valido '{row.get('verification_status', '')}'"
                )
            if modalita == "esecuzione" and esito == "":
                errori.append(f"Riga {idx}: esito vuoto vietato alla chiusura")
            if esito and esito not in stati_validi:
                errori.append(f"Riga {idx}: esito '{esito}' non ammesso (stop={stop})")
            if row.get("verification_status", "") == "unverified_primary" and esito in GIUDICABILI:
                errori.append(f"Riga {idx}: unverified_primary non può avere esito giudicato '{esito}'")
            if modalita == "esecuzione" and esito in GIUDICABILI:
                if row.get("source_kind", "") != "primary_excerpt":
                    errori.append(
                        f"Riga {idx}: source_kind='{row.get('source_kind', '')}' non può sostenere un esito giudicato '{esito}' (richiesto 'primary_excerpt', S12-S16)"
                    )
                pos_dich = row.get("posizione_dichiarata", "").strip()
                if not pos_dich or pos_dich == "null / non verificate":
                    errori.append(
                        f"Riga {idx}: posizione_dichiarata obbligatoria e verificabile su unità giudicata '{esito}' (M2e)"
                    )
                if "E2" not in errs:
                    if row.get("posizione_verificata", "") != "sì" or row.get("link_risolvibile", "") != "sì":
                        errori.append(
                            f"Riga {idx}: unità giudicata '{esito}' richiede posizione_verificata='sì' e link_risolvibile='sì' (salvo errore E2 documentato, M2e)"
                        )
            if duplicati:
                errori.append(f"Riga {idx}: tipo_errore contiene codici duplicati '{row.get('tipo_errore', '')}'")
            invalidi = sorted(errs - CODICI_AMMESSI)
            if invalidi:
                errori.append(f"Riga {idx}: codici tipo_errore non validi {invalidi}")

            if schema_csv == "v0.5-22col":
                estratto = row.get("estratto_fedele", "")
                polarita = row.get("polarita_fonte", "")
                if esito in ("verifica non possibile", STATO_BUDGET):
                    if estratto != "":
                        errori.append(
                            f"Riga {idx}: estratto_fedele vietato su esito '{esito}' (unità non verificata)"
                        )
                    if polarita != "":
                        errori.append(
                            f"Riga {idx}: polarita_fonte vietata su esito '{esito}' (unità non verificata)"
                        )
                elif esito in GIUDICABILI:
                    if modalita == "esecuzione":
                        if estratto not in ESTRATTO_FEDELE_AMMESSI:
                            errori.append(
                                f"Riga {idx}: estratto_fedele obbligatorio in esecuzione su unità giudicata"
                            )
                        if polarita not in POLARITA_AMMESSE:
                            errori.append(
                                f"Riga {idx}: polarita_fonte obbligatoria in esecuzione su unità giudicata"
                            )
                    else:
                        if estratto and estratto not in ESTRATTO_FEDELE_AMMESSI:
                            errori.append(f"Riga {idx}: estratto_fedele non ammesso '{estratto}'")
                        if polarita and polarita not in POLARITA_AMMESSE:
                            errori.append(f"Riga {idx}: polarita_fonte non ammessa '{polarita}'")
                    if estratto == "sì" and (errs & FEDELTA_ERR):
                        errori.append(
                            f"Riga {idx}: RT-03: estratto_fedele='sì' incompatibile con "
                            f"codici di infedeltà {sorted(errs & FEDELTA_ERR)}"
                        )
                    # R01: simmetria semantica su estratto_fedele='no'
                    # Nota R02 (convenzione di protocollo): polarita_fonte='contraria' indica la direzione
                    # empirica della fonte rispetto alla tesi generale del dossier, mentre esito='supporta'
                    # valuta lo specifico claim locale estratto (es. il dossier riporta fedelmente una
                    # fonte contraria): la combinazione supporta + contraria e' pertanto legittima.
                    if estratto == "no":
                        if esito in ("supporta", "parziale"):
                            errori.append(
                                f"Riga {idx}: RT-03: estratto_fedele='no' incompatibile con esito '{esito}' "
                                "(un estratto infedele non può supportare neppure parzialmente il claim)"
                            )
                        if modalita == "esecuzione" and not (errs & FEDELTA_ERR):
                            errori.append(
                                f"Riga {idx}: RT-03: estratto_fedele='no' richiede almeno un codice di infedeltà "
                                f"in tipo_errore ({sorted(FEDELTA_ERR)})"
                            )
                else:
                    if estratto and estratto not in ESTRATTO_FEDELE_AMMESSI:
                        errori.append(f"Riga {idx}: estratto_fedele non ammesso '{estratto}'")
                    if polarita and polarita not in POLARITA_AMMESSE:
                        errori.append(f"Riga {idx}: polarita_fonte non ammessa '{polarita}'")
        else:
            errori.append(f"Riga {idx}: tipo_riga sconosciuto '{tipo_riga}'")

    documenti: Dict[str, Dict[str, str]] = {}
    for idx, row in docs_rows:
        doc_id = row.get("id", "")
        if doc_id in documenti:
            errori.append(f"Riga {idx}: id DOCUMENTO duplicato '{doc_id}'")
        else:
            documenti[doc_id] = row

    unita_ids: set = set()
    for idx, row in unit_rows:
        uid = row.get("id", "")
        if not uid:
            errori.append(f"Riga {idx}: UNITA priva di id")
        elif uid in unita_ids:
            errori.append(f"Riga {idx}: id UNITA duplicato '{uid}'")
        else:
            unita_ids.add(uid)

        documento_id = row.get("documento_id", "")
        if not documento_id:
            errori.append(f"Riga {idx}: UNITA priva di documento_id")
            continue
        doc_row = documenti.get(documento_id)
        if doc_row is None and modalita == "esecuzione" and documenti:
            errori.append(
                f"Riga {idx}: documento_id '{documento_id}' non dichiarato tra le righe DOCUMENTO"
            )

        esito = row.get("esito", "")
        errs, _ = _split_errs(row.get("tipo_errore", ""))
        doc_accesso = doc_row.get("stato_accesso", "") if doc_row is not None else ""

        if doc_accesso in ("non disponibile", "metadato") and esito in GIUDICABILI:
            errori.append(
                f"Riga {idx}: unità giudicata '{esito}' su documento '{doc_accesso}' privo di testo verificabile (promozione indebita, S17-S19)"
            )
        if doc_accesso == "metadato" and row.get("stato_accesso", "") in ("abstract", "full text"):
            errori.append(
                f"Riga {idx}: promozione indebita metadato -> {row.get('stato_accesso', '')} (§11)"
            )
        if doc_accesso == "abstract" and row.get("stato_accesso", "") == "full text":
            errori.append(
                f"Riga {idx}: promozione indebita abstract -> full text (§11)"
            )
        non_acquisito = row.get("stato_accesso", "").startswith("non acquisito") or (
            doc_accesso in ("non disponibile", "metadato")
        )
        if esito == "verifica non possibile" and non_acquisito and errs:
            errori.append(
                f"Riga {idx}: RT-VNP violato, codice errore {sorted(errs)} su primario non acquisito o solo metadato"
            )

    if modalita == "esecuzione":
        if not docs_rows:
            errori.append("F2: il foglio di esecuzione deve contenere almeno una riga DOCUMENTO")
        if not unit_rows:
            errori.append("F2: il foglio di esecuzione deve contenere almeno una riga UNITA")

    hash_ok = 0
    risultati_disco, errori_disco, hash_ok = _verifica_documenti_su_disco(
        docs_rows, corpus_base_dir, doc_file_map
    )
    errori.extend(errori_disco)

    if modalita == "esecuzione" and richiedi_verifica_disco:
        n_doc_leggibili = sum(
            1
            for _, drow in docs_rows
            if drow.get("stato_accesso", "") in ("full text", "abstract")
            and "E8" not in _split_errs(drow.get("tipo_errore", ""))[0]
        )
        if n_doc_leggibili > 0 and (corpus_base_dir is None and doc_file_map is None):
            errori.append(
                "RT-07: verifica SHA-256 reale su disco obbligatoria in esecuzione "
                "(fornire corpus_base_dir e/o doc_file_map per i documenti leggibili)"
            )
        elif hash_ok < n_doc_leggibili:
            errori.append(
                f"RT-07: hash_verificati_su_disco ({hash_ok}) < documenti leggibili ({n_doc_leggibili})"
            )

    return _risultato_validazione(
        len(errori) == 0,
        schema_csv,
        modalita,
        n_colonne,
        len(docs_rows),
        len(unit_rows),
        righe_esempio,
        hash_ok,
        errori,
    )


# ============================================================================
# Bridge verso il motore v0.3
# ============================================================================

def _valida_int_puro(nome: str, valore: Any, minimo: int = 0) -> int:
    if isinstance(valore, bool) or not isinstance(valore, int) or valore < minimo:
        raise ValueError(f"{nome} deve essere un intero >= {minimo} (bool escluso); ricevuto: {valore!r}")
    return valore


def carica_foglio_audit_csv(
    lines_or_path: Any,
    *,
    corpus_target: int = 20,
    sostituzioni_dichiarate: int = 0,
    contraddizioni_conservate: Optional[int] = None,
    prep_tentati: Optional[int] = None,
    tempi_A: Optional[List[float]] = None,
    tempi_B: Optional[List[float]] = None,
    coppie_F5: Optional[List[Tuple[str, str]]] = None,
    stop: Optional[str] = None,
    audit_count: int = 1,
    ciclo: str = "v0.5",
    corpus_base_dir: Optional[str | pathlib.Path] = None,
    doc_file_map: Optional[Dict[str, str]] = None,
    consenti_hash_solo_dichiarato: bool = False,
    richiedi_verifica_disco: bool = False,
    sorgente_tipo: Optional[str] = None,
) -> Dict[str, Any]:
    _valida_int_puro("corpus_target", corpus_target, minimo=1)
    _valida_int_puro("sostituzioni_dichiarate", sostituzioni_dichiarate, minimo=0)
    _valida_int_puro("audit_count", audit_count, minimo=1)
    if prep_tentati is not None:
        _valida_int_puro("prep_tentati", prep_tentati, minimo=0)
    if contraddizioni_conservate is not None:
        _valida_int_puro("contraddizioni_conservate", contraddizioni_conservate, minimo=0)
    if not isinstance(consenti_hash_solo_dichiarato, bool):
        raise ValueError("consenti_hash_solo_dichiarato deve essere un booleano (True/False)")
    if not isinstance(richiedi_verifica_disco, bool):
        raise ValueError("richiedi_verifica_disco deve essere un booleano (True/False)")
    if not isinstance(ciclo, str) or not ciclo.strip():
        raise ValueError("ciclo deve essere una stringa non vuota")

    validazione = valida_csv_scheda_f2(
        lines_or_path,
        modalita="esecuzione",
        stop=stop,
        accetta_v02_20col=False,
        corpus_base_dir=corpus_base_dir,
        doc_file_map=doc_file_map,
        richiedi_verifica_disco=richiedi_verifica_disco,
        sorgente_tipo=sorgente_tipo,
    )
    if not validazione["valido"]:
        raise ValueError("Scheda F2 non valida: " + " | ".join(validazione["errori"]))

    righe = _leggi_righe(lines_or_path, sorgente_tipo=sorgente_tipo)
    header = righe[0]
    righe_dati = [dict(zip(header, cols)) for cols in righe[1:] if len(cols) == len(header)]
    docs_rows = [(idx, row) for idx, row in enumerate(righe_dati, start=2) if row["tipo_riga"] == "DOCUMENTO"]
    unit_rows = [(idx, row) for idx, row in enumerate(righe_dati, start=2) if row["tipo_riga"] == "UNITA"]

    v03 = _carica_motore_v03()

    risultati_disco: Dict[str, Dict[str, Any]] = {}
    if corpus_base_dir is not None or doc_file_map is not None:
        risultati_disco, _, _ = _verifica_documenti_su_disco(
            docs_rows, corpus_base_dir, doc_file_map
        )

    docs: List[Dict[str, Any]] = []
    for _, row in docs_rows:
        errs, _ = _split_errs(row.get("tipo_errore", ""))
        doc_id = row["id"]
        accesso = row.get("stato_accesso", "")
        identita_si = row.get("identita_ok", "") == "sì"
        doc_leggibile = accesso in ("full text", "abstract") and ("E8" not in errs)
        if doc_id in risultati_disco:
            hash_coincide = bool(risultati_disco[doc_id]["ok"])
        elif consenti_hash_solo_dichiarato:
            hash_coincide = bool(row.get("hash_file", "")) and identita_si
        else:
            # CR-02 + R05: fail-closed di default — senza riscontro reale su disco, l'hash NON risulta verificato
            hash_coincide = False
        # ME-06: M1 non tautologico — per i documenti leggibili richiede identita_ok e verifica dell'hash
        prov_verificata = (identita_si and hash_coincide) if doc_leggibile else identita_si
        docs.append(
            v03.doc(
                doc_id,
                ok=identita_si,
                accesso=accesso,
                prov=prov_verificata,
                hash_file=row.get("hash_file", ""),
                hash_coincide=hash_coincide,
                errore_prep_E8=("E8" in errs),
                motivo_E8=(row.get("note", "") or "E8 registrato in scheda") if "E8" in errs else "",
            )
        )

    units: List[Dict[str, Any]] = []
    for _, row in unit_rows:
        errs, _ = _split_errs(row.get("tipo_errore", ""))
        esito = row.get("esito", "")
        link_ok = row.get("link_risolvibile", "") == "sì" and row.get("posizione_verificata", "") == "sì"
        unita = v03.unit(
            row["id"],
            esito,
            numerica=(row.get("tipo_unita", "") in ("quantitativa", "numerica") or "E7" in errs),
            inventato=("E7" in errs),
            link=link_ok,
            tipo_errore=row.get("tipo_errore", ""),
            ciclo=ciclo,
        )
        unita["link_prodotto"] = (
            (esito in GIUDICABILI and "E2" not in errs)
            or (
                not row.get("stato_accesso", "").startswith("non acquisito")
                and row.get("posizione_dichiarata", "") not in ("", "null / non verificate")
            )
        )
        unita["estratto_fedele"] = row.get("estratto_fedele", "") == "sì"
        unita["polarita_fonte"] = row.get("polarita_fonte", "")
        unita["lettore"] = row.get("lettore", "")
        unita["revisione_indipendente"] = row.get("revisione_indipendente", "")
        unita["adjudicazione"] = row.get("adjudicazione", "")
        unita["tempo_min"] = row.get("tempo_min", "")
        unita["stato_accesso"] = row.get("stato_accesso", "")
        unita["documento_id"] = row.get("documento_id", "")
        units.append(unita)

    if coppie_F5 is None:
        coppie_auto = [
            (row.get("esito", ""), row.get("revisione_indipendente", ""))
            for _, row in unit_rows
            if row.get("revisione_indipendente", "") in STATI_ORDINARI
        ]
        coppie_F5 = coppie_auto or None

    contraddizioni_rilevate = sum(
        1
        for _, row in unit_rows
        if row.get("esito", "") in GIUDICABILI
        and (
            row.get("polarita_fonte", "") in ("contraria", "mista")
            or row.get("esito", "") == "contrasta"
        )
    )
    if contraddizioni_conservate is None:
        if contraddizioni_rilevate > 0:
            raise ValueError(
                "Con contraddizioni_rilevate > 0 specificare esplicitamente "
                f"contraddizioni_conservate (0..{contraddizioni_rilevate}) "
                "per il calcolo non tautologico di M8"
            )
        contraddizioni_conservate = 0
    else:
        contraddizioni_conservate = _valida_int_puro("contraddizioni_conservate", contraddizioni_conservate, minimo=0)
        if contraddizioni_conservate < 0 or contraddizioni_conservate > contraddizioni_rilevate:
            raise ValueError(
                f"contraddizioni_conservate={contraddizioni_conservate} fuori intervallo "
                f"(0..{contraddizioni_rilevate})"
            )

    e8_count = sum(1 for d in docs if d.get("errore_prep_E8"))
    if prep_tentati is None:
        prep_tentati_eff = len(docs) if docs else corpus_target
    else:
        prep_tentati_eff = prep_tentati

    foglio = v03.sheet(
        docs,
        units,
        subs=sostituzioni_dichiarate,
        target=corpus_target,
        contrad=(contraddizioni_rilevate, contraddizioni_conservate),
        prep=(e8_count, prep_tentati_eff),
        tempiA=tempi_A or [],
        tempiB=tempi_B or [],
        coppie_F5=coppie_F5,
        ciclo=ciclo,
        audit_count=audit_count,
        stop=stop,
    )
    foglio["hash_verificati_su_disco"] = sum(
        1 for esito in risultati_disco.values() if esito["ok"]
    )
    foglio["validazione_csv"] = validazione
    return foglio


def valuta_foglio_audit_csv(
    lines_or_path: Any,
    *,
    corpus_target: int = 20,
    sostituzioni_dichiarate: int = 0,
    contraddizioni_conservate: Optional[int] = None,
    prep_tentati: Optional[int] = None,
    tempi_A: Optional[List[float]] = None,
    tempi_B: Optional[List[float]] = None,
    coppie_F5: Optional[List[Tuple[str, str]]] = None,
    stop: Optional[str] = None,
    audit_count: int = 1,
    ciclo: str = "v0.5",
    corpus_base_dir: Optional[str | pathlib.Path] = None,
    doc_file_map: Optional[Dict[str, str]] = None,
    consenti_hash_solo_dichiarato: bool = False,
    richiedi_verifica_disco: bool = False,
    sorgente_tipo: Optional[str] = None,
    quota_min: float = 0.80,
) -> Dict[str, Any]:
    validazione = valida_csv_scheda_f2(
        lines_or_path,
        modalita="esecuzione",
        stop=stop,
        accetta_v02_20col=False,
        corpus_base_dir=corpus_base_dir,
        doc_file_map=doc_file_map,
        richiedi_verifica_disco=richiedi_verifica_disco,
        sorgente_tipo=sorgente_tipo,
    )
    foglio = carica_foglio_audit_csv(
        lines_or_path,
        corpus_target=corpus_target,
        sostituzioni_dichiarate=sostituzioni_dichiarate,
        contraddizioni_conservate=contraddizioni_conservate,
        prep_tentati=prep_tentati,
        tempi_A=tempi_A,
        tempi_B=tempi_B,
        coppie_F5=coppie_F5,
        stop=stop,
        audit_count=audit_count,
        ciclo=ciclo,
        corpus_base_dir=corpus_base_dir,
        doc_file_map=doc_file_map,
        consenti_hash_solo_dichiarato=consenti_hash_solo_dichiarato,
        richiedi_verifica_disco=richiedi_verifica_disco,
        sorgente_tipo=sorgente_tipo,
    )
    v03 = _carica_motore_v03()
    v03.metriche3(foglio)
    accettazione = v03.accettazione3(foglio, quota_min=quota_min)
    return {
        "validazione_csv": validazione,
        "foglio": foglio,
        "accettazione_v03": accettazione,
    }


# ============================================================================
# Test deterministici F2-01..F2-nn
# ============================================================================

_HASH_ZERO = "0" * 64
_HASH_V02_CONGELATO = "fca7792b65b8f652062cc90f74648b283116f3c11aaecc4978c2110c9bfe68b0"
_CORPUS_BASE = _PACKAGE_DIR / "data"  # corpus sintetico: i full text reali non sono ridistribuibili
_FILE_REALI = [
    (
        "S01",
        "corpus_sintetico/s01_sintetico.xml",
        "e718a569f4c35ec12217e3555e058a330b5ecb5d5cd88f7c2360d6ab43015eb8",
        4070,
    ),
    (
        "S03",
        "corpus_sintetico/s03_sintetico.xml",
        "d769afa13cfa87a7b25dd0e967bf7c74df61ff6e9cecf876c137b40dfd1ea369",
        4070,
    ),
    (
        "S05",
        "corpus_sintetico/s05_sintetico.xml",
        "05535151099e1d2da3bab560b5976504d475cec3edaef3a38ebb6a82f4db3019",
        4070,
    ),
]


def _encode_riga(campi: List[str]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";", quotechar='"', lineterminator="")
    writer.writerow(campi)
    return buffer.getvalue()


def _riga_doc(
    doc_id: str = "DOC-001",
    stato: str = "full text",
    identita: str = "sì",
    hash_file: str = _HASH_ZERO,
    errore: str = "",
    note: str = "",
    estratto: str = "",
    polarita: str = "",
) -> str:
    campi = {h: "" for h in HEADER_ATTESO_22}
    campi.update(
        {
            "tipo_riga": "DOCUMENTO",
            "id": doc_id,
            "stato_accesso": stato,
            "identita_ok": identita,
            "hash_file": hash_file,
            "tipo_errore": errore,
            "note": note,
            "estratto_fedele": estratto,
            "polarita_fonte": polarita,
        }
    )
    return _encode_riga([campi[h] for h in HEADER_ATTESO_22])


def _riga_unita(
    uid: str,
    esito: str = "supporta",
    doc_id: str = "DOC-001",
    stato: str = "full text",
    source_kind: str = "primary_excerpt",
    verification: str = "verified_primary",
    posizione: str = "p. 1",
    posizione_verificata: str = "sì",
    link: str = "sì",
    errore: str = "",
    estratto: str = "sì",
    polarita: str = "a_favore",
    lettore: str = "R1",
    revisore: str = "",
    tempo: str = "10",
    note: str = "",
    tipo_unita: str = "claim",
    voce: str = "affermazione di prova",
) -> str:
    campi = {h: "" for h in HEADER_ATTESO_22}
    campi.update(
        {
            "tipo_riga": "UNITA",
            "id": uid,
            "documento_id": doc_id,
            "voce_o_affermazione": voce,
            "tipo_unita": tipo_unita,
            "source_kind": source_kind,
            "verification_status": verification,
            "stato_accesso": stato,
            "posizione_dichiarata": posizione,
            "posizione_verificata": posizione_verificata,
            "link_risolvibile": link,
            "esito": esito,
            "tipo_errore": errore,
            "tempo_min": tempo,
            "lettore": lettore,
            "revisione_indipendente": revisore,
            "note": note,
            "estratto_fedele": estratto,
            "polarita_fonte": polarita,
        }
    )
    return _encode_riga([campi[h] for h in HEADER_ATTESO_22])


def _csv_da(righe: List[str]) -> str:
    return "\n".join([_encode_riga(HEADER_ATTESO_22)] + list(righe)) + "\n"


def _foglio_base(
    n_supporta: int = 6,
    n_parziale: int = 3,
    n_contrasta: int = 1,
    revisore_contrasta: str = "",
) -> str:
    righe = [_riga_doc()]
    contatore = 0
    for _ in range(n_supporta):
        contatore += 1
        righe.append(_riga_unita(f"E-{contatore:03d}"))
    for _ in range(n_parziale):
        contatore += 1
        righe.append(_riga_unita(f"E-{contatore:03d}", esito="parziale"))
    for _ in range(n_contrasta):
        contatore += 1
        righe.append(
            _riga_unita(
                f"E-{contatore:03d}",
                esito="contrasta",
                polarita="contraria",
                revisore=revisore_contrasta,
            )
        )
    return _csv_da(righe)


def esegui_test_f2() -> List[Dict[str, Any]]:
    checks: List[Dict[str, Any]] = []

    def check(cid: str, descrizione: str, funzione) -> None:
        try:
            ok, dettaglio = funzione()
        except Exception as exc:
            ok, dettaglio = False, f"eccezione {type(exc).__name__}: {exc}"
        checks.append(
            {
                "id": cid,
                "descrizione": descrizione,
                "ok": bool(ok),
                "esito": "PASS" if ok else "FAIL",
                "dettaglio": str(dettaglio),
            }
        )

    def t01():
        righe = _leggi_righe(CSV_SCHEDA_V05)
        ok = len(righe[0]) == 22 and righe[0] == HEADER_ATTESO_22
        return ok, f"colonne={len(righe[0])}"

    def t02():
        r = valida_csv_scheda_f2(CSV_SCHEDA_V05, modalita="template")
        ok = (
            r["valido"]
            and r["schema_csv"] == "v0.5-22col"
            and r["righe_esempio"] == 2
            and r["righe_documento"] == 1
            and r["righe_unita"] == 1
        )
        return ok, f"valido={r['valido']} schema={r['schema_csv']} esempio={r['righe_esempio']}"

    def t03():
        r = valida_csv_scheda_f2(CSV_SCHEDA_V05, modalita="esecuzione")
        ok = (not r["valido"]) and r["righe_esempio"] == 2 and any("esempio" in e.lower() for e in r["errori"])
        return ok, f"valido={r['valido']} errori={len(r['errori'])}"

    def t04():
        digest = hashlib.sha256(CSV_SCHEDA_V02.read_bytes()).hexdigest()
        return digest == _HASH_V02_CONGELATO, digest

    def t05():
        r = valida_csv_scheda_f2(CSV_SCHEDA_V02, modalita="template", accetta_v02_20col=True)
        ok = r["valido"] and r["schema_csv"] == "v0.2-20col" and r["n_colonne"] == 20
        return ok, f"valido={r['valido']} schema={r['schema_csv']}"

    def t06():
        r = valida_csv_scheda_f2(CSV_SCHEDA_V02, modalita="esecuzione", accetta_v02_20col=True)
        ok = (not r["valido"]) and any("F2" in e for e in r["errori"])
        return ok, f"valido={r['valido']} errori={r['errori'][:1]}"

    def t07():
        esiti = {}
        for codice in ("E1", "E2", "E3", "E6"):
            testo = _csv_da([_riga_doc(), _riga_unita("E-001", errore=codice)])
            r = valida_csv_scheda_f2(testo, modalita="esecuzione")
            esiti[codice] = (not r["valido"]) and any("RT-03" in e for e in r["errori"])
        return all(esiti.values()), esiti

    def t08():
        testi = [
            _csv_da([_riga_doc(), _riga_unita("E-001", errore="E4")]),
            _csv_da([_riga_doc(), _riga_unita("E-001", errore="E7", polarita="mista")]),
        ]
        risultati = [valida_csv_scheda_f2(t, modalita="esecuzione")["valido"] for t in testi]
        return all(risultati), risultati

    def _foglio_reale_s01() -> Tuple[str, Dict[str, str]]:
        doc_id, rel, sha, _ = _FILE_REALI[0]
        righe = [_riga_doc(doc_id=doc_id, hash_file=sha, note="fonte reale congelata")]
        for i in range(1, 7):
            righe.append(_riga_unita(f"E-{i:03d}", doc_id=doc_id))
        for i in range(7, 10):
            righe.append(_riga_unita(f"E-{i:03d}", doc_id=doc_id, esito="parziale"))
        righe.append(_riga_unita("E-010", doc_id=doc_id, esito="contrasta", polarita="contraria"))
        return _csv_da(righe), {doc_id: rel}

    def t09():
        testo, mappa_s01 = _foglio_reale_s01()
        val = valida_csv_scheda_f2(
            testo, modalita="esecuzione", corpus_base_dir=_CORPUS_BASE, doc_file_map=mappa_s01, richiedi_verifica_disco=True
        )
        foglio = carica_foglio_audit_csv(
            testo, contraddizioni_conservate=1, corpus_base_dir=_CORPUS_BASE, doc_file_map=mappa_s01
        )
        v03 = _carica_motore_v03()
        m = v03.metriche3(foglio)
        acc = v03.accettazione3(foglio)
        # CR-02: senza verifica su disco, un foglio sintetico con hash fittizio DEVE fallire strutturalmente
        foglio_no_disco = carica_foglio_audit_csv(_foglio_base(), contraddizioni_conservate=1)
        acc_no_disco = v03.accettazione3(foglio_no_disco)
        ok = (
            val["valido"]
            and foglio["hash_verificati_su_disco"] == 1
            and abs(m["M3"]["val"] - 0.6) < 1e-12
            and m["M3f"]["val"] == 1.0
            and m["M8"]["val"] == 1.0
            and foglio["contraddizioni_rilevate"] == 1
            and acc["esito"] == "accettata"
            and acc_no_disco["esito"] == "fallimento_strutturale"
        )
        return ok, f"M3={m['M3']['val']} M3f={m['M3f']['val']} M8={m['M8']['val']} acc={acc['esito']} no_disco={acc_no_disco['esito']}"

    def t10():
        try:
            carica_foglio_audit_csv(_foglio_base(), contraddizioni_conservate=None)
        except ValueError as exc:
            return "contraddizioni_conservate" in str(exc), str(exc)
        return False, "nessuna ValueError"

    def t11():
        testo, mappa_s01 = _foglio_reale_s01()
        foglio = carica_foglio_audit_csv(
            testo, contraddizioni_conservate=0, corpus_base_dir=_CORPUS_BASE, doc_file_map=mappa_s01
        )
        v03 = _carica_motore_v03()
        m = v03.metriche3(foglio)
        acc = v03.accettazione3(foglio)
        ok = m["M8"]["val"] == 0.0 and acc["esito"] == "non_accettabile"
        return ok, f"M8={m['M8']['val']} acc={acc['esito']}"

    def t12():
        casi = [
            _riga_unita(
                "E-001",
                esito="verifica non possibile",
                stato="non acquisito (nota v0.1: F)",
                source_kind="dossier_paraphrase",
                verification="unverified_primary",
                posizione="null / non verificate",
                posizione_verificata="no",
                link="no",
                estratto="sì",
                polarita="",
            ),
            _riga_unita(
                "E-001",
                esito="verifica non possibile",
                stato="non acquisito (nota v0.1: F)",
                source_kind="dossier_paraphrase",
                verification="unverified_primary",
                posizione="null / non verificate",
                posizione_verificata="no",
                link="no",
                estratto="",
                polarita="a_favore",
            ),
        ]
        risultati = []
        for riga in casi:
            r = valida_csv_scheda_f2(_csv_da([_riga_doc(), riga]), modalita="esecuzione")
            risultati.append(not r["valido"])
        return all(risultati), risultati

    def t13():
        riga = _riga_unita("E-001", esito=STATO_BUDGET, estratto="sì", polarita="contraria")
        r = valida_csv_scheda_f2(_csv_da([_riga_doc(), riga]), modalita="esecuzione", stop="S2")
        return (not r["valido"]) and any("estratto_fedele" in e for e in r["errori"]), r["errori"]

    def t14():
        r1 = valida_csv_scheda_f2(
            _csv_da([_riga_doc(estratto="sì")]), modalita="esecuzione"
        )
        r2 = valida_csv_scheda_f2(
            _csv_da([_riga_doc(polarita="mista")]), modalita="esecuzione"
        )
        return (not r1["valido"]) and (not r2["valido"]), [r1["errori"][:1], r2["errori"][:1]]

    def t15():
        doc = _riga_doc(stato="abstract")
        unita = _riga_unita("E-001", stato="full text")
        r = valida_csv_scheda_f2(_csv_da([doc, unita]), modalita="esecuzione")
        return (not r["valido"]) and any("promozione indebita" in e for e in r["errori"]), r["errori"]

    def t16():
        doc = _riga_doc(stato="non disponibile", hash_file="")
        unita = _riga_unita("E-001", stato="abstract")
        r = valida_csv_scheda_f2(_csv_da([doc, unita]), modalita="esecuzione")
        return (not r["valido"]) and any("non disponibile" in e for e in r["errori"]), r["errori"]

    def t17():
        righe = _foglio_base().splitlines()
        righe[-1] = righe[-1] + ";extra"
        r = valida_csv_scheda_f2("\n".join(righe), modalita="esecuzione")
        return (not r["valido"]) and any("numero colonne = 23" in e for e in r["errori"]), r["errori"]

    def t18():
        doc = _riga_doc()
        u1 = _riga_unita("E-001")
        u2 = _riga_unita("E-001", esito="parziale")
        r1 = valida_csv_scheda_f2(_csv_da([doc, u1, u2]), modalita="esecuzione")
        r2 = valida_csv_scheda_f2(
            _csv_da([doc, _riga_unita("E-002", doc_id="DOC-999")]), modalita="esecuzione"
        )
        return (
            (not r1["valido"])
            and any("duplicato" in e for e in r1["errori"])
            and (not r2["valido"])
            and any("non dichiarato" in e for e in r2["errori"]),
            [r1["errori"][:1], r2["errori"][:1]],
        )

    def t19():
        risultati = []
        for doc_id, rel, sha, dimensione in _FILE_REALI[:1]:
            esito = verifica_sha256_documento(
                pathlib.Path(rel), sha, base_dir=_CORPUS_BASE
            )
            risultati.append(
                esito["ok"]
                and esito["sha256_calcolato"] == sha
                and esito["bytes"] == dimensione
                and not esito["errore_E8"]
            )
        return all(risultati), risultati

    def t20():
        risultati = []
        for doc_id, rel, sha, dimensione in _FILE_REALI[1:]:
            esito = verifica_sha256_documento(
                pathlib.Path(rel), sha, base_dir=_CORPUS_BASE
            )
            risultati.append(
                esito["ok"]
                and esito["sha256_calcolato"] == sha
                and esito["bytes"] == dimensione
                and not esito["errore_E8"]
            )
        return all(risultati), risultati

    def t21():
        _, rel, sha, _ = _FILE_REALI[0]
        alterato = ("0" if sha[0] != "0" else "1") + sha[1:]
        esito = verifica_sha256_documento(pathlib.Path(rel), alterato, base_dir=_CORPUS_BASE)
        ok = (not esito["ok"]) and (not esito["errore_E8"]) and esito["sha256_calcolato"] == sha
        return ok, esito["esito"]

    def t22():
        try:
            verifica_sha256_documento(
                pathlib.Path("../Diotima_protocollo_pilota_v0.2.md"),
                _HASH_ZERO,
                base_dir=_CORPUS_BASE,
            )
        except ValueError as exc:
            return "Path traversal" in str(exc), str(exc)
        return False, "nessuna ValueError"

    def t23():
        import tempfile
        inesistente = verifica_sha256_documento(
            pathlib.Path("corpus_sintetico/non_esiste.xml"), _HASH_ZERO, base_dir=_CORPUS_BASE
        )
        with tempfile.TemporaryDirectory() as td:
            vuoto_p = pathlib.Path(td) / "vuoto.bin"
            vuoto_p.write_bytes(b"")
            esito_vuoto = verifica_sha256_documento(pathlib.Path("vuoto.bin"), _HASH_ZERO, base_dir=pathlib.Path(td))
        try:
            verifica_sha256_documento(pathlib.Path("x"), "abc", base_dir=_CORPUS_BASE)
            hash_breve = False
        except ValueError:
            hash_breve = True
        ok = (
            (not inesistente["errore_E8"])
            and (not inesistente["ok"])
            and ("/" not in inesistente["esito"])
            and esito_vuoto["errore_E8"]
            and (not esito_vuoto["ok"])
            and hash_breve
        )
        return ok, f"missing_E8={inesistente['errore_E8']} empty_E8={esito_vuoto['errore_E8']} hash_breve={hash_breve}"

    def t24():
        testo = _csv_da(
            [
                _riga_doc(),
                _riga_unita("E-001", voce="claim con; punto e virgola"),
            ]
        )
        righe = _leggi_righe(testo)
        r = valida_csv_scheda_f2(testo, modalita="esecuzione")
        ok = (
            len(righe) == 3
            and len(righe[2]) == 22
            and righe[2][3] == "claim con; punto e virgola"
            and r["valido"]
        )
        return ok, f"colonne_unita={len(righe[2])} valido={r['valido']}"

    def t25():
        righe = []
        mapping = {}
        for doc_id, rel, sha, _ in _FILE_REALI:
            righe.append(_riga_doc(doc_id=doc_id, hash_file=sha, note="fonte reale congelata"))
            mapping[doc_id] = rel
        for doc_id, _, _, _ in _FILE_REALI:
            righe.append(_riga_unita(f"E-{doc_id}", doc_id=doc_id))
        testo = _csv_da(righe)
        val = valida_csv_scheda_f2(
            testo,
            modalita="esecuzione",
            corpus_base_dir=_CORPUS_BASE,
            doc_file_map=mapping,
        )
        foglio = carica_foglio_audit_csv(
            testo,
            contraddizioni_conservate=0,
            corpus_base_dir=_CORPUS_BASE,
            doc_file_map=mapping,
        )
        ok = (
            val["valido"]
            and val["hash_verificati_su_disco"] == 3
            and foglio["hash_verificati_su_disco"] == 3
        )
        return ok, f"valido={val['valido']} verificati={val['hash_verificati_su_disco']}"

    def t26():
        testo = _csv_da([_riga_doc(doc_id="S01", hash_file=_FILE_REALI[0][2])])
        r = valida_csv_scheda_f2(
            testo,
            modalita="esecuzione",
            corpus_base_dir=_CORPUS_BASE,
            doc_file_map={},
        )
        return (not r["valido"]) and any("doc_file_map" in e for e in r["errori"]), r["errori"]

    def t27():
        try:
            valida_csv_scheda_f2(_foglio_base(), modalita="altro")
            m = False
        except ValueError:
            m = True
        try:
            valida_csv_scheda_f2(_foglio_base(), modalita="esecuzione", stop="S1")
            s = False
        except ValueError:
            s = True
        return m and s, f"modalita={m} stop={s}"

    def t28():
        testo = _foglio_base(revisore_contrasta="parziale")
        foglio = carica_foglio_audit_csv(testo, contraddizioni_conservate=1)
        v03 = _carica_motore_v03()
        m = v03.metriche3(foglio)
        ok = (
            foglio["coppie_F5"] == [("contrasta", "parziale")]
            and m["M7"]["calcolabile"]
            and m["M7"]["n_coppie"] == 1
        )
        return ok, f"coppie={foglio['coppie_F5']} M7={m['M7']['calcolabile']}"

    def t29():
        riga = _riga_unita("E-001", esito=STATO_BUDGET, estratto="", polarita="")
        testo = _csv_da([_riga_doc(), riga])
        con_s2 = valida_csv_scheda_f2(testo, modalita="esecuzione", stop="S2")
        senza_s2 = valida_csv_scheda_f2(testo, modalita="esecuzione")
        foglio = carica_foglio_audit_csv(testo, stop="S2")
        ok = con_s2["valido"] and (not senza_s2["valido"]) and foglio["stop"] == "S2"
        return ok, f"S2={con_s2['valido']} senza_S2={senza_s2['valido']}"

    def t30():
        v05 = valida_csv_scheda_f2(CSV_SCHEDA_V05, modalita="template", accetta_v02_20col=False)
        v02 = valida_csv_scheda_f2(CSV_SCHEDA_V02, modalita="template", accetta_v02_20col=False)
        ok = v05["valido"] and (not v02["valido"])
        return ok, f"v0.5={v05['valido']} v0.2_senza_flag={v02['valido']}"

    def t31():
        import json as _json
        testo, mappa_s01 = _foglio_reale_s01()
        risultato = valuta_foglio_audit_csv(
            testo, contraddizioni_conservate=1, corpus_base_dir=_CORPUS_BASE, doc_file_map=mappa_s01
        )
        dump = _json.dumps(risultato, ensure_ascii=False)
        chiavi = set(risultato) == {"validazione_csv", "foglio", "accettazione_v03"}
        ok = (
            chiavi
            and risultato["validazione_csv"]["valido"]
            and risultato["accettazione_v03"]["esito"] == "accettata"
            and risultato["accettazione_v03"]["metriche"]["M3f"]["val"] == 1.0
            and str(_PROJECT_DIR) not in dump
        )
        return ok, f"chiavi={sorted(risultato)} acc={risultato['accettazione_v03']['esito']}"

    check("F2-01", "CSV v0.5: header esatto a 22 colonne", t01)
    check("F2-02", "CSV v0.5 valido in template con 2 righe di esempio", t02)
    check("F2-03", "CSV v0.5 bloccato in esecuzione finché restano le righe di esempio", t03)
    check("F2-04", "CSV v0.2 invariato: SHA-256 congelato", t04)
    check("F2-05", "CSV v0.2 valido in template con accetta_v02_20col=True", t05)
    check("F2-06", "CSV v0.2 rifiutato in esecuzione F2 (richieste 22 colonne)", t06)
    check("F2-07", "RT-03: estratto_fedele='sì' rifiutato con E1/E2/E3/E6", t07)
    check("F2-08", "E4/E7 compatibili con estratto_fedele='sì'", t08)
    check("F2-09", "Contraddizione fedele: M3<1, M3f=1, M8=1, accettata", t09)
    check("F2-10", "M8 non tautologico: contraddizioni_conservate obbligatorio", t10)
    check("F2-11", "Contraddizioni non conservate: M8=0 e non_accettabile", t11)
    check("F2-12", "VNP: estratto_fedele e polarita_fonte vietati", t12)
    check("F2-13", "Budget S2: estratto_fedele e polarita_fonte vietati", t13)
    check("F2-14", "DOCUMENTO: estratto_fedele e polarita_fonte vietati", t14)
    check("F2-15", "Promozione indebita abstract -> full text bloccata", t15)
    check("F2-16", "Unità giudicata su documento non disponibile bloccata", t16)
    check("F2-17", "Riga con 23 colonne rifiutata", t17)
    check("F2-18", "ID UNITA duplicati e documento_id non dichiarato rifiutati", t18)
    check("F2-19", "SHA-256 reale S01 verificato su disco", t19)
    check("F2-20", "SHA-256 reali S03 e S05 verificati su disco", t20)
    check("F2-21", "SHA-256 alterato di un hex: bloccato senza E8", t21)
    check("F2-22", "Path traversal '..' bloccato con ValueError", t22)
    check("F2-23", "File inesistente = RT-VNP (no E8); file 0 byte = E8; hash breve = ValueError", t23)
    check("F2-24", "Campo quotato con ';' parsato correttamente", t24)
    check("F2-25", "Bridge reale: 3 documenti verificati su disco", t25)
    check("F2-26", "doc_file_map incompleto per documento acquisito: errore", t26)
    check("F2-27", "modalita e stop non validi: ValueError", t27)
    check("F2-28", "Coppie F5 estratte da revisione_indipendente", t28)
    check("F2-29", "Budget: ammesso solo con S2 e campi F2 vuoti", t29)
    check("F2-30", "v0.5 valido senza flag; v0.2 no senza accetta_v02_20col", t30)
    check("F2-31", "valuta_foglio_audit_csv restituisce le tre chiavi attese senza path leak (O1)", t31)
    check(
        "F2-32",
        "R01: estratto_fedele=no rifiuta supporta/parziale e tipo_errore vuoto",
        lambda: (
            (not valida_csv_scheda_f2(_csv_da([_riga_doc(), _riga_unita("E-001", estratto="no", esito="supporta")]), modalita="esecuzione")["valido"])
            and (not valida_csv_scheda_f2(_csv_da([_riga_doc(), _riga_unita("E-001", estratto="no", esito="contrasta", polarita="contraria", errore="")]), modalita="esecuzione")["valido"]),
            "R01 verificato",
        ),
    )
    check(
        "F2-33",
        "CR-03/CR-04: blocco documento metadato e unita senza passaggio primario verificato",
        lambda: (
            (not valida_csv_scheda_f2(_csv_da([_riga_doc(stato="metadato", hash_file=""), _riga_unita("E-001", stato="metadato")]), modalita="esecuzione")["valido"])
            and (not valida_csv_scheda_f2(_csv_da([_riga_doc(), _riga_unita("E-001", source_kind="dossier_paraphrase", posizione="", posizione_verificata="no", link="no")]), modalita="esecuzione")["valido"]),
            "CR-03/CR-04 verificati",
        ),
    )
    check(
        "F2-34",
        "R08/AL-08: path esterno senza base_dir bloccato fail-closed senza path leak",
        lambda: (
            (lambda r: (not r["valido"]) and all("/etc/" not in e for e in r["errori"]))(
                valida_csv_scheda_f2(_csv_da([_riga_doc()]), modalita="esecuzione", doc_file_map={"DOC-001": "/etc/passwd"})
            ),
            "AL-08 + O1 verificati",
        ),
    )
    return checks


if __name__ == "__main__":
    risultati = esegui_test_f2()
    for c in risultati:
        print(f"{c['esito']} [{c['id']}] {c['descrizione']} | {c['dettaglio']}")
    passati = sum(1 for c in risultati if c["ok"])
    print(f"RIEPILOGO: {passati}/{len(risultati)} PASS")
    if passati != len(risultati):
        sys.exit(1)
