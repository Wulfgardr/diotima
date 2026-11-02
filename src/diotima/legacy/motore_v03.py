#!/usr/bin/env python3
"""
Motore logico Diotima v0.3 — Completo e autonomo (sola libreria standard Python).
Implementa:
- Tutti i 10 rilievi Red Team RT-01..RT-10 + RT-VNP (D1..D11)
- Procedura decisionale operativa a 5 passi (ordine obbligato)
- Validatore strutturale e semantico per la scheda CSV a 20 colonne (Diotima_scheda_audit_v0.2.csv)
- Valutazione comparativa su fogli Round 1 (A, B, C) e Round 2 (A2, B2, C2) e curve OC bayesiane
"""

import json
import math
import pathlib
import random
import statistics

ROOT = pathlib.Path(__file__).resolve().parent  # dati inclusi nel pacchetto
OUT = pathlib.Path.cwd() / "risultati_motore_v0.3.json"
CSV_SCHEDA = ROOT / "data" / "scheda_audit_v0.2.csv"

STATI_ORDINARI = ("supporta", "parziale", "contrasta", "insufficiente", "verifica non possibile")
STATO_BUDGET = "non_valutata_budget"
GIUDICABILI = ("supporta", "parziale", "contrasta", "insufficiente")
CODICI_AMMESSI = {"E1", "E2", "E3", "E4", "E5", "E6", "E7", "E8"}
FEDELTA_ERR = {"E1", "E2", "E3", "E6"}
BLOCCANTI = {"E1", "E2", "E7"}
QUOTA_MIN = 0.80
TETTO_E8_MAX = 0.10
SOGLIA_SOSTITUZIONI = 0.20

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


# ============================================================================
# 1. FUNZIONI STATISTICHE E MATEMATICHE AUTONOME (SOLA LIBRERIA STANDARD)
# ============================================================================

def mediana(v):
    return statistics.median(v) if v else None


def iqr(v):
    if len(v) < 2:
        return None
    q = statistics.quantiles(v, n=4, method="inclusive")
    return [round(q[0], 3), round(q[2], 3)]


def accordo_cohen(coppie):
    n = len(coppie)
    if not n:
        return None, None
    po = sum(1 for a, b in coppie if a == b) / n
    cats = sorted({x for p in coppie for x in p})
    pc = 0.0
    for c in cats:
        p1 = sum(1 for a, _ in coppie if a == c) / n
        p2 = sum(1 for _, b in coppie if b == c) / n
        pc += p1 * p2
    kappa = (po - pc) / (1.0 - pc) if pc < 1.0 else None
    return po, kappa


def betacf(a, b, x):
    maxit, eps, fpmin = 300, 3e-16, 1e-300
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c, d = 1.0, 1.0 - qab * x / qap
    if abs(d) < fpmin:
        d = fpmin
    d = 1.0 / d
    h = d
    for mm in range(1, maxit + 1):
        m2 = 2 * mm
        aa = mm * (b - mm) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < fpmin:
            d = fpmin
        c = 1.0 + aa / c
        if abs(c) < fpmin:
            c = fpmin
        d = 1.0 / d
        h *= d * c
        aa = -(a + mm) * (qab + mm) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < fpmin:
            d = fpmin
        c = 1.0 + aa / c
        if abs(c) < fpmin:
            c = fpmin
        d = 1.0 / d
        de = d * c
        h *= de
        if abs(de - 1.0) < eps:
            break
    return h


def betai(a, b, x):
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    lbt = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log(1.0 - x)
    bt = math.exp(lbt)
    if x < (a + 1.0) / (a + b + 2.0):
        return bt * betacf(a, b, x) / a
    return 1.0 - bt * betacf(b, a, 1.0 - x) / b


def pmf(k, n, p):
    return math.comb(n, k) * (p ** k) * ((1.0 - p) ** (n - k))


def post_ge(x, n, prior, t=0.95):
    a, b = prior
    return 1.0 - betai(a + x, b + n - x, t)


# ============================================================================
# 2. PROCEDURA DECISIONALE OPERATIVA A 5 PASSI + RT-VNP
# ============================================================================

def procedura_5passi(item):
    """
    Applica in ordine obbligato la procedura di decisione a 5 passi (§1 packet v0.2 / §6.3 flusso v0.2).
    Fermata al primo passo che si applica:
      Passo 1: Verifica materialmente possibile? (primario non acquisito / passaggio non ispezionabile)
               -> 'verifica non possibile', tipo_errore = None (RT-VNP: stato, non errore; E8 solo se illeggibile/diritto assente, E4 solo se link dichiarato rotto).
      Passo 2: Contraddice qualifica, direzione o valore affermato (incluso valore numerico smentito da valore diverso o citazione testuale inesistente)?
               -> 'contrasta' (+ E7 se valore numerico smentito/assente, + E1 se pseudo-citazione testuale, + E2 se coordinate inventate).
      Passo 3: Compatibile ma preliminare, esplorativo, vago o fuori tema al punto da non sostenere l'affermazione?
               -> 'insufficiente' (+ E3 se fuori tema).
      Passo 4: Sostiene la direzione ma tace su forza, quantità o dettagli affermati?
               -> 'parziale' (+ E7 se la rivendicazione contiene un numero assente/non quantificato nella fonte: non quantificare != smentire).
      Passo 5: Altrimenti sostiene l'affermazione così com'è formulata -> 'supporta', tipo_errore = None.
    """
    acquisito = item.get("documento_acquisito", True)
    ispezionabile = item.get("passaggio_ispezionabile", True)
    if not acquisito or not ispezionabile:
        err = []
        if item.get("file_illeggibile_o_diritto_assente", False):
            err.append("E8")
        if item.get("link_dichiarato_rotto", False):
            err.append("E4")
        return {
            "unita": item.get("unita"),
            "passo_attivato": 1,
            "esito": "verifica non possibile",
            "tipo_errore": ", ".join(err) if err else None,
            "regola": "Passo 1 (RT-VNP): non acquisizione e stato, tipo_errore vuoto salvo E8/E4 specifici",
        }

    contraddice_qualifica_o_direzione = item.get("contraddice_qualifica_o_direzione", False)
    valore_numerico_smentito = item.get("valore_numerico_smentito", False)
    pseudo_citazione_testuale = item.get("pseudo_citazione_testuale", False)
    if contraddice_qualifica_o_direzione or valore_numerico_smentito or pseudo_citazione_testuale:
        err = []
        if pseudo_citazione_testuale:
            err.append("E1")
        if item.get("coordinate_inventate", False):
            err.append("E2")
        if valore_numerico_smentito or item.get("numero_inventato_in_contrasto", False):
            err.append("E7")
        return {
            "unita": item.get("unita"),
            "passo_attivato": 2,
            "esito": "contrasta",
            "tipo_errore": ", ".join(err) if err else None,
            "regola": "Passo 2: contraddice qualifica, direzione o valore numerico affermato",
        }

    preliminare_o_vago = item.get("preliminare_o_vago", False)
    fuori_tema = item.get("fuori_tema", False)
    if preliminare_o_vago or fuori_tema:
        err = []
        if fuori_tema:
            err.append("E3")
        if item.get("scope_errato", False):
            err.append("E6")
        return {
            "unita": item.get("unita"),
            "passo_attivato": 3,
            "esito": "insufficiente",
            "tipo_errore": ", ".join(err) if err else None,
            "regola": "Passo 3: compatibile ma preliminare, esplorativo o vago",
        }

    direzione_ok_dettaglio_o_quantita_assente = item.get("direzione_ok_dettaglio_o_quantita_assente", False)
    numero_assente_non_quantificato = item.get("numero_assente_non_quantificato", False)
    if direzione_ok_dettaglio_o_quantita_assente or numero_assente_non_quantificato:
        err = []
        if numero_assente_non_quantificato:
            err.append("E7")
        if item.get("scope_errato", False):
            err.append("E6")
        return {
            "unita": item.get("unita"),
            "passo_attivato": 4,
            "esito": "parziale",
            "tipo_errore": ", ".join(err) if err else None,
            "regola": "Passo 4: sostiene la direzione ma tace su forza/quantita (non quantificare != smentire)",
        }

    return {
        "unita": item.get("unita"),
        "passo_attivato": 5,
        "esito": "supporta",
        "tipo_errore": None,
        "regola": "Passo 5: sostegno pieno all'affermazione",
    }


def valida_vnp_unita(u):
    """
    RT-VNP: Verifica che un'unita con stato 'verifica non possibile' per semplice non acquisizione
    del primario non abbia codici errore spuri (es. E2, E4, E7).
    Ammette E8 solo se c'e errore di preparazione (illeggibile/diritto assente) ed E4 solo se c'e
    un collegamento dichiarato nello snapshot che risulta rotto.
    """
    if u.get("esito") != "verifica non possibile":
        return {"ok": True, "motivo": None}
    c = codici(u)
    if not c:
        return {"ok": True, "motivo": None}
    non_acquisito = u.get("stato_accesso", "").startswith("non acquisito") or not u.get("documento_acquisito", True)
    if non_acquisito:
        ammessi_eccezionali = set()
        if u.get("file_illeggibile_o_diritto_assente"):
            ammessi_eccezionali.add("E8")
        if u.get("link_dichiarato_rotto"):
            ammessi_eccezionali.add("E4")
        spuri = sorted(c - ammessi_eccezionali)
        if spuri:
            return {"ok": False, "motivo": f"RT-VNP violato: codici spuri {spuri} su verifica non possibile per non acquisizione"}
    return {"ok": True, "motivo": None}


# ============================================================================
# 3. COSTRUTTORI DATI, PARSING CODICI E CALCOLO METRICHE (RT-01..RT-10)
# ============================================================================

def codici(u):
    """RT-10: Parsing multi-etichetta di tipo_errore separato da virgola."""
    t = u.get("tipo_errore") or ""
    return {c.strip() for c in t.split(",") if c.strip()}


def doc(doc_id, ok=True, accesso="full text", prov=True, hash_file="sha256_ok", hash_coincide=True, errore_prep_E8=False, motivo_E8=""):
    return {
        "id": doc_id,
        "identita_ok": ok,
        "stato_accesso": accesso,
        "provenienza": prov,
        "hash_file": hash_file,
        "hash_coincide": hash_coincide,
        "errore_prep_E8": errore_prep_E8,
        "motivo_E8": motivo_E8,
    }


def unit(uid, esito, numerica=False, inventato=False, link=True, tipo_errore="", sostituisce_id=None, ciclo="v0.2"):
    return {
        "id": uid,
        "esito": esito,
        "numerica": numerica,
        "numero_inventato": inventato,
        "link_prodotto": True,
        "link_ok": link,
        "tipo_errore": tipo_errore,
        "sostituisce_id": sostituisce_id,
        "ciclo": ciclo,
    }


def sheet(
    docs,
    units,
    subs=0,
    target=20,
    contrad=(0, 0),
    prep=None,
    tempiA=None,
    tempiB=None,
    coppie_F5=None,
    ciclo="v0.2",
    audit_count=1,
    stop=None,
):
    if prep is None:
        e8_count = sum(1 for d in docs if d.get("errore_prep_E8"))
        prep = (e8_count, len(docs) if docs else target)
    return {
        "docs": docs,
        "unita": units,
        "storico_append_only": list(units),
        "sostituzioni_dichiarate": subs,
        "corpus_target": target,
        "contraddizioni_rilevate": contrad[0],
        "contraddizioni_conservate": contrad[1],
        "prep_errori": prep[0],
        "prep_tentati": prep[1],
        "tempi": {"A": tempiA or [], "B": tempiB or []},
        "coppie_F5": coppie_F5,
        "ciclo": ciclo,
        "audit_count": audit_count,
        "stop": stop,
    }


def unita_attive(units):
    """
    RT-01: In un registro append-only, le righe del ciclo rev1 che dichiarano `sostituisce_id`
    aggiornano il denominatore attivo senza cancellare le righe sostituite dallo storico.
    """
    sostituite = {u["sostituisce_id"] for u in units if u.get("sostituisce_id")}
    return [u for u in units if u["id"] not in sostituite]


def verifica_manifest_e_hash(docs, corpus_target=20, prep_errori=None):
    """
    RT-07:
    1) Il controllo di coincidenza SHA-256 si applica ai soli documenti con file leggibile acquisito
       (stato_accesso in {'full text', 'abstract'} e senza errore di preparazione E8).
    2) I documenti con stato_accesso in {'metadato', 'non disponibile'} o con errore E8 (file illeggibile)
       soddisfano M1 anche con hash_file vuoto, purché abbiano identita_ok, stato_accesso, provenienza
       (e motivo_E8 registrato se E8).
    3) La quota di documenti illeggibili (E8) non puo superare il tetto del 10% (<= 2 su 20).
    """
    traced = 0
    hash_leggibili_tot = 0
    hash_leggibili_ok = 0
    e8_docs = 0

    for d in docs:
        accesso = d.get("stato_accesso", "")
        is_e8 = bool(d.get("errore_prep_E8"))
        if is_e8:
            e8_docs += 1
        base_ok = bool(d.get("identita_ok") and accesso and d.get("provenienza"))
        if is_e8 and not d.get("motivo_E8"):
            base_ok = False

        leggibile_acquisito = (accesso in ("full text", "abstract")) and not is_e8
        if leggibile_acquisito:
            hash_leggibili_tot += 1
            h_ok = bool(d.get("hash_file")) and bool(d.get("hash_coincide", True))
            if h_ok:
                hash_leggibili_ok += 1
            else:
                base_ok = False
        if base_ok:
            traced += 1

    eff_e8 = prep_errori if prep_errori is not None else e8_docs
    den_target = corpus_target if corpus_target else len(docs)
    quota_e8 = eff_e8 / den_target if den_target else 0.0
    tetto_e8_ok = quota_e8 <= TETTO_E8_MAX

    return {
        "M1": {"num": traced, "den": len(docs), "val": traced / len(docs) if docs else None},
        "hash_leggibili": {
            "num": hash_leggibili_ok,
            "den": hash_leggibili_tot,
            "val": hash_leggibili_ok / hash_leggibili_tot if hash_leggibili_tot else 1.0,
            "tutti_coincidenti": hash_leggibili_ok == hash_leggibili_tot,
        },
        "tetto_E8": {
            "errori_E8": eff_e8,
            "corpus_target": den_target,
            "quota": round(quota_e8, 4),
            "soglia_max": TETTO_E8_MAX,
            "ok": tetto_e8_ok,
        },
    }


def calcola_M7_F5(unita_f5=None, scheda_A_libera=None, scheda_B_matrice=None):
    """
    RT-08: M7 non e calcolabile direttamente tra la scheda libera A (F3/F4) e la scheda strutturata B
    perche manca un insieme comune di unita pre-allineate e un campo categorico condiviso.
    M7 si calcola esclusivamente in fase F5 su un insieme comune di unita UNITA gia estratte e pre-allineate,
    confrontando l'assegnazione indipendente del campo `esito` (5 categorie) tra `lettore` e `revisione_indipendente`.
    """
    if scheda_A_libera is not None or scheda_B_matrice is not None:
        return {
            "calcolabile": False,
            "motivo": "RT-08: condizioni A (scheda libera) e B (matrice) in F3/F4 eterogenee senza unita pre-allineate",
            "accordo_grezzo": None,
            "kappa": None,
            "n_coppie": 0,
            "soglia_80_ok": None,
            "disaccordi": [],
        }
    if not unita_f5:
        return {
            "calcolabile": False,
            "motivo": "nessuna unita sottoposta a doppia lettura in F5",
            "accordo_grezzo": None,
            "kappa": None,
            "n_coppie": 0,
            "soglia_80_ok": None,
            "disaccordi": [],
        }

    coppie = []
    disaccordi = []
    for item in unita_f5:
        if isinstance(item, (tuple, list)) and len(item) == 2:
            uid = f"pair-{len(coppie)+1}"
            e1, e2 = item[0], item[1]
        else:
            uid = item.get("id") or item.get("unita")
            e1 = item.get("esito_lettore") or item.get("lettore_esito")
            e2 = item.get("esito_revisore") or item.get("revisione_indipendente_esito")
        if not e1 or not e2:
            return {
                "calcolabile": False,
                "motivo": f"RT-08: unita {uid} priva di doppia assegnazione indipendente sull'insieme pre-allineato F5",
                "accordo_grezzo": None,
                "kappa": None,
                "n_coppie": 0,
                "soglia_80_ok": None,
                "disaccordi": [],
            }
        coppie.append((e1, e2))
        if e1 != e2:
            disaccordi.append({"unita": uid, "lettore": e1, "revisione_indipendente": e2})

    po, kap = accordo_cohen(coppie)
    return {
        "calcolabile": True,
        "motivo": "F5: insieme comune di unita pre-allineate con confronto categorico a 5 stati",
        "accordo_grezzo": round(po, 4) if po is not None else None,
        "kappa": round(kap, 4) if kap is not None else None,
        "n_coppie": len(coppie),
        "soglia_80_ok": (po >= 0.80) if po is not None else None,
        "disaccordi": disaccordi,
    }


def valida_passaggio_L1_L2(revisori_L1, R1_L2, R2_L2, piano_blocchi, modalita_F0="sequenziale_L1_poi_L2"):
    """
    RT-06: Impedisce il cortocircuito sequenziale tra Livello 1 e Livello 2.
    - Se modalita_F0 == 'sequenziale_L1_poi_L2', nessuno dei revisori che nel Livello 2 deve leggere
      un blocco in baseline A (senza Diotima) puo aver gia schedato quello stesso corpus in condizione B nel Livello 1.
    - Verifica inoltre che il crossover L2 sia controbilanciato sia per blocco che per periodo:
      R1_L2: Blocco A in cond A -> Blocco B in cond B
      R2_L2: Blocco A in cond B -> Blocco B in cond A (o simmetrico).
    """
    errori = []
    rev_l1_set = set(revisori_L1 or [])

    if modalita_F0 == "sequenziale_L1_poi_L2":
        contaminati = sorted(rev_l1_set & {R1_L2, R2_L2})
        if contaminati:
            errori.append(
                f"RT-06 (contaminazione_L1_L2): i revisori {contaminati} hanno gia schedato il corpus in B nel Livello 1 e non possono eseguire la baseline A nel Livello 2"
            )

    if R1_L2 == R2_L2:
        errori.append("RT-06: Livello 2 richiede due revisori distinti")

    p1 = piano_blocchi.get(R1_L2, [])
    p2 = piano_blocchi.get(R2_L2, [])
    if len(p1) != 2 or len(p2) != 2:
        errori.append("RT-06: ciascun revisore deve avere 2 periodi/blocchi assegnati")
    else:
        cond_p1 = (p1[0].get("condizione"), p1[1].get("condizione"))
        cond_p2 = (p2[0].get("condizione"), p2[1].get("condizione"))
        blocchi_p1 = (p1[0].get("blocco"), p1[1].get("blocco"))
        blocchi_p2 = (p2[0].get("blocco"), p2[1].get("blocco"))

        if cond_p1 not in (("A", "B"), ("B", "A")) or cond_p2 not in (("A", "B"), ("B", "A")) or cond_p1 == cond_p2:
            errori.append(
                f"RT-06 (ordine_non_controbilanciato): sequenze condizioni {cond_p1} vs {cond_p2} non incrociate tra periodo 1 e periodo 2"
            )
        if blocchi_p1[0] == blocchi_p1[1] or blocchi_p1 != blocchi_p2:
            errori.append("RT-06: i due revisori devono attraversare i due blocchi disgiunti nello stesso ordine con condizioni opposte")

    return {"valido": len(errori) == 0, "modalita_F0": modalita_F0, "errori": errori}


def chiudi_per_budget_S2(s):
    """
    RT-09: Quando interviene l'arresto per esaurimento del budget ore persona (S2),
    chiude legalmente tutte le righe UNITA ancora aperte (esito == '') assegnando
    `esito = 'non_valutata_budget'` e registrando l'evento nel log append-only.
    """
    s["stop"] = "S2"
    chiuse_ora = 0
    for u in s["unita"]:
        if u.get("esito", "") == "":
            u["esito"] = STATO_BUDGET
            u["link_prodotto"] = False
            chiuse_ora += 1
            s.setdefault("storico_append_only", []).append(
                {"evento": "chiusura_budget_S2", "unita_id": u["id"], "nuovo_esito": STATO_BUDGET}
            )
    s["chiuse_budget_S2"] = chiuse_ora
    return s


def applica_ciclo_rev1(s, sostituzioni_rev1):
    """
    RT-01: Gestisce la ripetizione in fascia M3b [90%, 95%) compatibilmente con S3 (un solo audit)
    e con il registro append-only (§8.1).
    - Ammessa SOLO se il primo giro ('v0.2') ha dato esito 'zona_revisione'.
    - Se il foglio e gia in 'v0.2-rev1', un ulteriore ciclo ('rev2') viene bloccato da S3.
    - Le nuove unita vengono aggiunte in append-only con `sostituisce_id` e `ciclo = 'v0.2-rev1'`,
      aggiornando il denominatore attivo per l'unico secondo calcolo preregistrato.
    """
    if s.get("ciclo") != "v0.2" or s.get("audit_count", 1) >= 2:
        return {
            "consentito": False,
            "esito_blocco": "blocco_S3_doppio_audit",
            "motivo": "RT-01 / S3: vietato un terzo calcolo (rev2) o un secondo audit su ciclo gia revisionato; serve nuova versione del protocollo (v0.3)",
            "s_regole": ["S3"],
        }
    primo_esito = accettazione3(s)
    if primo_esito["esito"] != "zona_revisione":
        return {
            "consentito": False,
            "esito_blocco": "blocco_S3_audit_non_in_M3b",
            "motivo": f"RT-01 / S3: il ciclo rev1 e ammesso solo da zona_revisione [90%, 95%), ma il primo giro ha esito '{primo_esito['esito']}'",
            "s_regole": ["S3"],
        }

    nuovo_unita = list(s["unita"])
    for rep in sostituzioni_rev1:
        nuovo_unita.append(rep)

    s_rev1 = dict(s)
    s_rev1["unita"] = nuovo_unita
    s_rev1["storico_append_only"] = list(nuovo_unita)
    s_rev1["ciclo"] = "v0.2-rev1"
    s_rev1["audit_count"] = 2
    secondo_esito = accettazione3(s_rev1)
    if secondo_esito["esito"] != "accettata":
        secondo_esito["esito"] = "richiede_nuova_versione_protocollo"
        secondo_esito["motivi"].append("RT-01 (M3b + S3): dopo l'unico ciclo v0.2-rev1 M3f resta < 95%; vietato rev2, necessaria nuova versione del protocollo")
        if "S3" not in secondo_esito["s_regole"]:
            secondo_esito["s_regole"].append("S3")
    return {
        "consentito": True,
        "ciclo": "v0.2-rev1",
        "righe_totali_append_only": len(s_rev1["storico_append_only"]),
        "unita_attive_rev1": len(unita_attive(s_rev1["unita"])),
        "risultato_rev1": secondo_esito,
    }


def metriche3(s):
    """Calcola tutte le metriche M1..M9 + M2e, M3f, M4b, quota_giudicate, hash_leggibili, tetto_E8."""
    docs = s["docs"]
    all_units = s["unita"]
    units = unita_attive(all_units)

    m = {}
    prep_check = verifica_manifest_e_hash(docs, corpus_target=s.get("corpus_target", 20), prep_errori=s.get("prep_errori"))
    m["M1"] = prep_check["M1"]
    m["hash_leggibili"] = prep_check["hash_leggibili"]
    m["tetto_E8"] = prep_check["tetto_E8"]

    # RT-02: M2e esclude verifica non possibile (e non_valutata_budget) dal denominatore dei link
    links_v01 = [u for u in units if u.get("link_prodotto", True)]
    link_ok_v01 = sum(1 for u in links_v01 if u.get("link_ok", True))
    m["M2"] = {"num": link_ok_v01, "den": len(links_v01), "val": link_ok_v01 / len(links_v01) if links_v01 else None}

    links_eff = [
        u for u in units
        if u["esito"] not in ("verifica non possibile", STATO_BUDGET) and u.get("link_prodotto", True)
    ]
    link_ok_eff = sum(1 for u in links_eff if u.get("link_ok", True))
    m["M2e"] = {"num": link_ok_eff, "den": len(links_eff), "val": link_ok_eff / len(links_eff) if links_eff else None}

    giud = [u for u in units if u["esito"] in GIUDICABILI]
    supporta = sum(1 for u in giud if u["esito"] == "supporta")
    m["M3"] = {
        "num": supporta,
        "den_giudicate": len(giud),
        "den_totali": len(units),
        "val": supporta / len(giud) if giud else None,
        "non_valutabile": not giud,
    }

    # RT-03: M3f misura la fedelta dell'estratto sulle unita giudicate (assenza di E1, E2, E3, E6)
    fedeli = sum(1 for u in giud if not (codici(u) & FEDELTA_ERR) and u.get("estratto_fedele", True))
    m["M3f"] = {
        "num": fedeli,
        "den_giudicate": len(giud),
        "den_totali": len(units),
        "val": fedeli / len(giud) if giud else None,
        "non_valutabile": not giud,
    }

    m["quota_giudicate"] = {
        "num": len(giud),
        "den": len(units),
        "val": len(giud) / len(units) if units else None,
    }

    # RT-05 & RT-10: M4 conta le unita con almeno un errore E7 (o flag numero_inventato), val=None se den=0
    num_claim = [u for u in units if u.get("numerica") or ("E7" in codici(u))]
    inv = sum(1 for u in units if u.get("numero_inventato") or ("E7" in codici(u)))
    m["M4"] = {
        "num": inv,
        "den": len(num_claim),
        "val": inv / len(num_claim) if num_claim else None,
        "non_valutabile": len(num_claim) == 0,
        "regola_zero": inv == 0,
    }

    # RT-04: M4b conta tutte le unita con errori bloccanti E1, E2 o E7
    blocc = sum(1 for u in units if (codici(u) & BLOCCANTI) or u.get("numero_inventato"))
    m["M4b"] = {"num": blocc, "den": len(units), "regola_zero": blocc == 0}

    m["M5"] = {
        "A": {"mediana": mediana(s["tempi"]["A"]), "iqr": iqr(s["tempi"]["A"])},
        "B": {"mediana": mediana(s["tempi"]["B"]), "iqr": iqr(s["tempi"]["B"])},
    }
    a, b = mediana(s["tempi"]["A"]), mediana(s["tempi"]["B"])
    if a and b:
        red = 1.0 - b / a
        m["M6"] = {"val": red, "calcolabile": True, "soglia_20_raggiunta": red >= 0.20}
    else:
        m["M6"] = {"val": None, "calcolabile": False, "soglia_20_raggiunta": None}

    # RT-08: M7 calcolata su unita pre-allineate F5
    m["M7"] = calcola_M7_F5(s.get("coppie_F5"))

    # RT-05: M8 con denominatore zero -> val=None (non valutabile) ma soddisfatta per assenza di contraddizioni
    c_ril = s["contraddizioni_rilevate"]
    c_cons = s["contraddizioni_conservate"]
    m["M8"] = {
        "num": c_cons,
        "den": c_ril,
        "val": c_cons / c_ril if c_ril else None,
        "non_valutabile": c_ril == 0,
        "soddisfatta": (c_cons == c_ril) if c_ril > 0 else True,
    }

    m["M9"] = {
        "num": s["prep_errori"],
        "den": s["prep_tentati"],
        "val": s["prep_errori"] / s["prep_tentati"] if s["prep_tentati"] else None,
        "tetto_E8_ok": prep_check["tetto_E8"]["ok"],
    }

    m["append_only"] = {
        "ciclo": s.get("ciclo", "v0.2"),
        "righe_storico": len(all_units),
        "unita_attive": len(units),
    }
    return m


def accettazione3(s, quota_min=QUOTA_MIN):
    """
    Motore decisionale v0.3 con chiusura completa di RT-01..RT-10 + RT-VNP.
    """
    m = metriche3(s)
    units = unita_attive(s["unita"])
    aperte = sum(1 for u in units if u.get("esito", "") == "")
    n_budget = sum(1 for u in units if u.get("esito") == STATO_BUDGET)
    giud = m["M3f"]["den_giudicate"]
    subs_rate = s["sostituzioni_dichiarate"] / s["corpus_target"] if s["corpus_target"] else 0.0

    out = {
        "ciclo": s.get("ciclo", "v0.2"),
        "esito": None,
        "motivi": [],
        "s_regole": [],
        "subs_rate": round(subs_rate, 4),
        "metriche": m,
    }

    def finish(esito, motivi, regole=()):
        out["esito"] = esito
        out["motivi"] = motivi
        out["s_regole"] = list(regole)
        return out

    # RT-01: Blocco S3 se audit_count > 2
    if s.get("audit_count", 1) > 2:
        return finish("blocco_S3_doppio_audit", ["S3: superato il limite di un solo ciclo di revisione preregistrato"], ("S3",))

    # RT-09: Gestione arresto per budget S2 e divieto di non_valutata_budget fuori da S2
    if s.get("stop") == "S2":
        if aperte > 0:
            chiudi_per_budget_S2(s)
            m = metriche3(s)
            out["metriche"] = m
            units = unita_attive(s["unita"])
            n_budget = sum(1 for u in units if u.get("esito") == STATO_BUDGET)
            aperte = 0
        return finish(
            "non_concluso_budget",
            [f"S2 (RT-09): arresto per fine budget con {n_budget} unita chiuse legalmente come {STATO_BUDGET}"],
            ("S2",),
        )
    elif n_budget > 0:
        return finish(
            "fallimento_strutturale",
            [f"RT-09: {n_budget} unita con stato {STATO_BUDGET} senza attivazione di S2"],
            ("S4",),
        )

    if giud == 0:
        return finish("prova_non_conclusa", ["n = 0: nessuna unita giudicabile"], ("S7",))

    if aperte > 0:
        return finish("in_corso", [f"{aperte} unita ancora aperte: vietate alla chiusura"], ("S1 non soddisfatta",))

    # RT-VNP: Verifica assenza codici errore spuri sulle unita VNP
    vnp_err = [valida_vnp_unita(u)["motivo"] for u in units if not valida_vnp_unita(u)["ok"]]
    if vnp_err:
        return finish("fallimento_strutturale", vnp_err, ("S4",))

    struct = []
    if m["M1"]["val"] is not None and m["M1"]["val"] < 1.0:
        struct.append(f"M1 = {m['M1']['val']:.4f} (< 100%)")
    if not m["hash_leggibili"]["tutti_coincidenti"]:
        struct.append(
            f"RT-07: hash non coincidente sui file leggibili ({m['hash_leggibili']['num']}/{m['hash_leggibili']['den']})"
        )
    if not m["tetto_E8"]["ok"]:
        struct.append(
            f"RT-07: documenti illeggibili E8 = {m['tetto_E8']['quota']:.1%} (> tetto {TETTO_E8_MAX:.0%})"
        )
    if m["M2e"]["val"] is not None and m["M2e"]["val"] < 1.0:
        struct.append(f"M2e = {m['M2e']['val']:.4f} (< 100%, VNP esclusi)")
    if m["quota_giudicate"]["val"] is not None and m["quota_giudicate"]["val"] < quota_min:
        struct.append(f"RT-02: quota giudicate = {m['quota_giudicate']['val']:.4f} (< {quota_min:.0%})")
    if m["M4b"]["num"] > 0:
        struct.append(f"RT-04: errori bloccanti E1/E2/E7 = {m['M4b']['num']} (> 0)")
    if m["M3f"]["val"] is not None and m["M3f"]["val"] < 0.90:
        struct.append(f"M3f = {m['M3f']['val']:.4f} (< 90%)")

    if struct:
        return finish("fallimento_strutturale", struct, ("S4",))

    if subs_rate > SOGLIA_SOSTITUZIONI:
        return finish("sospensione_corpus_inadatto", [f"sostituzioni {subs_rate:.1%} > 20%"], ("S5",))

    if not m["M8"]["soddisfatta"]:
        return finish("non_accettabile", [f"M8 = {m['M8']['val']:.4f} (< 100%: contraddizioni non conservate)"])

    v = m["M3f"]["val"]
    if 0.90 <= v < 0.95:
        return finish("zona_revisione", [f"RT-10: M3f = {v:.5f} in [90%, 95%) -> consente un unico ciclo v0.2-rev1"])
    if v >= 0.95:
        return finish(
            "accettata",
            [
                f"M3f = {v:.4f} >= 95%; M1 = M2e = 100%; hash leggibili ok; E8 <= 10%; quota >= 80%; M4b = 0; M8 soddisfatta"
            ],
        )
    return finish("non_accettabile", ["condizione non classificata"])


# ============================================================================
# 4. VALIDATORE SCHEDA CSV A 20 COLONNE
# ============================================================================

def valida_csv_scheda(lines_or_path, modalita="template", stop=None):
    """
    Valida il formato e i vincoli semantici della scheda CSV a 20 colonne (`Diotima_scheda_audit_v0.2.csv`).
    - modalita='template': accetta le righe di esempio marcate in `note`.
    - modalita='esecuzione': blocca se le righe di esempio non sono state cancellate (F2),
      se ci sono campi `esito` vuoti (salvo in_corso), se un `unverified_primary` riceve uno stato
      giudicato positivo, o se RT-VNP / multi-etichetta `tipo_errore` sono violati.
    """
    if isinstance(lines_or_path, pathlib.Path):
        raw_lines = lines_or_path.read_text(encoding="utf-8").splitlines()
    else:
        raw_lines = list(lines_or_path)

    errori = []
    if not raw_lines:
        return {"valido": False, "n_colonne": 0, "errori": ["File CSV vuoto"]}

    header = raw_lines[0].split(";")
    if header != HEADER_ATTESO_20:
        errori.append(f"Header non conforme: attese 20 colonne specifiche, trovate {len(header)}")

    righe_doc = 0
    righe_unita = 0
    righe_esempio = 0

    stati_validi = set(STATI_ORDINARI) | ({STATO_BUDGET} if stop == "S2" else set())

    for idx, line in enumerate(raw_lines[1:], start=2):
        if not line.strip():
            continue
        cols = line.split(";")
        if len(cols) != 20:
            errori.append(f"Riga {idx}: numero colonne = {len(cols)} != 20")
            continue
        row = dict(zip(HEADER_ATTESO_20, cols))
        is_esempio = "RIGA DI ESEMPIO ILLUSTRATIVO" in row["note"]
        if is_esempio:
            righe_esempio += 1
            if modalita == "esecuzione":
                errori.append(f"Riga {idx} ({row['id']}): riga di esempio non rimossa prima dell'esecuzione (F2)")

        tr = row["tipo_riga"]
        if tr == "DOCUMENTO":
            righe_doc += 1
            if row["stato_accesso"] not in ("metadato", "abstract", "full text", "non disponibile"):
                errori.append(f"Riga {idx}: stato_accesso DOCUMENTO non valido '{row['stato_accesso']}'")
            if row["stato_accesso"] in ("full text", "abstract") and row["tipo_errore"] != "E8" and not row["hash_file"]:
                errori.append(f"Riga {idx}: documento leggibile privo di hash_file (RT-07)")
        elif tr == "UNITA":
            righe_unita += 1
            if row["source_kind"] not in ("primary_excerpt", "dossier_paraphrase"):
                errori.append(f"Riga {idx}: source_kind non valido '{row['source_kind']}'")
            if row["verification_status"] not in ("verified_primary", "unverified_primary"):
                errori.append(f"Riga {idx}: verification_status non valido '{row['verification_status']}'")
            esito = row["esito"]
            if modalita == "esecuzione" and esito == "":
                errori.append(f"Riga {idx}: esito vuoto vietato alla chiusura")
            if esito and esito not in stati_validi:
                errori.append(f"Riga {idx}: esito '{esito}' non ammesso (stop={stop})")
            if row["verification_status"] == "unverified_primary" and esito in GIUDICABILI:
                errori.append(f"Riga {idx}: unverified_primary non puo avere esito giudicato '{esito}'")
            errs = {c.strip() for c in row["tipo_errore"].split(",") if c.strip()}
            invalid_codes = sorted(errs - CODICI_AMMESSI)
            if invalid_codes:
                errori.append(f"Riga {idx}: codici tipo_errore non validi {invalid_codes}")
            if esito == "verifica non possibile" and row["stato_accesso"].startswith("non acquisito") and errs:
                errori.append(f"Riga {idx}: RT-VNP violato, codice errore {sorted(errs)} su primario non acquisito")
        else:
            errori.append(f"Riga {idx}: tipo_riga sconosciuto '{tr}'")

    return {
        "valido": len(errori) == 0,
        "modalita": modalita,
        "n_colonne": len(header),
        "righe_documento": righe_doc,
        "righe_unita": righe_unita,
        "righe_esempio": righe_esempio,
        "errori": errori,
    }


# ============================================================================
# 5. VALUTAZIONE DEI FOGLI SINTETICI (R1 E R2) E SOGLIE CONGIUNTE
# ============================================================================

def soglie_congiunte():
    righe = []
    for n in (40, 60, 80):
        for conf in (0.80, 0.85, 0.90, 0.95):
            pr_fa = pr_095 = pr_098 = 0.0
            for x in range(n + 1):
                if post_ge(x, n, (1.0, 1.0)) >= conf:
                    pr_fa += pmf(x, n, 0.90)
                    pr_095 += pmf(x, n, 0.95)
                    pr_098 += pmf(x, n, 0.98)
            righe.append(
                {
                    "N": n,
                    "conf": conf,
                    "falso_accept_theta90": round(pr_fa, 4),
                    "accept_theta95": round(pr_095, 4),
                    "accept_theta98": round(pr_098, 4),
                }
            )
    return righe


def foglio_da_risposta(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    docs = [
        doc("DOC-S1", accesso="full text", hash_file="h1", hash_coincide=True),
        doc("DOC-S2", accesso="abstract", hash_file="h2", hash_coincide=True),
        doc("DOC-S3", accesso="non disponibile", hash_file="", hash_coincide=False),
        doc("DOC-S4", accesso="full text", hash_file="h4", hash_coincide=True),
    ]
    inv_map = {"U-03": True, "U-05": False, "U-06": True}
    num_map = {"U-03": True, "U-05": True, "U-06": True}
    non_acq_map = {"U-05": True}
    units = []
    for d in data:
        uid = d["unita"]
        u = unit(
            uid,
            (d.get("esito") or "").strip(),
            numerica=num_map.get(uid, False),
            inventato=inv_map.get(uid, False),
            tipo_errore=d.get("tipo_errore") or "",
        )
        if non_acq_map.get(uid):
            u["documento_acquisito"] = False
            u["stato_accesso"] = "non acquisito"
            u["link_prodotto"] = False
        units.append(u)
    return sheet(docs, units, subs=0, target=20, contrad=(0, 0), prep=(0, 20))


# ============================================================================
# 6. BATTERIA DI VERIFICA MECCANICA COMPLETA (10/10 RT + RT-VNP + 5 PASSI + CSV)
# ============================================================================

def esegui_test():
    checks = []

    def chk(fid, rt_tag, name, got, exp):
        checks.append(
            {
                "fixture": fid,
                "rilievo": rt_tag,
                "check": name,
                "ok": bool(got == exp),
                "atteso": exp,
                "ottenuto": got,
            }
        )

    docs10 = [doc(f"D-{i:02d}") for i in range(1, 11)]

    # G1: Caso sano di riferimento
    g1 = sheet(
        docs10,
        [unit(f"U-{i}", "supporta") for i in range(1, 34)] + [unit("U-34", "insufficiente")],
        contrad=(3, 3),
        tempiA=[12, 14, 15, 17, 20],
        tempiB=[9, 10, 11, 13, 15],
    )
    r_g1 = accettazione3(g1)
    chk("G1", "BASE", "caso sano -> accettata", r_g1["esito"], "accettata")

    # G2 (RT-01): Ciclo append-only v0.2-rev1 in fascia M3b [90%, 95%) e blocco S3 su rev2 / doppio audit
    g2_units = [unit(f"U-{i}", "supporta") for i in range(1, 93)] + [
        unit(f"U-{i}", "insufficiente", tipo_errore="E3") for i in range(93, 101)
    ]
    g2 = sheet(docs10, g2_units)
    r_g2_primo = accettazione3(g2)
    chk("G2a", "RT-01", "primo giro con M3f=92% -> zona_revisione", r_g2_primo["esito"], "zona_revisione")

    sost_rev1 = [
        unit(f"U-{i}-rev1", "supporta", sostituisce_id=f"U-{i}", ciclo="v0.2-rev1") for i in range(93, 98)
    ]
    res_rev1 = applica_ciclo_rev1(g2, sost_rev1)
    chk("G2b", "RT-01", "ciclo v0.2-rev1 append-only -> accettata (M3f=97%)", res_rev1["risultato_rev1"]["esito"], "accettata")
    chk("G2c", "RT-01", "registro append-only conserva 105 righe totali (100+5)", res_rev1["righe_totali_append_only"], 105)
    chk("G2d", "RT-01", "denominatore attivo rev1 = 100 unita", res_rev1["unita_attive_rev1"], 100)

    # Tentativo di rev2 quando rev1 resta < 95%
    sost_rev1_parziale = [
        unit("U-93-rev1", "supporta", sostituisce_id="U-93", ciclo="v0.2-rev1"),
        unit("U-94-rev1", "supporta", sostituisce_id="U-94", ciclo="v0.2-rev1"),
    ]
    res_rev1_fail = applica_ciclo_rev1(sheet(docs10, g2_units), sost_rev1_parziale)
    chk(
        "G2e",
        "RT-01",
        "se dopo v0.2-rev1 M3f=94% (<95%) -> richiede_nuova_versione_protocollo (S3)",
        res_rev1_fail["risultato_rev1"]["esito"],
        "richiede_nuova_versione_protocollo",
    )
    g2_gia_rev1 = sheet(docs10, g2_units, ciclo="v0.2-rev1", audit_count=2)
    res_rev2 = applica_ciclo_rev1(g2_gia_rev1, sost_rev1)
    chk("G2f", "RT-01", "tentativo di terzo giro (rev2) bloccato da S3", res_rev2["esito_blocco"], "blocco_S3_doppio_audit")

    # G3 (RT-02): Esclusione VNP da M2 e soglia minima quota_giudicate >= 80%
    g3 = sheet(docs10, [unit("U-1", "supporta")] + [unit(f"V-{i}", "verifica non possibile") for i in range(1, 100)])
    r_g3 = accettazione3(g3)
    chk("G3a", "RT-02", "1 supporta + 99 VNP -> fallimento_strutturale (quota 1% < 80%)", r_g3["esito"], "fallimento_strutturale")
    for u in g3["unita"][1:]:
        u["link_prodotto"] = False
        u["link_ok"] = False
    r_g3b = accettazione3(g3)
    chk("G3b", "RT-02", "VNP con link_ok=False non abbassa M2e (M2e = 1.0)", r_g3b["metriche"]["M2e"]["val"], 1.0)

    # G4 (RT-03): Separazione fedelta M3f vs polarita/direzione M3
    g4_units = [unit(f"U-{i}", "supporta") for i in range(1, 190)] + [unit(f"U-{i}", "contrasta") for i in range(190, 200)]
    r_g4 = accettazione3(sheet(docs10, g4_units, contrad=(10, 10)))
    chk("G4a", "RT-03", "189 supporta + 10 contrasta fedeli -> accettata (M3f=100%)", r_g4["esito"], "accettata")
    chk("G4b", "RT-03", "M3 descrittivo misura la direzione (94,975%)", round(r_g4["metriche"]["M3"]["val"], 5), round(189 / 199, 5))
    chk("G4c", "RT-03", "M3f misura la fedelta dell'estratto (100%)", r_g4["metriche"]["M3f"]["val"], 1.0)

    # G5 (RT-04): Errori E1 ed E2 bloccano l'accettazione tramite M4b = 0
    g5_e1 = [unit(f"U-{i}", "supporta") for i in range(1, 21)]
    g5_e1[19]["tipo_errore"] = "E1"
    r_g5_e1 = accettazione3(sheet(docs10, g5_e1))
    chk("G5a", "RT-04", "errore E1 con M3=100% e M4=0 blocca l'accettazione (M4b=1)", r_g5_e1["esito"], "fallimento_strutturale")
    g5_e2 = [unit(f"U-{i}", "supporta") for i in range(1, 21)]
    g5_e2[0]["tipo_errore"] = "E2"
    r_g5_e2 = accettazione3(sheet(docs10, g5_e2))
    chk("G5b", "RT-04", "errore E2 con M3=100% e M4=0 blocca l'accettazione (M4b=1)", r_g5_e2["esito"], "fallimento_strutturale")

    # G6 (RT-05): Paradosso del denominatore zero per M4 e M8
    g6 = sheet(docs10, [unit(f"U-{i}", "supporta") for i in range(1, 31)], contrad=(0, 0))
    r_g6 = accettazione3(g6)
    chk("G6a", "RT-05", "zero affermazioni numeriche e zero contraddizioni -> accettata", r_g6["esito"], "accettata")
    chk("G6b", "RT-05", "M4 con denominatore zero ha val=None ma regola_zero=True", (r_g6["metriche"]["M4"]["val"], r_g6["metriche"]["M4"]["regola_zero"]), (None, True))
    chk("G6c", "RT-05", "M8 con denominatore zero ha val=None ma soddisfatta=True", (r_g6["metriche"]["M8"]["val"], r_g6["metriche"]["M8"]["soddisfatta"]), (None, True))

    # G7 (RT-06): Blocco anti-contaminazione revisori L1 -> L2 e verifica crossover controbilanciato
    piano_ok = {
        "R2": [{"blocco": "Blocco_A", "condizione": "A"}, {"blocco": "Blocco_B", "condizione": "B"}],
        "R3": [{"blocco": "Blocco_A", "condizione": "B"}, {"blocco": "Blocco_B", "condizione": "A"}],
    }
    piano_contaminato = {
        "R1": [{"blocco": "Blocco_A", "condizione": "A"}, {"blocco": "Blocco_B", "condizione": "B"}],
        "R2": [{"blocco": "Blocco_A", "condizione": "B"}, {"blocco": "Blocco_B", "condizione": "A"}],
    }
    piano_sbilanciato = {
        "R2": [{"blocco": "Blocco_A", "condizione": "A"}, {"blocco": "Blocco_B", "condizione": "B"}],
        "R3": [{"blocco": "Blocco_A", "condizione": "A"}, {"blocco": "Blocco_B", "condizione": "B"}],
    }
    v_cont = valida_passaggio_L1_L2(["R1"], "R1", "R2", piano_contaminato, modalita_F0="sequenziale_L1_poi_L2")
    chk("G7a", "RT-06", "revisore R1 di L1 riutilizzato in L2 su stesso corpus -> bloccato", v_cont["valido"], False)
    v_sbil = valida_passaggio_L1_L2(["R1"], "R2", "R3", piano_sbilanciato, modalita_F0="sequenziale_L1_poi_L2")
    chk("G7b", "RT-06", "crossover con entrambi i revisori A->B -> bloccato", v_sbil["valido"], False)
    v_ok = valida_passaggio_L1_L2(["R1"], "R2", "R3", piano_ok, modalita_F0="sequenziale_L1_poi_L2")
    chk("G7c", "RT-06", "revisori freschi R2/R3 con crossover A->B / B->A -> valido", v_ok["valido"], True)

    # G8 (RT-07): Verifica hash sui soli file leggibili e tetto E8 <= 10% (<= 2 su 20)
    docs20_ok = (
        [doc(f"D-{i:02d}", accesso="full text", hash_file=f"sha_{i}", hash_coincide=True) for i in range(1, 17)]
        + [doc("D-17", accesso="metadato", hash_file="", hash_coincide=False), doc("D-18", accesso="non disponibile", hash_file="", hash_coincide=False)]
        + [
            doc("D-19", accesso="full text", hash_file="", hash_coincide=False, errore_prep_E8=True, motivo_E8="PDF corrotto"),
            doc("D-20", accesso="full text", hash_file="", hash_coincide=False, errore_prep_E8=True, motivo_E8=" Scansione illeggibile"),
        ]
    )
    r_g8a = accettazione3(sheet(docs20_ok, [unit(f"U-{i}", "supporta") for i in range(1, 31)], target=20))
    chk("G8a", "RT-07", "16 full text con hash ok + 2 non disp senza hash + 2 E8 (10%) -> M1=100%, accettata", r_g8a["esito"], "accettata")

    docs20_bad_hash = list(docs20_ok)
    docs20_bad_hash[0] = doc("D-01", accesso="full text", hash_file="sha_1", hash_coincide=False)
    r_g8b = accettazione3(sheet(docs20_bad_hash, [unit(f"U-{i}", "supporta") for i in range(1, 31)], target=20))
    chk("G8b", "RT-07", "hash non coincidente su file leggibile -> fallimento_strutturale", r_g8b["esito"], "fallimento_strutturale")

    docs20_troppi_e8 = list(docs20_ok)
    docs20_troppi_e8[15] = doc("D-16", accesso="full text", hash_file="", hash_coincide=False, errore_prep_E8=True, motivo_E8="3o illeggibile")
    r_g8c = accettazione3(sheet(docs20_troppi_e8, [unit(f"U-{i}", "supporta") for i in range(1, 31)], target=20))
    chk("G8c", "RT-07", "3 documenti E8 su 20 (15% > 10%) -> fallimento_strutturale", r_g8c["esito"], "fallimento_strutturale")

    # G9 (RT-08): Calcolo di M7 su unita pre-allineate in F5 vs rifiuto tra schede eterogenee A/B
    m7_etero = calcola_M7_F5(scheda_A_libera=["nota libera 1"], scheda_B_matrice=[{"id": "U-1", "esito": "supporta"}])
    chk("G9a", "RT-08", "M7 tra scheda libera A e matrice B in F3/F4 -> non calcolabile", m7_etero["calcolabile"], False)
    unita_f5_test = [
        {"id": f"U-{i}", "esito_lettore": "supporta", "esito_revisore": "supporta"} for i in range(1, 8)
    ] + [
        {"id": "U-8", "esito_lettore": "contrasta", "esito_revisore": "contrasta"},
        {"id": "U-9", "esito_lettore": "parziale", "esito_revisore": "parziale"},
        {"id": "U-10", "esito_lettore": "parziale", "esito_revisore": "contrasta"},
    ]
    m7_f5 = calcola_M7_F5(unita_f5=unita_f5_test)
    chk("G9b", "RT-08", "M7 in F5 su 10 unita pre-allineate -> accordo 0.90 (>=80%) e 1 disaccordo", (m7_f5["calcolabile"], m7_f5["accordo_grezzo"], len(m7_f5["disaccordi"])), (True, 0.9, 1))

    # G10 (RT-09): Arresto per budget S2 chiude le unita aperte come non_valutata_budget
    g10_units = [unit(f"U-{i}", "supporta") for i in range(1, 11)] + [unit("U-11", ""), unit("U-12", "")]
    g10 = sheet(docs10, g10_units, stop="S2")
    r_g10 = accettazione3(g10)
    aperte_dopo_s2 = sum(1 for u in g10["unita"] if u["esito"] == "")
    budget_dopo_s2 = sum(1 for u in g10["unita"] if u["esito"] == STATO_BUDGET)
    chk("G10a", "RT-09", "arresto S2 chiude le 2 unita aperte come non_valutata_budget -> non_concluso_budget", (r_g10["esito"], aperte_dopo_s2, budget_dopo_s2), ("non_concluso_budget", 0, 2))
    g10_illegale = sheet(docs10, [unit(f"U-{i}", "supporta") for i in range(1, 11)] + [unit("U-11", STATO_BUDGET)], stop=None)
    r_g10b = accettazione3(g10_illegale)
    chk("G10b", "RT-09", "stato non_valutata_budget senza stop S2 -> fallimento_strutturale", r_g10b["esito"], "fallimento_strutturale")

    # G11 (RT-10): Intervallo continuo [90%, 95%), multi-etichetta tipo_errore e M4 per unita
    g11_units = [unit(f"U-{i}", "supporta") for i in range(1, 190)] + [
        unit(f"U-{i}", "insufficiente", tipo_errore="E3") for i in range(190, 200)
    ]
    r_g11a = accettazione3(sheet(docs10, g11_units))
    chk("G11a", "RT-10", "M3f = 189/199 (94,97487%) cade in zona_revisione [90%, 95%)", r_g11a["esito"], "zona_revisione")
    g11_multi = [unit(f"U-{i}", "supporta") for i in range(1, 20)] + [
        unit("U-20", "contrasta", numerica=True, inventato=True, tipo_errore="E2, E7")
    ]
    r_g11b = accettazione3(sheet(docs10, g11_multi))
    chk(
        "G11b",
        "RT-10",
        "multi-etichetta 'E2, E7' parsata e contata per unita (M4=1, M4b=1)",
        (sorted(codici(g11_multi[-1])), r_g11b["metriche"]["M4"]["num"], r_g11b["metriche"]["M4b"]["num"]),
        (["E2", "E7"], 1, 1),
    )

    # G12 (RT-VNP + Procedura a 5 passi): 5 casi di calibrazione C1..C5 + 8 unita del packet v0.2
    calibrazione = [
        {"unita": "C1", "direzione_ok_dettaglio_o_quantita_assente": True, "numero_assente_non_quantificato": True},
        {"unita": "C2", "contraddice_qualifica_o_direzione": True},
        {"unita": "C3", "valore_numerico_smentito": True},
        {"unita": "C4"},
        {"unita": "C5", "documento_acquisito": False},
    ]
    esiti_cal = [(procedura_5passi(c)["esito"], procedura_5passi(c)["tipo_errore"]) for c in calibrazione]
    attesi_cal = [
        ("parziale", "E7"),
        ("contrasta", None),
        ("contrasta", "E7"),
        ("supporta", None),
        ("verifica non possibile", None),
    ]
    chk("G12a", "5-PASSI", "5 casi di calibrazione C1..C5 classificati esattamente", esiti_cal, attesi_cal)

    packet_v02_items = [
        {"unita": "U-01"},
        {"unita": "U-02", "contraddice_qualifica_o_direzione": True},
        {"unita": "U-03", "direzione_ok_dettaglio_o_quantita_assente": True, "numero_assente_non_quantificato": True},
        {"unita": "U-04", "preliminare_o_vago": True},
        {"unita": "U-05", "documento_acquisito": False},
        {"unita": "U-06", "valore_numerico_smentito": True},
        {"unita": "U-07"},
        {"unita": "U-08", "contraddice_qualifica_o_direzione": True, "pseudo_citazione_testuale": True},
    ]
    key2_attesa = {
        "U-01": ("supporta", None),
        "U-02": ("contrasta", None),
        "U-03": ("parziale", "E7"),
        "U-04": ("insufficiente", None),
        "U-05": ("verifica non possibile", None),
        "U-06": ("contrasta", "E7"),
        "U-07": ("supporta", None),
        "U-08": ("contrasta", "E1"),
    }
    got_packet = {x["unita"]: (procedura_5passi(x)["esito"], procedura_5passi(x)["tipo_errore"]) for x in packet_v02_items}
    chk("G12b", "5-PASSI", "8 unita del packet v0.2 riproducono 8/8 stati e codici della chiave", got_packet, key2_attesa)

    u_vnp_spurio = unit("U-05", "verifica non possibile", tipo_errore="E2")
    u_vnp_spurio["documento_acquisito"] = False
    chk("G12c", "RT-VNP", "codice spurio E2 su verifica non possibile per non acquisizione viene bloccato", valida_vnp_unita(u_vnp_spurio)["ok"], False)

    # G13: Validatore CSV a 20 colonne
    val_tpl = valida_csv_scheda(CSV_SCHEDA, modalita="template")
    chk("G13a", "CSV-20", "template Diotima_scheda_audit_v0.2.csv valido a 20 colonne", (val_tpl["valido"], val_tpl["n_colonne"]), (True, 20))
    val_exec_esempio = valida_csv_scheda(CSV_SCHEDA, modalita="esecuzione")
    chk("G13b", "CSV-20", "modalita esecuzione blocca se le 2 righe di esempio non sono state rimosse", val_exec_esempio["valido"], False)

    csv_operativo = [
        ";".join(HEADER_ATTESO_20),
        "DOCUMENTO;DOC-01;;;;;;full text;sì;a1b2c3d4;;;;;;;;;;fonte EuropePMC, CC-BY",
        "UNITA;U-01;DOC-01;Affermazione verificata;claim;primary_excerpt;verified_primary;full text;;;p. 4;p. 4;sì;supporta;;5;R1;R2;;ok",
    ]
    val_op = valida_csv_scheda(csv_operativo, modalita="esecuzione")
    chk("G13c", "CSV-20", "foglio CSV operativo pulito a 20 colonne -> valido", val_op["valido"], True)

    return checks


def run():
    checks = esegui_test()

    fogli = {}
    for nome, fn in (
        ("A", "A_gemini.json"),
        ("B", "B_glm.json"),
        ("C", "C_deepseek.json"),
        ("A2", "A2_gemini.json"),
        ("B2", "B2_glm.json"),
        ("C2", "C2_deepseek.json"),
    ):
        p = ROOT / "risposte" / fn
        if not p.exists():
            fogli[nome] = {"stato": "in attesa"}
            continue
        s = foglio_da_risposta(p)
        r3 = accettazione3(s)
        fogli[nome] = {
            "stato": "presente",
            "v03_esito": r3["esito"],
            "v03_M3_direzione": round(r3["metriche"]["M3"]["val"], 4),
            "v03_M3f_fedelta": round(r3["metriche"]["M3f"]["val"], 4),
            "v03_M4_numeri_E7": r3["metriche"]["M4"]["num"],
            "v03_M4b_bloccanti": r3["metriche"]["M4b"]["num"],
            "v03_quota_giudicate": round(r3["metriche"]["quota_giudicate"]["val"], 4),
            "v03_motivi": r3["motivi"],
        }

    copertura_rt = {
        "RT-01": "Chiuso meccanicamente (G2a..G2f): ciclo append-only v0.2-rev1 da zona_revisione e blocco S3 su rev2/doppio audit",
        "RT-02": "Chiuso meccanicamente (G3a..G3b): VNP escluse da M2e e soglia obbligatoria quota_giudicate >= 80%",
        "RT-03": "Chiuso meccanicamente (G4a..G4c): M3f (fedelta dell'estratto) governa l'accettazione, M3 (direzione) descrittivo, M8 conserva contraddizioni",
        "RT-04": "Chiuso meccanicamente (G5a..G5b): M4b = conteggio(E1, E2, E7) = 0 obbligatorio per l'accettazione",
        "RT-05": "Chiuso meccanicamente (G6a..G6c): denominatori zero per M4 (soddisfatta se num=0) e M8 (soddisfatta se den=0)",
        "RT-06": "Chiuso meccanicamente (G7a..G7c): blocco anti-contaminazione revisori L1->L2 e validatore crossover controbilanciato",
        "RT-07": "Chiuso meccanicamente (G8a..G8c): verifica hash sui soli file leggibili acquisiti e tetto E8 <= 10% (<=2/20)",
        "RT-08": "Chiuso meccanicamente (G9a..G9b): rifiuto M7 su schede eterogenee A/B e calcolo in F5 su unita pre-allineate",
        "RT-09": "Chiuso meccanicamente (G10a..G10b): chiusura legale con stato non_valutata_budget sotto regola S2",
        "RT-10": "Chiuso meccanicamente (G11a..G11b): M3b = [90%, 95%) senza buchi, multi-etichetta tipo_errore con ',' e M4 per unita",
        "RT-VNP": "Chiuso meccanicamente (G12a..G12c): non acquisizione al Passo 1 con tipo_errore vuoto e blocco codici spuri",
    }

    risultati = {
        "versione": "motore v0.3 (completo e autonomo: 10/10 RT + RT-VNP + procedura 5 passi + validatore CSV 20 col)",
        "data": "2026-10-18",
        "copertura_rilievi": copertura_rt,
        "fixtures": checks,
        "fogli": fogli,
        "validazione_csv_scheda": valida_csv_scheda(CSV_SCHEDA, modalita="template"),
        "soglie_congiunte": soglie_congiunte(),
        "riepilogo": {
            "rilievi_rt_chiusi": "10/10 + RT-VNP",
            "check_totali": len(checks),
            "check_ok": sum(1 for c in checks if c["ok"]),
            "tutti_ok": all(c["ok"] for c in checks),
        },
    }

    OUT.write_text(json.dumps(risultati, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(risultati["riepilogo"], ensure_ascii=False))
    for c in checks:
        status = "OK  " if c["ok"] else "FAIL"
        print(f"{status} [{c['fixture']} · {c['rilievo']}] {c['check']} | atteso: {c['atteso']} | ottenuto: {c['ottenuto']}")


if __name__ == "__main__":
    run()
