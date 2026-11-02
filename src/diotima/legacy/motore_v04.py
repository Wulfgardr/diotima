#!/usr/bin/env python3
"""
Motore Statistico-Causale Diotima v0.4 (`motore_mcelreath_v0_4.py`)
===================================================================
Implementazione in Python 3.11+ puro (zero dipendenze esterne: solo stdlib
`math`, `random`, `json`, `dataclasses`, `typing`, `hashlib`, `statistics`)
radicata in:
  - Richard McElreath, *Statistical Rethinking: A Bayesian Course with Examples
    in R and Stan* (2nd Ed., Chapman & Hall/CRC, 2020)
  - Standard metodologici del dossier Diotima `S01–S20` e rilievi `RT-01..RT-10` + `RT-VNP`

Moduli implementati:
  1. Cap. 2 & Cap. 3 (pp. 40–68):
     - Distribuzione posteriore Beta-Binomiale esatta e per Grid Approximation
     - Compatibility Intervals (CI / PI e HPDI all'80%, 89% McElreath, 95%)
     - Funzione di perdita asimmetrica L(d, p) = c_FN * p * I(d=accept) + c_FP * (1 - p_max + p) * I(d=reject)
     - Pianificatore di taglia campionaria personalizzabile (`plan_custom_sample_size`)
       con i 5 profili (`esplorativo`, `equilibrato`, `rigoroso`, `confermativo`, `personalizzato`)
  2. Cap. 6 (§6.3 pp. 161–162, 176–178):
     - Simulatore e correttore bayesiano del Collider Bias di selezione letteraria (T -> S <- N)
     - Punteggio di Vaglio Epistemico Diotima (`vaglio_epistemico_mcelreath`) ancorato a
       RoB 2 (S03), ROBINS-I (S04), GRADE (S05/S06) e disegno di studio
  3. Cap. 12 & Cap. 13 (pp. 369–375, 399–420):
     - Sovradispersione Beta-Binomiale e stimatore gerarchico Multilevel con Partial Pooling
       per unità di claim annidate nei documenti (`UNITA` in `DOC`), pesi di shrinkage McElreath
       w_j = n_j / (n_j + sigma^2 / tau^2) e correlazione intra-documento rho_ICC
  4. Cap. 15 (pp. 499–521):
     - Classificatore causale dei full-text mancanti (`verifica non possibile`) secondo i 3 regimi
       del DAG di McElreath Fig. 15.4 p. 500: (a) MCAR, (b) MAR condizionato a S, (c) MNAR dipendente da H,
       con calcolo dei bounds di Manski/McElreath
     - Modello di lettura progressiva a 5 livelli (`L0..L4`) con marginalizzazione sull'errore
       categoriale dei lettori (§15.3) ed entropia posteriore per l'attivazione dell'adjudicazione umana
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field, asdict
import hashlib
import json
import math
import random
import statistics
from typing import Any, Dict, List, Optional, Tuple


# ============================================================================
# COSTANTI METODOLOGICHE E PROFILI CAMPIONARI (S01-S20 & McElreath Cap. 2-3)
# ============================================================================

# Tassonomia chiusa dei tipi di claim (contratto `diotima_progressive_reader`, enum API).
# Valori fuori tassonomia rifiutati con ValueError (fail-closed): nessun fallback silenzioso.
ENUM_CLAIM_TYPE: Tuple[str, ...] = (
    "quantitative",
    "methodological",
    "qualitative",
    "stopping_rule",
    "clinical_outcome",
)


def _valida_intero(nome_param: str, valore: Any, minimo: Optional[int] = None, massimo: Optional[int] = None) -> int:
    """Validazione fail-closed di un intero (bool escluso perche' isinstance(bool, int))."""
    if isinstance(valore, bool) or not isinstance(valore, int):
        raise ValueError(f"{nome_param} deve essere un numero intero; ricevuto: {valore!r}")
    if minimo is not None and valore < minimo:
        raise ValueError(f"{nome_param} deve essere >= {minimo}; ricevuto: {valore}")
    if massimo is not None and valore > massimo:
        raise ValueError(f"{nome_param} deve essere <= {massimo}; ricevuto: {valore}")
    return valore


def _valida_finito(nome_param: str, valore: Any, minimo: Optional[float] = None) -> float:
    """Validazione fail-closed di un numero finito (bool/str/NaN/inf rifiutati).

    bool e str NON sono coeribili in numeri (float(True)=1.0, float("1.5")=1.5):
    il contratto di dominio esige num=numero, altrimenti ValueError (rev. C11).
    """
    if isinstance(valore, bool) or not isinstance(valore, (int, float)):
        raise ValueError(f"{nome_param} deve essere un numero finito; ricevuto: {valore!r}")
    v = float(valore)
    if not math.isfinite(v):
        raise ValueError(f"{nome_param} deve essere un numero finito; ricevuto: {valore!r}")
    if minimo is not None and v < minimo:
        raise ValueError(f"{nome_param} deve essere >= {minimo}; ricevuto: {v}")
    return v


def _valida_prior(nome_param: str, prior: Any) -> Tuple[float, float]:
    """Valida una prior coniugata Beta(alpha_0, beta_0): esattamente 2 componenti finita e > 0."""
    if isinstance(prior, bool) or not isinstance(prior, (tuple, list)) or len(prior) != 2:
        raise ValueError(f"{nome_param} deve essere (alpha_0, beta_0) con due componenti; ricevuto: {prior!r}")
    a0 = _valida_finito(f"{nome_param}[0] (alpha_0)", prior[0])
    b0 = _valida_finito(f"{nome_param}[1] (beta_0)", prior[1])
    if a0 <= 0.0 or b0 <= 0.0:
        raise ValueError(f"{nome_param} deve avere alpha_0 > 0 e beta_0 > 0 (prior Beta positiva); ricevuto: {prior!r}")
    return a0, b0


PROFILI_CAMPIONARI: Dict[str, Dict[str, Any]] = {
    "esplorativo": {
        "N": 30,
        "confidenza": 0.70,
        "p_max": 0.05,
        "prior": (1.0, 1.0),
        "loss_ratio_fn_fp": 4.0,
        "descrizione": "Pre-pilota rapido (N=30, confidenza 70%, p_max=5%)",
    },
    "equilibrato": {
        "N": 60,
        "confidenza": 0.80,
        "p_max": 0.05,
        "prior": (1.0, 1.0),
        "loss_ratio_fn_fp": 8.0,
        "descrizione": "Profilo di riferimento Diotima F0 (N=60, confidenza 80%, p_max=5%)",
    },
    "rigoroso": {
        "N": 90,
        "confidenza": 0.90,
        "p_max": 0.05,
        "prior": (1.0, 1.0),
        "loss_ratio_fn_fp": 12.0,
        "descrizione": "Audit ad alta garanzia (N=90, confidenza 90%, p_max=5%)",
    },
    "confermativo": {
        "N": 114,
        "confidenza": 0.95,
        "p_max": 0.05,
        "prior": (1.0, 1.0),
        "loss_ratio_fn_fp": 19.0,
        "descrizione": "Validazione confermativa piena (N=114, confidenza 95%, p_max=5%, k_max=1)",
    },
}

STATI_DIOTIMA_5 = (
    "supporta",
    "parziale",
    "contrasta",
    "insufficiente",
    "verifica non possibile",
)


# ============================================================================
# 1. FUNZIONI MATEMATICHE BETA-BINOMIALI ESATTE, QUANTILI E GRID (Cap. 2 & 3)
# ============================================================================

def _betacf(a: float, b: float, x: float) -> float:
    """Frazione continua di Lentz per la funzione Beta incompleta regolarizzata."""
    maxit = 400
    eps = 3.0e-16
    fpmin = 1.0e-300
    qab = a + b
    qap = a + 1.0
    qam = a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < fpmin:
        d = fpmin
    d = 1.0 / d
    h = d
    for m in range(1, maxit + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < fpmin:
            d = fpmin
        c = 1.0 + aa / c
        if abs(c) < fpmin:
            c = fpmin
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < fpmin:
            d = fpmin
        c = 1.0 + aa / c
        if abs(c) < fpmin:
            c = fpmin
        d = 1.0 / d
        del_val = d * c
        h *= del_val
        if abs(del_val - 1.0) < eps:
            break
    return h


def beta_cdf(x: float, a: float, b: float) -> float:
    """CDF esatta I_x(a, b) della distribuzione Beta(a, b)."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    lbt = (
        math.lgamma(a + b)
        - math.lgamma(a)
        - math.lgamma(b)
        + a * math.log(x)
        + b * math.log(1.0 - x)
    )
    bt = math.exp(lbt)
    if x < (a + 1.0) / (a + b + 2.0):
        return bt * _betacf(a, b, x) / a
    return 1.0 - bt * _betacf(b, a, 1.0 - x) / b


def beta_pdf(x: float, a: float, b: float) -> float:
    """Densità di probabilità Beta(a, b) in x."""
    if x <= 0.0 or x >= 1.0:
        if x == 0.0 and a == 1.0:
            return b
        if x == 1.0 and b == 1.0:
            return a
        return 0.0
    lpdf = (
        math.lgamma(a + b)
        - math.lgamma(a)
        - math.lgamma(b)
        + (a - 1.0) * math.log(x)
        + (b - 1.0) * math.log(1.0 - x)
    )
    return math.exp(lpdf)


def beta_quantile(prob: float, a: float, b: float, tol: float = 1e-10) -> float:
    """Inversa della CDF Beta(a, b) tramite bisezione monotona ad alta precisione."""
    if prob <= 0.0:
        return 0.0
    if prob >= 1.0:
        return 1.0
    lo, hi = 0.0, 1.0
    for _ in range(80):
        mid = 0.5 * (lo + hi)
        if beta_cdf(mid, a, b) < prob:
            lo = mid
        else:
            hi = mid
        if (hi - lo) < tol:
            break
    return 0.5 * (lo + hi)


def binom_pmf(k: int, n: int, p: float) -> float:
    """PMF binomiale esatta P(K = k | n, p)."""
    if k < 0 or k > n:
        return 0.0
    if p <= 0.0:
        return 1.0 if k == 0 else 0.0
    if p >= 1.0:
        return 1.0 if k == n else 0.0
    log_pmf = (
        math.lgamma(n + 1)
        - math.lgamma(k + 1)
        - math.lgamma(n - k + 1)
        + k * math.log(p)
        + (n - k) * math.log(1.0 - p)
    )
    return math.exp(log_pmf)


def compatibility_intervals_beta(
    alpha_post: float,
    beta_post: float,
    levels: Tuple[float, ...] = (0.80, 0.89, 0.95),
    grid_size: int = 2001,
) -> Dict[str, Any]:
    """
    McElreath Cap. 3 (pp. 54–58): Calcola i Compatibility Intervals (sia Percentile
    Intervals PI esatti sui quantili sia Highest Posterior Density Intervals HPDI su
    griglia) alle soglie 80%, 89% (scelta canonica di McElreath contro l'abuso dei test
    al 95%) e 95%.
    """
    mean = alpha_post / (alpha_post + beta_post)
    var = (
        (alpha_post * beta_post)
        / (((alpha_post + beta_post) ** 2) * (alpha_post + beta_post + 1.0))
    )
    sd = math.sqrt(var)
    if alpha_post > 1.0 and beta_post > 1.0:
        mode = (alpha_post - 1.0) / (alpha_post + beta_post - 2.0)
    elif alpha_post <= 1.0 and beta_post > 1.0:
        mode = 0.0
    elif alpha_post > 1.0 and beta_post <= 1.0:
        mode = 1.0
    else:
        mode = 0.5

    # Grid Approximation (McElreath R code 2.3, p. 40)
    grid_p = [i / (grid_size - 1) for i in range(grid_size)]
    raw_weights = [beta_pdf(x, alpha_post, beta_post) for x in grid_p]
    tot_w = sum(raw_weights) or 1.0
    post_w = [w / tot_w for w in raw_weights]

    # Ordina i punti della griglia per densità decrescente per il calcolo dell'HPDI
    idx_sorted = sorted(range(grid_size), key=lambda i: post_w[i], reverse=True)

    pi_dict: Dict[str, List[float]] = {}
    hpdi_dict: Dict[str, List[float]] = {}
    for lvl in levels:
        key = f"{int(round(lvl * 100))}%"
        tail = 0.5 * (1.0 - lvl)
        q_lo = beta_quantile(tail, alpha_post, beta_post)
        q_hi = beta_quantile(1.0 - tail, alpha_post, beta_post)
        pi_dict[key] = [round(q_lo, 5), round(q_hi, 5)]

        cum = 0.0
        included = []
        for idx in idx_sorted:
            included.append(grid_p[idx])
            cum += post_w[idx]
            if cum >= lvl:
                break
        hpdi_dict[key] = [round(min(included), 5), round(max(included), 5)]

    return {
        "alpha_post": round(alpha_post, 4),
        "beta_post": round(beta_post, 4),
        "mean": round(mean, 5),
        "median": round(beta_quantile(0.50, alpha_post, beta_post), 5),
        "mode_map": round(mode, 5),
        "sd": round(sd, 5),
        "percentile_intervals_PI": pi_dict,
        "highest_posterior_density_HPDI": hpdi_dict,
        "grid_size": grid_size,
    }


def mcelreath_asymmetric_loss(
    k_errors: int,
    n_trials: int,
    p_max: float = 0.05,
    prior: Tuple[float, float] = (1.0, 1.0),
    c_fn: float = 8.0,
    c_fp: float = 1.0,
) -> Dict[str, Any]:
    """
    McElreath Cap. 3 (§3.2.3 pp. 59–62, Loss Functions):
    Modella la decisione operativa d in {'accept', 'reject'} sul tasso latente di
    infedeltà/errore p in [0, 1] con distribuzione posteriore Beta(alpha_0 + k, beta_0 + N - k).

    Funzione di perdita asimmetrica di Diotima:
      L(d, p) = c_FN * p * I(d = 'accept') + c_FP * (1 - p_max + p) * I(d = 'reject')

    Per linearità dell'attesa rispetto alla posteriore di p con media E[p | k, N] = mu_p:
      E[L('accept', p) | k, N] = c_FN * mu_p
      E[L('reject', p) | k, N] = c_FP * (1 - p_max + mu_p)

    La decisione bayesiana ottima minimizza la perdita attesa posteriore:
      d* = 'accept'  <=>  c_FN * mu_p <= c_FP * (1 - p_max + mu_p)
                     <=>  mu_p <= (1 - p_max) / (c_FN / c_FP - 1)   (per c_FN > c_FP)
    """
    _valida_intero("k_errors", k_errors, minimo=0)
    _valida_intero("n_trials", n_trials, minimo=0)
    if k_errors > n_trials:
        raise ValueError(f"k_errors ({k_errors}) non puo' superare n_trials ({n_trials})")
    if not isinstance(p_max, (int, float)) or isinstance(p_max, bool) or not math.isfinite(float(p_max)) or p_max <= 0.0 or p_max > 1.0:
        raise ValueError(f"p_max deve essere in (0, 1]; ricevuto: {p_max!r}")
    a0, b0 = _valida_prior("prior", prior)
    c_fn_norm = _valida_finito("c_fn (costo falso negativo)", c_fn)
    c_fp_norm = _valida_finito("c_fp (costo falso positivo)", c_fp)
    if c_fn_norm <= 0.0 or c_fp_norm <= 0.0:
        raise ValueError("c_fn e c_fp devono essere costi positivi")

    alpha_p = a0 + k_errors
    beta_p = b0 + (n_trials - k_errors)
    mu_p = alpha_p / (alpha_p + beta_p)

    expected_loss_accept = c_fn_norm * mu_p
    expected_loss_reject = c_fp_norm * (1.0 - p_max + mu_p)
    prob_p_le_pmax = beta_cdf(p_max, alpha_p, beta_p)

    ratio = c_fn_norm / c_fp_norm if c_fp_norm > 0 else float("inf")
    if ratio > 1.0:
        soglia_media_p = (1.0 - p_max) / (ratio - 1.0)
    else:
        soglia_media_p = 1.0

    decision_loss = "accept" if expected_loss_accept <= expected_loss_reject else "reject"

    return {
        "k_errors": k_errors,
        "n_trials": n_trials,
        "p_max": p_max,
        "c_FN": c_fn_norm,
        "c_FP": c_fp_norm,
        "loss_ratio_fn_fp": round(ratio, 4),
        "posterior_mean_error_p": round(mu_p, 5),
        "posterior_mean_fidelity_theta": round(1.0 - mu_p, 5),
        "prob_p_le_pmax": round(prob_p_le_pmax, 5),
        "expected_loss_accept": round(expected_loss_accept, 5),
        "expected_loss_reject": round(expected_loss_reject, 5),
        "critical_mean_p_threshold": round(min(1.0, soglia_media_p), 5),
        "optimal_decision_loss": decision_loss,
    }


def _trova_n_minimo_per_confidenza(
    k: int,
    p_max: float,
    conf: float,
    a0: float,
    b0: float,
    n_max: int = 100_000,
) -> Optional[int]:
    """Ricerca binaria monotona esatta del minimo N che raggiunge la confidenza richiesta.

    Con k errori ammessi su N unita' giudicate e prior coniugata Beta(a0, b0), la
    probabilita' posteriore Pr(p <= p_max | k, N) = beta_cdf(p_max, a0 + k, b0 + N - k)
    e' strettamente crescente in N >= max(1, k) per 0 < p_max < 1 (aumenta la massa
    posteriore sotto p_max). First-search: bisezione esatta su interi, zero clamp
    silenziosi. Casi limite:
      - p_max == 0.0: beta_cdf = 0.0 < conf (per conf > 0) -> None (irraggiungibile);
      - p_max == 1.0: beta_cdf = 1.0 >= conf per ogni N ammesso -> max(1, k).
    """
    k_norm = _valida_intero("k", k, minimo=0)
    _valida_intero("n_max", n_max, minimo=1)
    if isinstance(p_max, bool) or not isinstance(p_max, (int, float)) or not math.isfinite(float(p_max)) or p_max < 0.0 or p_max > 1.0:
        raise ValueError(f"p_max deve essere in [0, 1]; ricevuto: {p_max!r}")
    if isinstance(conf, bool) or not isinstance(conf, (int, float)) or not math.isfinite(float(conf)) or conf <= 0.0 or conf > 1.0:
        raise ValueError(f"conf deve essere in (0, 1]; ricevuto: {conf!r}")
    a0, b0 = _valida_prior("prior", (a0, b0))
    eff_p_max = float(p_max)
    eff_conf = float(conf)
    if eff_conf >= 1.0 and eff_p_max < 1.0:
        # In aritmetica esatta, per 0 <= p_max < 1 e a,b > 0, I_{p_max}(a, b) < 1 per ogni N finito
        # (evita saturazione IEEE-754 double a 1.0 intorno a N~1000).
        return None

    lo = max(1, k_norm)

    def conf_at(n: int) -> float:
        return beta_cdf(eff_p_max, a0 + k_norm, b0 + (n - k_norm))

    if lo > n_max:
        return None
    if conf_at(lo) >= eff_conf:
        return lo
    hi = n_max
    if conf_at(hi) < eff_conf:
        return None
    # Invariante: conf_at(lo) < conf <= conf_at(hi)
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if conf_at(mid) >= eff_conf:
            hi = mid
        else:
            lo = mid
    return hi


def plan_custom_sample_size(
    profilo: str = "equilibrato",
    p_max: Optional[float] = None,
    confidenza: Optional[float] = None,
    prior: Optional[Tuple[float, float]] = None,
    k_max_override: Optional[int] = None,
    loss_ratio_fn_fp: Optional[float] = None,
    n_custom: Optional[int] = None,
    richiedi_adeguatezza: bool = False,
) -> Dict[str, Any]:
    """
    Pianificatore di Taglia Campionaria Personalizzabile (`plan_custom_sample_size`).
    Supporta i 5 profili:
      - 'esplorativo':    N=30,  conf=70%, p_max=0.05
      - 'equilibrato':    N=60,  conf=80%, p_max=0.05  [default]
      - 'rigoroso':       N=90,  conf=90%, p_max=0.05
      - 'confermativo':   N=114, conf=95%, p_max=0.05
      - 'personalizzato': calcola N minimo per garantire Pr(p <= p_max | k <= k_max, N) >= confidenza
                          oppure valuta l'N specificato dall'utente con prior Beta(alpha_0, beta_0)
                          e rapporto di perdita asimmetrica c_FN / c_FP di McElreath Cap. 3.

    Adeguatezza fail-closed (v0.5): l'output espone `k_max_ammissibile_a_N`, `regola_inerte`,
    `piano_adeguato`, `stato_adeguatezza`, `deficit_confidenza`, `n_minimo_richiesto_per_k`
    e `avvisi_pianificatore`; con `richiedi_adeguatezza=True` una configurazione che non raggiunge
    `confidenza` alla `k_max` scelta solleva ValueError di dominio (blocco F0 senza fallback).
    """
    if not isinstance(richiedi_adeguatezza, bool):
        raise ValueError(f"richiedi_adeguatezza deve essere un booleano (true/false); ricevuto: {richiedi_adeguatezza!r}")
    prof_key = profilo.strip().lower() if isinstance(profilo, str) else ""
    if prof_key not in PROFILI_CAMPIONARI and prof_key != "personalizzato":
        raise ValueError(
            f"Profilo '{profilo}' non riconosciuto. Profili ammessi: "
            f"{list(PROFILI_CAMPIONARI.keys()) + ['personalizzato']}"
        )

    a0, b0 = _valida_prior("prior", prior if prior is not None else PROFILI_CAMPIONARI.get(prof_key, PROFILI_CAMPIONARI["equilibrato"])["prior"])
    if p_max is not None and (isinstance(p_max, bool) or not isinstance(p_max, (int, float)) or not math.isfinite(float(p_max)) or p_max <= 0.0 or p_max > 1.0):
        raise ValueError(f"p_max deve essere in (0, 1]; ricevuto: {p_max!r}")
    if confidenza is not None and (isinstance(confidenza, bool) or not isinstance(confidenza, (int, float)) or not math.isfinite(float(confidenza)) or confidenza <= 0.0 or confidenza > 1.0):
        raise ValueError(f"confidenza deve essere in (0, 1]; ricevuto: {confidenza!r}")
    if k_max_override is not None:
        k_max_override = _valida_intero("k_max_override", k_max_override, minimo=0)
    if n_custom is not None:
        n_custom = _valida_intero("n_custom", n_custom, minimo=1)
    if loss_ratio_fn_fp is not None:
        _valida_finito("loss_ratio_fn_fp", loss_ratio_fn_fp)

    base = PROFILI_CAMPIONARI.get(prof_key, PROFILI_CAMPIONARI["equilibrato"])
    eff_p_max = float(p_max if p_max is not None else base["p_max"])
    eff_conf = float(confidenza if confidenza is not None else base["confidenza"])
    if eff_conf >= 1.0 and eff_p_max < 1.0:
        raise ValueError(
            f"confidenza={eff_conf!r} non raggiungibile per alcun N finito con p_max={eff_p_max!r} < 1.0 "
            "nel modello continuo Beta-Binomiale (specificare confidenza in (0, 1))."
        )
    eff_prior = (a0, b0)
    eff_loss_ratio = (
        loss_ratio_fn_fp if loss_ratio_fn_fp is not None else base["loss_ratio_fn_fp"]
    )

    # Determinazione di N e k_max
    if prof_key != "personalizzato" and n_custom is None:
        n_target = base["N"]
        # Trova il massimo k tale che Pr(p <= p_max | k, N) >= eff_conf
        k_ammissibile_a_N = -1
        for k_cand in range(n_target + 1):
            post_prob = beta_cdf(eff_p_max, a0 + k_cand, b0 + n_target - k_cand)
            if post_prob >= eff_conf:
                k_ammissibile_a_N = k_cand
            else:
                break
        k_best = k_max_override if k_max_override is not None else k_ammissibile_a_N
    else:
        # Profilo personalizzato: se n_custom è fornito usa n_custom, altrimenti cerca N minimo
        k_target = k_max_override if k_max_override is not None else 1
        if n_custom is not None:
            n_target = max(1, int(n_custom))
            k_best = k_target
            # Verifica anche il massimo k ammissibile a n_custom
            k_ammissibile_a_N = -1
            for k_cand in range(n_target + 1):
                if beta_cdf(eff_p_max, a0 + k_cand, b0 + n_target - k_cand) >= eff_conf:
                    k_ammissibile_a_N = k_cand
                else:
                    break
            # (rev. v0.5) NESSUN clamp silenzioso: se nemmeno k=0 raggiunge eff_conf, k_best
            # resta -1 ("regola inerte", stato REGOLA_INERTE_NESSUN_K_AMMISSIBILE) cosi' come
            # nel ramo profili standard; era max(0, k_auto) che mascherava l'inadeguatezza.
            if k_max_override is None:
                k_best = k_ammissibile_a_N
        else:
            # (rev. v0.5) N minimo ESATTO per garantire Pr(p <= p_max | k, N) >= conf: bisezione
            # monotona su interi (la CDF posteriore e' crescente in N) fino a n_max = 100_000.
            # Niente loop lineare troncato a 999: se la soluzione non esiste entro il limite,
            # errore di dominio esplicito (mai fallback silenzioso a N=2).
            n_trovato = _trova_n_minimo_per_confidenza(k_target, eff_p_max, eff_conf, a0, b0)
            if n_trovato is None:
                raise ValueError(
                    f"Profilo 'personalizzato' senza n_custom: nessuna taglia N <= 100000 raggiunge la "
                    f"confidenza {eff_conf} con k_max {k_target} errori ammessi, p_max {eff_p_max} e prior "
                    f"Beta({a0}, {b0}): configurazione irraggiungibile (fail-closed, invalidare il piano)"
                )
            n_target = n_trovato
            k_best = k_target
            # ME-05: calcola il vero massimo k ammissibile a n_target (puo` essere > k_target con prior informative)
            k_ammissibile_a_N = -1
            for k_cand in range(n_target + 1):
                if beta_cdf(eff_p_max, a0 + k_cand, b0 + n_target - k_cand) >= eff_conf:
                    k_ammissibile_a_N = k_cand
                else:
                    break

    # (C11 rev.) k_max_override deve restare <= N: altrimenti beta_post = b0 + N - k_max
    # diventa <= 0 e la cdf Beta potrebbe essere valutata fuori dominio. Errore di dominio
    # esplicito e leggibile, senza clamp silenziosi e senza crash tardivi.
    if k_max_override is not None and k_max_override > n_target:
        raise ValueError(
            f"k_max_override ({k_max_override}) supera il numero di unita' giudicate N={n_target} "
            f"(profilo '{prof_key}'): k_max deve essere in [0, N]; usare 'personalizzato' con "
            "n_custom >= k_max oppure aumentare la taglia campionaria"
        )

    # Calcolo distribuzione posteriore e Compatibility Intervals al limite k = max(0, k_best)
    k_eval = max(0, k_best)
    alpha_post = a0 + k_eval
    beta_post = b0 + n_target - k_eval
    post_conf_at_kmax = beta_cdf(eff_p_max, alpha_post, beta_post)

    # ---- Adeguatezza strutturata del piano (v0.5: chiusura del known_limit) ----
    # Confronto coerente con il loop di selezione di k (`post_prob >= eff_conf`), senza
    # tolleranza extra: beta_cdf e' deterministica e ricalcolata con gli stessi argomenti
    # del k selezionato, quindi l'uguaglianza comporta il passaggio del loop.
    regola_inerte = bool(k_ammissibile_a_N == -1)
    piano_adeguato = bool(k_best >= 0 and post_conf_at_kmax >= eff_conf)
    if piano_adeguato:
        stato_adeguatezza = "ADEGUATO"
    elif k_best < 0:
        stato_adeguatezza = "REGOLA_INERTE_NESSUN_K_AMMISSIBILE"
    else:
        stato_adeguatezza = "INADEGUATO_SOTTO_CONFIDENZA"
    deficit_confidenza = round(max(0.0, eff_conf - post_conf_at_kmax), 5)
    n_minimo_richiesto_per_k = _trova_n_minimo_per_confidenza(
        k_eval, eff_p_max, eff_conf, a0, b0
    )
    if piano_adeguato:
        avvisi_pianificatore = []
    else:
        dettaglio_n_minimo = (
            str(n_minimo_richiesto_per_k)
            if n_minimo_richiesto_per_k is not None
            else "irraggiungibile entro 100000 unita' (valutare p_max, prior o l'abolizione della regola)"
        )
        if stato_adeguatezza == "REGOLA_INERTE_NESSUN_K_AMMISSIBILE":
            avvisi_pianificatore = [
                f"Regola inerte (N={n_target}, p_max={eff_p_max}, eff_conf={eff_conf}, prior Beta({a0}, {b0})): "
                "neanche k=0 errori raggiunge la confidenza richiesta al limite k ammissibile; "
                "il piano NON puo' essere usato con accettazione automatica a k best (-1).",
                f"post_prob_p_le_pmax_at_kmax = {post_conf_at_kmax:.5f} < eff_conf = {eff_conf}; "
                f"k_max_ammissibile_a_N = {k_ammissibile_a_N}; n_minimo_richiesto_per_k = {dettaglio_n_minimo}.",
            ]
        else:
            avvisi_pianificatore = [
                f"Configurazione sotto-confidenza: post_prob_p_le_pmax_at_kmax = {post_conf_at_kmax:.5f} "
                f"< eff_conf = {eff_conf} (deficit_confidenza = {deficit_confidenza}).",
                f"k_max_ammissibile_a_N = {k_ammissibile_a_N} "
                f"(k_max selezionato = {k_best} su N = {n_target}, p_max = {eff_p_max}, prior Beta({a0}, {b0})); "
                f"n_minimo_richiesto_per_k = {dettaglio_n_minimo}.",
            ]
    if richiedi_adeguatezza and not piano_adeguato:
        raise ValueError(
            f"Configurazione pianificatore sottodimensionata ({stato_adeguatezza}): "
            f"post_prob_p_le_pmax_at_kmax = {post_conf_at_kmax:.5f} < eff_conf = {eff_conf} su N={n_target} "
            f"con k_max {k_best} (k_max_ammissibile_a_N = {k_ammissibile_a_N}, "
            f"n_minimo_richiesto_per_k = {n_minimo_richiesto_per_k}): piano bloccato in F0, ricalcolare "
            "la taglia o rilassare la regola -> richiedi_adeguatezza=True e piano_adeguato=False"
        )

    ci_error_p = compatibility_intervals_beta(alpha_post, beta_post)
    ci_fidelity_theta = compatibility_intervals_beta(beta_post, alpha_post)

    # Analisi della funzione di perdita di McElreath per k = 0 .. min(5, n_target)
    loss_table = []
    for k_step in range(min(6, n_target + 1)):
        l_row = mcelreath_asymmetric_loss(
            k_errors=k_step,
            n_trials=n_target,
            p_max=eff_p_max,
            prior=(a0, b0),
            c_fn=eff_loss_ratio,
            c_fp=1.0,
        )
        l_row["soddisfa_confidenza"] = bool(l_row["prob_p_le_pmax"] >= eff_conf)
        loss_table.append(l_row)

    # Curve OC (Operating Characteristic) esatte
    oc_curves = {}
    for p_true, label in (
        (0.01, "p_true_1pct_eccellente"),
        (0.02, "p_true_2pct_buono"),
        (0.05, "p_true_5pct_soglia"),
        (0.10, "p_true_10pct_inaccettabile"),
    ):
        if k_best < 0:
            prob_accept = 0.0
        else:
            prob_accept = sum(binom_pmf(k, n_target, p_true) for k in range(k_best + 1))
        oc_curves[label] = {
            "p_true_error": p_true,
            "theta_true_fidelity": round(1.0 - p_true, 4),
            "prob_accept": round(prob_accept, 4),
            "prob_reject": round(1.0 - prob_accept, 4),
        }

    return {
        "profilo": prof_key,
        "descrizione": (
            base["descrizione"]
            if prof_key in PROFILI_CAMPIONARI and n_custom is None
            else f"Profilo personalizzato (N={n_target}, conf={eff_conf:.0%}, p_max={eff_p_max:.1%})"
        ),
        "N_unita_giudicate": n_target,
        "p_max_errore": eff_p_max,
        "theta_min_fedelta": round(1.0 - eff_p_max, 4),
        "confidenza_richiesta": eff_conf,
        "prior_beta": [a0, b0],
        "k_max_errori_tollerati": k_best,
        "post_prob_p_le_pmax_at_kmax": round(post_conf_at_kmax, 5),
        "k_max_ammissibile_a_N": k_ammissibile_a_N,
        "regola_inerte": regola_inerte,
        "piano_adeguato": piano_adeguato,
        "stato_adeguatezza": stato_adeguatezza,
        "deficit_confidenza": deficit_confidenza,
        "n_minimo_richiesto_per_k": n_minimo_richiesto_per_k,
        "avvisi_pianificatore": avvisi_pianificatore,
        "compatibility_intervals_errore_p_at_kmax": ci_error_p,
        "compatibility_intervals_fedelta_theta_at_kmax": ci_fidelity_theta,
        "loss_analysis_mcelreath": loss_table,
        "oc_curves": oc_curves,
    }


# ============================================================================
# 2. CAP. 6: COLLIDER BIAS DI SELEZIONE LETTERARIA (T -> S <- N) & VAGLIO EPISTEMICO
# ============================================================================

def _norm_ppf_approx(p: float) -> float:
    """Approssimazione razionale di Moro/Beasley-Springer per il quantile normale standard."""
    if p <= 0.0:
        return -6.0
    if p >= 1.0:
        return 6.0
    # Usa bisezione su math.erf per precisione macchina (stdlib pura)
    lo, hi = -8.0, 8.0
    for _ in range(80):
        mid = 0.5 * (lo + hi)
        cdf = 0.5 * (1.0 + math.erf(mid / math.sqrt(2.0)))
        if cdf < p:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def _pearson_r(xs: List[float], ys: List[float]) -> float:
    """Coefficiente di correlazione di Pearson."""
    n = len(xs)
    if n < 2:
        return 0.0
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    denx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    deny = math.sqrt(sum((y - my) ** 2 for y in ys))
    if denx == 0.0 or deny == 0.0:
        return 0.0
    return num / (denx * deny)


def simula_collider_bias_mcelreath(
    n_studi: int = 200,
    prop_selezionati: float = 0.10,
    seed: int = 157,
) -> Dict[str, Any]:
    """
    McElreath Cap. 6 (§6.1 pp. 161–162, R code 6.1 & §6.3 Collider Bias):
    Simula una popolazione di `n_studi` studi scientifici con:
      - Newsworthiness (clamore / citabilità / novità apparente): N ~ Normal(0, 1)
      - Trustworthiness (solidità metodologica / assenza di bias): T ~ Normal(0, 1)
    Nella popolazione generale N e T sono indipendenti (r_popolazione ~ 0).
    Il processo di pubblicazione/indicizzazione/ranking seleziona il top `prop_selezionati`
    (es. 10%) per punteggio combinato S_score = N + T (DAG: T -> S <- N).
    Condizionare sul collider S = 1 apre il percorso non causale T <-> N e induce
    una forte correlazione negativa spuria r(N, T | S=1) ~ -0.77 tra gli studi pubblicati.
    """
    rng = random.Random(seed)
    nw = [rng.gauss(0.0, 1.0) for _ in range(n_studi)]
    tw = [rng.gauss(0.0, 1.0) for _ in range(n_studi)]
    scores = [n_val + t_val for n_val, t_val in zip(nw, tw)]

    sorted_scores = sorted(scores)
    idx_q = max(0, min(n_studi - 1, int(round((1.0 - prop_selezionati) * n_studi))))
    soglia_s = sorted_scores[idx_q]

    sel_nw = [n_val for n_val, sc in zip(nw, scores) if sc >= soglia_s]
    sel_tw = [t_val for t_val, sc in zip(tw, scores) if sc >= soglia_s]

    r_pop = _pearson_r(nw, tw)
    r_sel = _pearson_r(sel_nw, sel_tw)

    # Pendenza OLS di T su N dentro S=1: E[T | N, S=1] = alpha + beta_TN * N
    mx = sum(sel_nw) / len(sel_nw)
    my = sum(sel_tw) / len(sel_tw)
    var_x = sum((x - mx) ** 2 for x in sel_nw) / len(sel_nw)
    cov_xy = sum((x - mx) * (y - my) for x, y in zip(sel_nw, sel_tw)) / len(sel_nw)
    slope_t_on_n_given_s1 = cov_xy / var_x if var_x > 0 else 0.0
    intercept_t_on_n_given_s1 = my - slope_t_on_n_given_s1 * mx

    return {
        "riferimento_mcelreath": "Cap. 6, §6.1 R code 6.1 pp. 161-162 & §6.3 Collider Bias (T -> S <- N)",
        "n_studi_popolazione": n_studi,
        "prop_selezionati_S1": prop_selezionati,
        "n_selezionati_S1": len(sel_nw),
        "soglia_selezione_score": round(soglia_s, 4),
        "r_popolazione_incondizionata": round(r_pop, 4),
        "r_selezionati_S1_collider": round(r_sel, 4),
        "ols_T_su_N_dato_S1": {
            "intercetta": round(intercept_t_on_n_given_s1, 4),
            "pendenza_negativa": round(slope_t_on_n_given_s1, 4),
        },
        "interpretazione_causale": (
            "Condizionare sulla sola selezione/ranking (S=1, es. top 20 paper estratti da Consensus) "
            f"induce una correlazione negativa r = {r_sel:.3f} tra Newsworthiness (N) e Trustworthiness (T): "
            "gli studi con claim più clamorosi (N elevato) che superano la soglia S=1 hanno in media "
            "una qualità metodologica T inferiore se non si condiziona esplicitamente su T (RoB 2 / ROBINS-I / GRADE)."
        ),
    }


def vaglio_epistemico_mcelreath(
    study_design: str = "simulation",
    rob2_or_robins_risk: str = "moderate",
    grade_certainty: str = "moderate",
    newsworthiness_z: float = 1.0,
    has_verified_full_text: bool = True,
    sample_size_studies_or_records: int = 10,
) -> Dict[str, Any]:
    """
    Calcola il Punteggio di Vaglio Epistemico Diotima (`vaglio_epistemico_mcelreath`)
    applicando la correzione di McElreath Cap. 6 al DAG di selezione letteraria T -> S <- N.

    Invece di pesare gli studi selezionati (S=1) solo in base alla loro rilevanza lessicale
    o al clamore del risultato (N, es. "riduzione di 10 volte del carico di screening"),
    Diotima:
      1. Stima l'indice osservabile di Trustworthiness metodologica T_obs in [-2.5, +2.5]
         ancorato agli standard S01-S06:
         - Disegno dello studio (SR/MA S01/S02, RCT S03, Cohort/Observational S04, Simulation, Opinion)
         - Rischio di bias (RoB 2 S03 / ROBINS-I S04: low, moderate/some_concerns, high/serious, critical)
         - Certezza GRADE (S05/S06: high, moderate, low, very_low)
         - Ispezione diretta del full text primario (has_verified_full_text)
      2. Calcola la distorsione da Collider Bias attesa se T non fosse misurato:
         E[T | N = n_z, S = 1] = 1.52 - 0.50 * n_z  (penalizzazione per claim sensazionalistici non verificati)
      3. Restituisce sia il peso euristico ingenuo (stile Consensus Meter, che tratta ogni paper
         selezionato S=1 con peso uniforme 1.0) sia il peso epistemico corretto di Diotima in [0, 1].
    """
    design_map = {
        "systematic_review_ma": 1.0,
        "rct": 0.9,
        "prospective_cohort": 0.5,
        "retrospective_evaluation": 0.2,
        "simulation": 0.0,
        "preclinical_animal": -0.3,
        "llm_exploratory": -0.6,
        "narrative_or_unknown": -1.0,
    }
    rob_map = {
        "low": 1.0,
        "moderate": 0.0,
        "some_concerns": 0.0,
        "high": -1.0,
        "serious": -1.2,
        "critical": -2.0,
        "unassessed_abstract_only": -1.1,
    }
    grade_map = {
        "high": 0.8,
        "moderate": 0.3,
        "low": -0.4,
        "very_low": -1.0,
    }

    if not isinstance(study_design, str) or not isinstance(rob2_or_robins_risk, str) or not isinstance(grade_certainty, str):
        raise ValueError(
            "study_design, rob2_or_robins_risk e grade_certainty devono essere stringhe di tassonomia; "
            f"ricevuti: {study_design!r}, {rob2_or_robins_risk!r}, {grade_certainty!r}"
        )
    newsworthiness_z_norm = _valida_finito("newsworthiness_z", newsworthiness_z)
    if sample_size_studies_or_records is None or isinstance(sample_size_studies_or_records, bool) or not isinstance(sample_size_studies_or_records, int) or sample_size_studies_or_records < 0:
        raise ValueError(f"sample_size_studies_or_records deve essere un numero intero >= 0; ricevuto: {sample_size_studies_or_records!r}")

    d_score = design_map.get(study_design.lower(), 0.0)
    r_score = rob_map.get(rob2_or_robins_risk.lower(), -0.5)
    g_score = grade_map.get(grade_certainty.lower(), 0.0)
    ft_bonus = 0.4 if has_verified_full_text else -0.9
    size_bonus = min(0.4, 0.1 * math.log10(max(1, sample_size_studies_or_records)))

    t_measured = d_score + r_score + g_score + ft_bonus + size_bonus

    # Correzione bayesiana del collider T -> S <- N quando lo studio è selezionato (S=1)
    # Se il full text non è verificato, T è parzialmente latente e risente della distorsione negativa da N
    collider_penalty = max(0.0, 0.35 * max(0.0, newsworthiness_z_norm - 0.5))
    if has_verified_full_text and rob2_or_robins_risk.lower() == "low":
        # D-separation: condizionare su T osservato e rigoroso blocca il percorso da N
        collider_penalty *= 0.15

    t_post_corrected = t_measured - collider_penalty
    # Trasformazione logistica in peso epistemico [0, 1]
    peso_diotima = 1.0 / (1.0 + math.exp(-t_post_corrected))
    peso_consensus_ingenuo = 1.0  # Consensus Meter assegna peso piatto 1/N a ogni paper incluso

    return {
        "study_design": study_design,
        "rob2_or_robins_risk": rob2_or_robins_risk,
        "grade_certainty": grade_certainty,
        "has_verified_full_text": has_verified_full_text,
        "newsworthiness_z": round(newsworthiness_z_norm, 3),
        "trustworthiness_T_measured": round(t_measured, 4),
        "collider_penalty_Cap6": round(collider_penalty, 4),
        "trustworthiness_T_post_corrected": round(t_post_corrected, 4),
        "peso_consensus_ingenuo": peso_consensus_ingenuo,
        "peso_epistemico_diotima": round(peso_diotima, 4),
        "rapporto_ridimensionamento": round(peso_diotima / peso_consensus_ingenuo, 4),
        "standard_applicati": ["S01", "S03", "S04", "S05", "S06", "McElreath_Cap6_Collider"],
        # Riconoscimento esplicito (non silenzioso): i token fuori tassonomia di RoB 2 / GRADE
        # e disegno producono flag False + avvertenza; il peso resta quello calcolabile
        # con i default precedenti, dichiarati come euristici.
        "riconoscimento_tassonomia": {
            "study_design": study_design.lower() in design_map,
            "rob2_or_robins_risk": rob2_or_robins_risk.lower() in rob_map,
            "grade_certainty": grade_certainty.lower() in grade_map,
        },
        "avvertenza_fuori_tassonomia": ", ".join(
            f"{nome} fuori tassonomia: '{valore}'"
            for nome, valore, riconoscito in (
                ("study_design", study_design, study_design.lower() in design_map),
                ("rob2_or_robins_risk", rob2_or_robins_risk, rob2_or_robins_risk.lower() in rob_map),
                ("grade_certainty", grade_certainty, grade_certainty.lower() in grade_map),
            )
            if not riconoscito
        ) or None,
    }


# ============================================================================
# 3. CAP. 12 & 13: BETA-BINOMIAL OVERDISPERSION & MULTILEVEL PARTIAL POOLING
# ============================================================================

def multilevel_partial_pooling_mcelreath(
    document_clusters: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    McElreath Cap. 12 (§12.1 Beta-Binomial Overdispersion, pp. 369–375) &
    Cap. 13 (§13.1–13.2 Multilevel Tadpoles / Partial Pooling, pp. 399–420):

    Modella le unità di verifica (`UNITA`) annidate nei documenti (`DOC_j`, j = 1..J).
    Ogni documento j ha n_j unità giudicate e k_j unità fedeli/supportate.
    Calcola:
      1. Stima No-Pooling:       p_no_pool[j] = k_j / n_j
      2. Stima Complete-Pooling: p_complete   = sum(k_j) / sum(n_j)
      3. Varianza tra documenti (tau^2), varianza binomiale intra-documento (sigma^2),
         correlazione intra-classe / sovradispersione rho_ICC (Cap. 12) e dimensione
         campionaria effettiva N_eff = sum(n_j / (1 + (n_j - 1) * rho_ICC)).
      4. Pesi di Partial Pooling di McElreath (Cap. 13, eq. 13.7–13.8):
           w_j = n_j / (n_j + sigma^2 / tau^2)
           p_partial[j] = p_complete + w_j * (p_no_pool[j] - p_complete)
         che regolarizzano i documenti con poche unità (n_j piccolo) verso la media
         globale del corpus, evitando sia l'amnesia del no-pooling sia l'omogeneizzazione
         forzata del complete-pooling.
    """
    # Validazione fail-closed di TUTTI i cluster: nessun filtro silenzioso
    # (un documento con n_j = 0 o con k_j > n_j e' un errore dei dati, non un outlier da ignorare).
    valid_docs: List[Dict[str, Any]] = []
    for indice, doc in enumerate(document_clusters):
        if not isinstance(doc, dict):
            raise ValueError(f"document_clusters[{indice}] deve essere un oggetto {{doc_id, k_j, n_j}}; ricevuto: {doc!r}")
        k_j = _valida_intero(f"document_clusters[{indice}].k_j", doc.get("k_j"), minimo=0)
        n_j = _valida_intero(f"document_clusters[{indice}].n_j", doc.get("n_j"), minimo=1)
        if k_j > n_j:
            raise ValueError(
                f"document_clusters[{indice}] ('{doc.get('doc_id')}'): k_j ({k_j}) non puo' superare n_j ({n_j})"
            )
        valid_docs.append(doc)

    if not valid_docs:
        raise ValueError("document_clusters vuoto: nessun documento da aggregare")

    j_count = len(valid_docs)
    n_tot = sum(int(d["n_j"]) for d in valid_docs)
    k_tot = sum(int(d["k_j"]) for d in valid_docs)
    p_complete = k_tot / n_tot if n_tot > 0 else 0.0

    # Stima ANOVA/momenti della varianza tra cluster (tau^2) e intra-cluster (sigma^2)
    sigma2_within = max(1e-4, p_complete * (1.0 - p_complete))
    n_bar = n_tot / j_count

    raw_props = [int(d["k_j"]) / int(d["n_j"]) for d in valid_docs]
    if j_count > 1:
        s2_between_raw = sum(
            int(d["n_j"]) * ((int(d["k_j"]) / int(d["n_j"])) - p_complete) ** 2
            for d in valid_docs
        ) / ((j_count - 1) * n_bar)
        # Sottrae il rumore di campionamento binomiale atteso sigma^2 / n_bar
        tau2_between = max(1e-4, s2_between_raw - (sigma2_within / max(1.0, n_bar)))
    else:
        tau2_between = 0.01

    rho_icc = tau2_between / (tau2_between + sigma2_within)
    rho_icc = max(0.0, min(0.99, rho_icc))

    ratio_sigma_tau = sigma2_within / tau2_between if tau2_between > 0 else 1e6

    stima_per_documento = []
    n_eff_tot = 0.0
    weighted_partial_sum = 0.0

    for d in valid_docs:
        doc_id = str(d.get("doc_id") or d.get("id") or "DOC")
        n_j = int(d["n_j"])
        k_j = int(d["k_j"])
        p_no = k_j / n_j
        w_j = n_j / (n_j + ratio_sigma_tau)
        p_part = p_complete + w_j * (p_no - p_complete)
        shrinkage_amount = abs(p_no - p_part)
        design_eff_j = 1.0 + (n_j - 1.0) * rho_icc
        n_eff_j = n_j / design_eff_j
        n_eff_tot += n_eff_j
        weighted_partial_sum += n_eff_j * p_part

        stima_per_documento.append(
            {
                "doc_id": doc_id,
                "k_j": k_j,
                "n_j": n_j,
                "p_no_pooling": round(p_no, 4),
                "p_complete_pooling": round(p_complete, 4),
                "peso_partial_pooling_w_j": round(w_j, 4),
                "p_partial_pooling": round(p_part, 4),
                "shrinkage_verso_media": round(shrinkage_amount, 4),
                "n_eff_j": round(n_eff_j, 3),
            }
        )

    p_multilevel_grand = (
        weighted_partial_sum / n_eff_tot if n_eff_tot > 0 else p_complete
    )
    # Parametro di concentrazione Beta-Binomiale theta_BB = (1 - rho_ICC) / rho_ICC (McElreath Cap. 12)
    theta_bb = (1.0 - rho_icc) / rho_icc if rho_icc > 1e-5 else 10000.0

    # Compatibility Intervals Beta-Binomiali corretti per la taglia campionaria effettiva N_eff
    k_eff = p_multilevel_grand * n_eff_tot
    ci_multilevel = compatibility_intervals_beta(1.0 + k_eff, 1.0 + (n_eff_tot - k_eff))

    return {
        "riferimento_mcelreath": "Cap. 12 (§12.1 Beta-Binomial) & Cap. 13 (§13.1-13.2 Partial Pooling, pp. 399-420)",
        "J_documenti": j_count,
        "N_totale_unita": n_tot,
        "K_totale_successi": k_tot,
        "N_eff_corretta_clustering": round(n_eff_tot, 3),
        "p_complete_pooling": round(p_complete, 5),
        "p_media_no_pooling": round(sum(raw_props) / len(raw_props), 5),
        "p_multilevel_partial_pooling": round(p_multilevel_grand, 5),
        "sigma2_within": round(sigma2_within, 5),
        "tau2_between": round(tau2_between, 5),
        "rho_ICC_intra_documento": round(rho_icc, 4),
        "theta_concentrazione_beta_binomiale": round(min(10000.0, theta_bb), 3),
        "compatibility_intervals_multilevel": ci_multilevel,
        "documenti": stima_per_documento,
    }


# ============================================================================
# 4. CAP. 15: MISSING DATA DAG (S -> H -> H* <- D), BOUNDS DI MANSKI & L0..L4
# ============================================================================

def classifica_missingness_mcelreath(
    n_total_units: int,
    n_vnp_missing: int,
    k_supported_observed: int,
    missing_depends_on_study_covariates_S: bool = False,
    missing_depends_on_latent_quality_H: bool = False,
     stratum_estimates: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    McElreath Cap. 15 (§15.2 Missing Data / Homework Dog DAGs, Fig. 15.4 p. 500):
    Analizza causalmente le unità con `verifica non possibile` (o `has_full_text: false`,
    indicatore di missingness D = 1) secondo i tre regimi del DAG S -> H -> H* <- D:

      - Caso (a) MCAR (`D_indipendente_MCAR`): D è indipendente sia dalle covariate dello
        studio S sia dallo stato vero di supporto/qualità H. L'esclusione delle unità
        mancanti riduce solo l'efficienza ma non introduce bias se pi_VNP <= 10%.
      - Caso (b) MAR condizionato a S (`S_to_D_MAR`): lo stato di accesso D dipende da
        caratteristiche osservate dello studio S (es. anno, editore chiuso, dominio clinico).
        Condizionando su S (post-stratificazione / backdoor adjustment su S) si recupera
        l'identificabilità causale di H.
      - Caso (c) MNAR dipendente da H (`H_to_D_MNAR`): la mancata disponibilità del testo
        primario o dei dati dipende dalla qualità/forza latente H dello studio (es. studi
        deboli o solo-abstract con claim gonfiati). Non è eliminabile per semplice
        condizionamento e richiede obbligatoriamente i Bounds di Manski/McElreath.

    Calcola inoltre i Bounds non parametrici di Manski/McElreath sul tasso reale nel corpus:
      theta_min_Manski = (1 - pi_VNP) * theta_obs + pi_VNP * 0
      theta_max_Manski = (1 - pi_VNP) * theta_obs + pi_VNP * 1
    """
    n_tot = _valida_intero("n_total_units", n_total_units, minimo=0)
    n_vnp = _valida_intero("n_vnp_missing", n_vnp_missing, minimo=0)
    k_obs = _valida_intero("k_supported_observed", k_supported_observed, minimo=0)
    if n_vnp > n_tot:
        raise ValueError(f"n_vnp_missing ({n_vnp}) non puo' superare n_total_units ({n_tot})")
    n_obs = n_tot - n_vnp
    if k_obs > n_obs:
        raise ValueError(f"k_supported_observed ({k_obs}) non puo' superare le unita' osservate ({n_obs})")

    if n_tot == 0:
        # Denominatore zero: nessun dato giudicato. Ritornare "non valutabile"
        # (theta/bounds a None) invece di arrotondare a 0.0 o a "100%".
        return {
            "riferimento_mcelreath": "Cap. 15, §15.2 Missing Data DAG (S -> H -> H* <- D, Fig. 15.4 p. 500)",
            "dag_regime": "NON_VALUTABILE (n_total_units = 0: nessuna unita' osservata)",
            "azione_causale_mcelreath": (
                "Denominatore zero: impossibile stimare theta o applicare i bounds di Manski. "
                "Servono unita' con esito o la stima va dichiara non valutabile."
            ),
            "n_totale": 0,
            "n_osservate_giudicate": 0,
            "n_mancanti_VNP": 0,
            "pi_VNP_missing_rate": None,
            "quota_giudicate": None,
            "theta_osservato_complete_case": None,
            "denominatore_osservabili_zero": True,
            "manski_bounds": {
                "theta_min_worst_case": None,
                "theta_max_best_case": None,
                "ampiezza_indeterminazione": None,
            },
            "theta_MAR_post_stratificato_su_S": None,
            "theta_MNAR_imputazione_conservativa": None,
            "ci_complete_case_ingenua": {},
            "ci_worst_case_manski": {},
            "stato_soglia_diotima": "DENOMINATORE_ZERO (nessuna unita' osservata: stima non valutabile, theta/bounds None)",
        }

    pi_vnp = n_vnp / n_tot
    quota_giudicate = n_obs / n_tot
    if n_obs == 0:
        # Nessuna unita' con esito (tutte missing): denominatore complete-case zero.
        return {
            "riferimento_mcelreath": "Cap. 15, §15.2 Missing Data DAG (S -> H -> H* <- D, Fig. 15.4 p. 500)",
            "dag_regime": "NON_VALUTABILE (n_osservate_giudicate = 0: tutte le unita' sono missing)",
            "azione_causale_mcelreath": (
                "Denominatore complete-case zero: theta osservato non stimabile; valutare i dati a monte "
                "o dichiarare l'analisi non valutabile (niente fix matematico che maschera il vuoto)."
            ),
            "n_totale": n_tot,
            "n_osservate_giudicate": 0,
            "n_mancanti_VNP": n_vnp,
            "pi_VNP_missing_rate": round(pi_vnp, 4),
            "quota_giudicate": 0.0,
            "theta_osservato_complete_case": None,
            "denominatore_osservabili_zero": True,
            "manski_bounds": {
                "theta_min_worst_case": None,
                "theta_max_best_case": None,
                "ampiezza_indeterminazione": None,
            },
            "theta_MAR_post_stratificato_su_S": None,
            "theta_MNAR_imputazione_conservativa": None,
            "ci_complete_case_ingenua": {},
            "ci_worst_case_manski": {},
            "stato_soglia_diotima": "DENOMINATORE_ZERO (nessuna unita' osservata: stima non valutabile, theta/bounds None)",
        }
    theta_obs = k_obs / n_obs

    if missing_depends_on_latent_quality_H:
        dag_regime = "Caso (c) MNAR (H -> D: Missing Not At Random, Fig. 15.4c p. 500)"
        azione_mcelreath = (
            "Impossibile chiudere il backdoor tramite covariate osservate: usare obbligatoriamente "
            "i Bounds di Manski/McElreath [theta_min, theta_max] o imputazione bayesiana esplicita "
            "con prior pessimista Beta(1, 4) sulle unità mancanti."
        )
    elif missing_depends_on_study_covariates_S:
        dag_regime = "Caso (b) MAR condizionato a S (S -> D e S -> H, Fig. 15.4b p. 500)"
        azione_mcelreath = (
            "Condizionare sulle covariate osservate S (anno, editore, licenza OA, dominio) "
            "tramite post-stratificazione per bloccare il percorso non causale D <- S -> H."
        )
    else:
        dag_regime = "Caso (a) MCAR (D indipendente da S e H, Fig. 15.4a p. 500)"
        azione_mcelreath = (
            "Complete-case analysis non distorta se pi_VNP <= 10%; riportare comunque "
            "l'ampiezza dei Bounds di Manski per trasparenza."
        )

    # Bounds esatti di Manski/McElreath sul corpus totale N_tot
    theta_manski_min = (k_obs + 0) / n_tot
    theta_manski_max = (k_obs + n_vnp) / n_tot
    manski_width = theta_manski_max - theta_manski_min

    # Post-stratificazione su S se sono forniti gli strati
    theta_mar_stratified = None
    if stratum_estimates:
        tot_w = sum(float(st.get("weight", 0.0)) for st in stratum_estimates)
        if tot_w > 0:
            theta_mar_stratified = sum(
                float(st["weight"]) * float(st["theta_stratum"]) for st in stratum_estimates
            ) / tot_w

    # Stima bayesiana con imputazione conservativa per il caso MNAR (prior Beta(1, 3) sui mancanti)
    expected_k_mnar_conservative = k_obs + 0.25 * n_vnp
    ci_manski_lower_bound = compatibility_intervals_beta(
        1.0 + k_obs, 1.0 + (n_tot - k_obs)
    )
    ci_observed_only = compatibility_intervals_beta(
        1.0 + k_obs, 1.0 + (n_obs - k_obs)
    )

    if pi_vnp > 0.20:
        stato_soglia_diotima = "BLOCCO_STRUTTURALE_RT02 (pi_VNP > 20%, quota_giudicate < 80%)"
    elif pi_vnp > 0.10:
        stato_soglia_diotima = "ALLERTA_SENSIBILITA_MANSKI (10% < pi_VNP <= 20%)"
    else:
        stato_soglia_diotima = "CONFORME_SOGLIA_10PCT (pi_VNP <= 10%)"

    return {
        "riferimento_mcelreath": "Cap. 15, §15.2 Missing Data DAG (S -> H -> H* <- D, Fig. 15.4 p. 500)",
        "dag_regime": dag_regime,
        "azione_causale_mcelreath": azione_mcelreath,
        "n_totale": n_tot,
        "n_osservate_giudicate": n_obs,
        "n_mancanti_VNP": n_vnp,
        "pi_VNP_missing_rate": round(pi_vnp, 4),
        "quota_giudicate": round(quota_giudicate, 4),
        "theta_osservato_complete_case": round(theta_obs, 4),
        "manski_bounds": {
            "theta_min_worst_case": round(theta_manski_min, 4),
            "theta_max_best_case": round(theta_manski_max, 4),
            "ampiezza_indeterminazione": round(manski_width, 4),
        },
        "theta_MAR_post_stratificato_su_S": (
            round(theta_mar_stratified, 4) if theta_mar_stratified is not None else None
        ),
        "theta_MNAR_imputazione_conservativa": round(expected_k_mnar_conservative / n_tot, 4),
        "ci_complete_case_ingenua": ci_observed_only["percentile_intervals_PI"],
        "ci_worst_case_manski": ci_manski_lower_bound["percentile_intervals_PI"],
        "stato_soglia_diotima": stato_soglia_diotima,
    }


def marginalizza_errore_categoriale_l4(
    voti_lettori: List[str],
    accuratezza_lettori: Optional[List[float]] = None,
    prior_stati: Optional[Dict[str, float]] = None,
    sorgente_voti: Optional[str] = None,
    numero_lettori_osservati: Optional[int] = None,
    indipendenza_lettori_sostenuta: Optional[bool] = None,
) -> Dict[str, Any]:
    """
    McElreath Cap. 15 (§15.3 Categorical Errors and Discrete Absences, pp. 515–521):
    Marginalizza sullo stato latente vero C in STATI_DIOTIMA_5 dato un vettore di
    classificazioni osservate y_1, ..., y_R (da più agenti o lettori umani) soggette a
    matrice di confusione / tasso di errore categoriale:
      P(y_r = c' | C = c) = acc_r              se c' == c
      P(y_r = c' | C = c) = (1 - acc_r) / 4    se c' != c
    Calcola la distribuzione posteriore P(C = c | y_1..y_R), l'entropia di Shannon
    normalizzata H_norm in [0, 1] e attiva il flag `richiede_adjudicazione_umana` se
    H_norm > 0.25, se c'è disaccordo tra i lettori o se c'è UNA SOLA osservazione
    (indipendenza non provabile richiede il passaggio umano, Cap. 15 §15.3).
    """
    k_states = len(STATI_DIOTIMA_5)
    if isinstance(voti_lettori, bool) or not isinstance(voti_lettori, (list, tuple)):
        raise ValueError(f"voti_lettori deve essere una lista di stati; ricevuto: {voti_lettori!r}")
    for _i, _v in enumerate(voti_lettori):
        if _v not in STATI_DIOTIMA_5:
            raise ValueError(
                f"voti_lettori[{_i}]='{_v}' fuori dalla tassonomia {list(STATI_DIOTIMA_5)}: errori "
                "categoriali fuori insieme non marginalizzabili (fail-closed)"
            )
    if numero_lettori_osservati is None:
        numero_lettori_osservati = len(voti_lettori)
    if sorgente_voti is None:
        sorgente_voti = "lettori_registrati_dal_chiamante"

    if not prior_stati:
        prior = {s: 1.0 / k_states for s in STATI_DIOTIMA_5}
    else:
        tot_p = sum(prior_stati.values()) or 1.0
        prior = {s: prior_stati.get(s, 0.0) / tot_p for s in STATI_DIOTIMA_5}

    if not voti_lettori:
        return {
            "stato_map": "verifica non possibile",
            "prob_map": 0.20,
            "entropia_normalizzata": 1.0,
            "richiede_adjudicazione_umana": True,
            "posterior_stati": prior,
            "sorgente_voti": "nessun_lettore",
            "numero_lettori_osservati": 0,
            "indipendenza_lettori_sostenuta": False,
        }

    accs = accuratezza_lettori or [0.90 for _ in voti_lettori]
    unnorm: Dict[str, float] = {}
    for c_true in STATI_DIOTIMA_5:
        lk = prior[c_true]
        for r_idx, voto in enumerate(voti_lettori):
            acc = max(0.50, min(0.999, accs[r_idx] if r_idx < len(accs) else 0.90))
            if voto == c_true:
                lk *= acc
            else:
                lk *= (1.0 - acc) / (k_states - 1)
        unnorm[c_true] = lk

    z = sum(unnorm.values()) or 1.0
    post = {c: unnorm[c] / z for c in STATI_DIOTIMA_5}

    # Entropia di Shannon normalizzata su log2(5)
    h_shannon = -sum(p * math.log2(p) for p in post.values() if p > 1e-12)
    h_norm = h_shannon / math.log2(k_states)

    stato_map = max(STATI_DIOTIMA_5, key=lambda c: post[c])
    disaccordo = len(set(voti_lettori)) > 1
    read_unico = numero_lettori_osservati <= 1
    richiede_umano = bool(h_norm > 0.25 or disaccordo or read_unico)

    return {
        "riferimento_mcelreath": "Cap. 15, §15.3 Categorical Errors (marginalizzazione su stato latente discreto, pp. 515-521)",
        "voti_osservati": list(voti_lettori),
        "sorgente_voti": sorgente_voti,
        "numero_lettori_osservati": int(numero_lettori_osservati),
        "indipendenza_lettori_sostenuta": bool(indipendenza_lettori_sostenuta) if indipendenza_lettori_sostenuta is not None else None,
        "stato_posteriore_MAP": stato_map,
        "probabilita_MAP": round(post[stato_map], 4),
        "entropia_shannon_normalizzata": round(h_norm, 4),
        "disaccordo_tra_lettori": disaccordo,
        "richiede_adjudicazione_umana": richiede_umano,
        "posterior_distribution": {k: round(v, 5) for k, v in post.items()},
    }


def verifica_integrita_primario_sha256(
    file_path: str | pathlib.Path,
    expected_sha256: str,
    base_dir: Optional[str | pathlib.Path] = None,
) -> Dict[str, Any]:
    """
    Verifica crittografica REALE del primario su disco (Gate L0, S17-S19 & RT-07 v0.5).

    Calcola lo SHA-256 del file indicato (lettura a chunk da 65536 byte, solo stdlib)
    e lo confronta con l'hash atteso dichiarato nel meta-manifest. Path traversal
    bloccato quando `base_dir` e' fornito e il target risolve fuori da esso
    (`ValueError` di dominio: il chiamante serve wipe, mai exception Fourier del gate).
    Ritorni strutturati esenti da path assoluti: NESSUN campo contiene il percorso
    (solo esiti, hash e bytes), in modo che gli artefatti generati restino portabili (O1).
    """
    # NB: import lazy di pathlib nel rispetto del solo stdlib dell'header del modulo.
    import pathlib as _pathlib

    if isinstance(file_path, str):
        file_path_norm = file_path
    elif isinstance(file_path, _pathlib.Path):
        file_path_norm = str(file_path)
    else:
        raise ValueError(f"file_path deve essere una stringa o un Path; ricevuto: {type(file_path).__name__}")
    file_path_norm = file_path_norm.strip()
    if not file_path_norm:
        raise ValueError("file_path non puo' essere vuoto o composto da soli spazi bianchi")

    root: Optional[_pathlib.Path] = None
    if base_dir is not None:
        if isinstance(base_dir, bool) or not isinstance(base_dir, (str, _pathlib.Path)):
            raise ValueError(f"base_dir deve essere str o Path; ricevuto: {type(base_dir).__name__}")
        base_dir_norm = str(base_dir).strip()
        if not base_dir_norm:
            raise ValueError(
                "base_dir non puo' essere vuoto o composto da soli spazi bianchi (confinamento RT-07 obbligatorio)"
            )
        root = _pathlib.Path(base_dir_norm).expanduser().resolve()
        candidate = _pathlib.Path(file_path_norm)
        if candidate.is_absolute():
            target = candidate.resolve()
        else:
            target = (root / candidate).resolve()
        if not target.is_relative_to(root):
            raise ValueError(
                "Path traversal bloccato: il percorso del primario esce da base_dir "
                "(il target risolve fuori dalla radice consentita dal gate RT-07)"
            )
    else:
        target = _pathlib.Path(file_path_norm).expanduser().resolve()

    # Nome/Nomi path risoluti MAI serializzati: l'esito riporta solo hash e diagnostica (O1; AL-02).
    sha_atteso_strip = expected_sha256.strip() if isinstance(expected_sha256, str) else ""
    if not isinstance(expected_sha256, str) or not (
        len(sha_atteso_strip) == 64
        and all(c in "0123456789abcdefABCDEF" for c in sha_atteso_strip)
    ):
        return {
            "ok": False,
            "esito_verifica": "FORMATO_SHA256_ATTESO_INVALIDO",
            "errore_E8": False,
            "file_acquisito": target.is_file(),
            "sha256_atteso": "<sha256_atteso_non_valido>",
            "sha256_calcolato": None,
            "bytes_file": None,
        }
    expected_sha256 = sha_atteso_strip
    atteso_norm = expected_sha256.lower()
    sha_atteso_out = atteso_norm

    if not target.exists():
        # RT-VNP: la mancata acquisizione del primario NON e' un errore E8:
        # e' una condizione di ausibilità dichiarata.
        return {
            "ok": False,
            "esito_verifica": "FILE_PRIMARIO_NON_ACQUISITO",
            "errore_E8": False,
            "file_acquisito": False,
            "sha256_atteso": atteso_norm,
            "sha256_calcolato": None,
            "bytes_file": None,
        }

    size_or_none: Optional[int] = None
    try:
        if not target.is_file():
            raise OSError(f"target non file: {target.name}")
        size_or_none = target.stat().st_size
        if size_or_none == 0:
            raise OSError("file vuoto (0 byte)")
        h = hashlib.sha256()
        total_bytes = 0
        with open(target, "rb") as fh:
            while True:
                chunk = fh.read(65536)
                if not chunk:
                    break
                h.update(chunk)
                total_bytes += len(chunk)
        sha256_calc = h.hexdigest()
    except OSError:
        return {
            "ok": False,
            "esito_verifica": "FILE_PRIMARIO_ILLEGGIBILE_O_VUOTO_E8",
            "errore_E8": True,
            "file_acquisito": False,
            "sha256_atteso": atteso_norm,
            "sha256_calcolato": None,
            "bytes_file": size_or_none,
        }

    if sha256_calc == atteso_norm:
        return {
            "ok": True,
            "esito_verifica": "SHA256_VERIFICATO_COINCIDENTE",
            "errore_E8": False,
            "file_acquisito": True,
            "sha256_atteso": atteso_norm,
            "sha256_calcolato": sha256_calc,
            "bytes_file": total_bytes,
        }
    return {
        "ok": False,
        "esito_verifica": "SHA256_MISMATCH_RT07",
        "errore_E8": False,
        "file_acquisito": True,
        "sha256_atteso": atteso_norm,
        "sha256_calcolato": sha256_calc,
        "bytes_file": total_bytes,
    }


def progressive_reader_l0_l4(
    claim_id: str,
    claim_text: str,
    claim_type: str,
    doc_metadata: Dict[str, Any],
    span_evidence: Dict[str, Any],
    appraisal_l3: Optional[Dict[str, Any]] = None,
    reader_votes_l4: Optional[List[str]] = None,
    reader_provenance_l4: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Modello di Lettura Progressiva a 5 livelli (`L0 -> L1 -> L2 -> L3 -> L4`) radicato
    negli standard S01-S20 e in McElreath Cap. 6 e Cap. 15:
      - L0 (Metadata & Provenance Gate, S17-S19): verifica DOI/identità, retraction,
        stato di accesso ('full text', 'abstract', 'metadato', 'non disponibile') e hash SHA-256.
      - L1 (Abstract Triage & Claim-Type Gate, S10-S11): blocca l'uso del solo Abstract
        (`BLOCK_ABSTRACT_ONLY`) quando il claim è quantitativo (`quantitative`), metodologico
        (`methodological`) o inferenziale forte, impedendo la scorciatoia di Consensus.
      - L2 (Grobid Full-Text Span Verification, S12-S16, S20): verifica l'ancoraggio nel
        corpo del testo primario (`section`, `page`, `quote`), applica i 5 passi decisionali
        e individua gli errori bloccanti E1, E2, E7.
      - L3 (Critical Appraisal & Collider Correction, S01-S06): applica RoB 2 / ROBINS-I /
        GRADE e il correttore del Collider Bias di McElreath Cap. 6.
      - L4 (Multi-Agent Categorical Marginalization & Human Adjudication, S07-S09, Cap. 15 §15.3):
        marginalizza sull'errore categoriale dei lettori e attiva l'intervento umano se
        l'entropia posteriore supera la soglia o se sono emersi blocchi in L0-L3.
    """
    trace_levels: Dict[str, Any] = {}
    appr = appraisal_l3 or {}

    if not isinstance(doc_metadata, dict):
        raise ValueError(f"doc_metadata deve essere un dizionario; ricevuto: {type(doc_metadata).__name__}")
    if not isinstance(span_evidence, dict):
        raise ValueError(f"span_evidence deve essere un dizionario; ricevuto: {type(span_evidence).__name__}")

    # AL-06: validazione rigorosa dei flag booleani (nessuna coercizione truthy di stringhe come 'no' o 'false')
    for campo_bool_md in ("identita_ok", "is_retracted", "has_full_text", "errore_prep_E8"):
        if campo_bool_md in doc_metadata and not isinstance(doc_metadata[campo_bool_md], bool):
            raise ValueError(
                f"doc_metadata.{campo_bool_md} deve essere un booleano (true/false); ricevuto: {doc_metadata[campo_bool_md]!r}"
            )
    for campo_bool_sp in (
        "quote_verified_in_fulltext",
        "coordinates_verified",
        "contradicts_claim",
        "numeric_mismatch",
        "numeric_missing_unquantified",
        "vague_or_preliminary",
        "partial_scope",
    ):
        if campo_bool_sp in span_evidence and not isinstance(span_evidence[campo_bool_sp], bool):
            raise ValueError(
                f"span_evidence.{campo_bool_sp} deve essere un booleano (true/false); ricevuto: {span_evidence[campo_bool_sp]!r}"
            )

    # CR-01: enum chiusa per stato_accesso; 'metadato' e 'non disponibile' sono privi di testo verificabile
    stato_accesso_raw = doc_metadata.get("stato_accesso", "full text")
    if not isinstance(stato_accesso_raw, str):
        raise ValueError(
            f"doc_metadata.stato_accesso deve essere una stringa; ricevuto: {stato_accesso_raw!r}"
        )
    stato_accesso = stato_accesso_raw.strip().lower()
    stati_accesso_l0 = ("full text", "abstract", "metadato", "non disponibile")
    if stato_accesso not in stati_accesso_l0:
        raise ValueError(
            f"doc_metadata.stato_accesso='{stato_accesso_raw}' non riconosciuto. "
            f"Valori ammessi: {list(stati_accesso_l0)}"
        )
    if "hash_file" in doc_metadata and doc_metadata["hash_file"] is not None and not isinstance(doc_metadata["hash_file"], str):
        raise ValueError(
            f"doc_metadata.hash_file deve essere una stringa (Optional[str]); ricevuto: {type(doc_metadata['hash_file']).__name__}"
        )

    # --- L0: Metadata & Provenance Gate (S17-S19) ---
    identita_ok = doc_metadata.get("identita_ok", True)
    retracted = doc_metadata.get("is_retracted", False)
    has_full_text = stato_accesso == "full text" and doc_metadata.get("has_full_text", True)
    hash_file = (doc_metadata.get("hash_file") or "")
    errore_e8 = doc_metadata.get("errore_prep_E8", False)

    # (v0.5) Verifica crittografica REALE dell'esistenza/integrita' del primario su disco:
    # chiavi opzionali in doc_metadata: file_path (str), base_dir (str), verifica_hash_reale (bool).
    file_path_md = doc_metadata.get("file_path")
    base_dir_md = doc_metadata.get("base_dir")
    verifica_hash_esplicito = "verifica_hash_reale" in doc_metadata
    verifica_hash_md = doc_metadata.get("verifica_hash_reale", False)
    if file_path_md is not None and not isinstance(file_path_md, str):
        raise ValueError(
            f"doc_metadata.file_path deve essere una stringa (Optional[str]); ricevuto: {type(file_path_md).__name__}"
        )
    if base_dir_md is not None and not isinstance(base_dir_md, str):
        raise ValueError(
            f"doc_metadata.base_dir deve essere una stringa (Optional[str]); ricevuto: {type(base_dir_md).__name__}"
        )
    if not isinstance(verifica_hash_md, bool):
        raise ValueError(
            f"doc_metadata.verifica_hash_reale deve essere un booleano (true/false); ricevuto: {verifica_hash_md!r}"
        )
    if file_path_md is not None and not file_path_md.strip():
        raise ValueError(
            "doc_metadata.file_path non puo' essere vuoto o composto da soli spazi bianchi (usare omissione/None se assente)"
        )
    if base_dir_md is not None and not base_dir_md.strip():
        raise ValueError(
            "doc_metadata.base_dir non puo' essere vuoto o composto da soli spazi bianchi (confinamento RT-07 obbligatorio se base_dir e' fornito)"
        )
    if verifica_hash_esplicito and (verifica_hash_md is False) and (file_path_md is not None):
        raise ValueError(
            "doc_metadata incoerente: verifica_hash_reale=False esplicito con file_path valorizzato "
            "(omettere file_path per la modalita' solo-metadato oppure impostare verifica_hash_reale=True)"
        )
    file_path_eff = file_path_md.strip() if isinstance(file_path_md, str) else ""
    base_dir_eff: Optional[str] = base_dir_md.strip() if isinstance(base_dir_md, str) else None
    verifica_hash_attiva = bool(verifica_hash_md) or bool(file_path_eff)

    # CR-01: anche 'metadato' (assenza di testo e di abstract acquisito) arresta il Gate L0 con RT-VNP
    l0_pass = identita_ok and not retracted and not errore_e8 and stato_accesso not in ("non disponibile", "metadato")
    trace_levels["L0_metadata_provenance"] = {
        "standard": ["S17", "S18", "S19", "RT-07"],
        "identita_ok": identita_ok,
        "is_retracted": retracted,
        "stato_accesso": stato_accesso,
        "has_full_text": has_full_text,
        "hash_presente": bool(hash_file),
        "formato_sha256_dichiarato_valido": (len(hash_file.strip()) == 64 and all(c in "0123456789abcdefABCDEF" for c in hash_file.strip())) if hash_file else False,
        "errore_E8": errore_e8,
        "gate_pass": l0_pass,
    }

    sottoblocco_l0: Optional[str] = None
    if not verifica_hash_attiva:
        # Modalita' solo-metadato (chiamate storiche): verifica su disco NON richiesta.
        trace_levels["L0_metadata_provenance"]["hash_verificato_su_disco"] = False
        trace_levels["L0_metadata_provenance"]["verifica_sha256_dettaglio"] = None
    elif not file_path_eff:
        # Verifica richiesta ma path del primario assente: arresto a L0 fail-closed (AL-04: gate_pass=False)
        trace_levels["L0_metadata_provenance"]["gate_pass"] = False
        trace_levels["L0_metadata_provenance"]["hash_verificato_su_disco"] = False
        trace_levels["L0_metadata_provenance"]["verifica_sha256_dettaglio"] = None
        trace_levels["L0_metadata_provenance"]["sottoblocco_l0"] = "L0_SHA256_FILE_PATH_MANCANTE"
        esito_l0 = "contrasta" if retracted else "verifica non possibile"
        return {
            "claim_id": claim_id,
            "livello_arresto": "L0",
            "esito_diotima": esito_l0,
            "tipo_errore": None,
            "blocco_attivo": "L0_PROVENANCE_OR_ACCESS_FAILURE",
            "sottoblocco_l0": "L0_SHA256_FILE_PATH_MANCANTE",
            "richiede_intervento_umano": True,
            "motivo": (
                f"Arresto a L0 (S17-S19/RT-07 v0.5): verifica SHA-256 reale richiesta ma doc_metadata.file_path "
                f"assente per '{claim_id}': fornire il percorso del primario congelato e l'hash atteso (hash_file)."
            ),
            "trace_levels": trace_levels,
        }

    ver_hash: Optional[Dict[str, Any]] = None
    if verifica_hash_attiva and file_path_eff:
        # ValueError di dominio (es. path traversal) risale esplicitamente al chiamante.
        ver_hash = verifica_integrita_primario_sha256(
            file_path_eff, hash_file, base_dir=base_dir_eff
        )
        trace_levels["L0_metadata_provenance"]["hash_verificato_su_disco"] = bool(ver_hash["ok"])
        trace_levels["L0_metadata_provenance"]["verifica_sha256_dettaglio"] = ver_hash
        l0_pass = l0_pass and bool(ver_hash["ok"])
        trace_levels["L0_metadata_provenance"]["gate_pass"] = l0_pass
        if not ver_hash["ok"]:
            if ver_hash["errore_E8"]:
                sottoblocco_l0 = "L0_FILE_PRIMARIO_ILLEGGIBILE_E8"
            elif ver_hash["esito_verifica"] == "FILE_PRIMARIO_NON_ACQUISITO":
                # RT-VNP: primario non acquisito, borne non e' un errore E8 (no codice E8).
                sottoblocco_l0 = "L0_FILE_PRIMARIO_NON_ACQUISITO"
            else:
                sottoblocco_l0 = f"L0_{ver_hash['esito_verifica']}"
            trace_levels["L0_metadata_provenance"]["sottoblocco_l0"] = sottoblocco_l0

    if not l0_pass:
        esito_l0 = "contrasta" if retracted else "verifica non possibile"
        cod_l0 = "E8" if (errore_e8 or (ver_hash is not None and ver_hash.get("errore_E8"))) else None
        payload_l0: Dict[str, Any] = {
            "claim_id": claim_id,
            "livello_arresto": "L0",
            "esito_diotima": esito_l0,
            "tipo_errore": cod_l0,
            "blocco_attivo": "L0_PROVENANCE_OR_ACCESS_FAILURE",
            "richiede_intervento_umano": True,
            "motivo": "Arresto a L0: documento non acquisito, solo metadato senza testo (RT-VNP), illeggibile (E8) o ritrattato (S18).",
            "trace_levels": trace_levels,
        }
        if sottoblocco_l0 is not None:
            payload_l0["sottoblocco_l0"] = sottoblocco_l0
            payload_l0["motivo"] = (
                f"Arresto a L0 ({sottoblocco_l0}): la verifica SHA-256 del primario su disco non ha dato "
                "esito positivo (S17-S19/RT-07 v0.5); dettaglio in trace_levels.L0_metadata_provenance."
            )
        return payload_l0

    # --- L1: Abstract Triage & Claim-Type Gate (S10-S11) ---
    if not isinstance(claim_type, str):
        raise ValueError(
            f"claim_type deve essere una stringa della tassonomia {list(ENUM_CLAIM_TYPE)}; ricevuto: {claim_type!r}"
        )
    ctype = claim_type.strip().lower()
    if ctype not in ENUM_CLAIM_TYPE:
        # Fail-closed (C07/C05): tassonomia ignota NON passa per un fallback numerico silenzioso.
        raise ValueError(
            f"claim_type='{claim_type}' non riconosciuto. Tassonomia ammessa: {list(ENUM_CLAIM_TYPE)}"
        )
    richiede_full_text = ctype != "qualitative"
    section_source = str(span_evidence.get("section", "Body")).strip().lower()
    solo_abstract = (not has_full_text) or (stato_accesso == "abstract") or (section_source == "abstract" and not has_full_text)

    blocco_l1_abstract = richiede_full_text and solo_abstract
    trace_levels["L1_abstract_triage"] = {
        "standard": ["S10", "S11", "S19"],
        "claim_type": ctype,
        "richiede_full_text_obbligatorio": richiede_full_text,
        "solo_abstract_disponibile": solo_abstract,
        "blocco_abstract_only": blocco_l1_abstract,
        "gate_pass": not blocco_l1_abstract,
    }

    if blocco_l1_abstract:
        # Differenza cruciale rispetto a Consensus: un claim quantitativo/metodologico
        # tratto da un record privo di full text (`has_full_text: false`) viene bloccato a L1!
        return {
            "claim_id": claim_id,
            "livello_arresto": "L1",
            "esito_diotima": "verifica non possibile" if not has_full_text else "insufficiente",
            "tipo_errore": None if not has_full_text else "E6",
            "blocco_attivo": "L1_BLOCK_ABSTRACT_ONLY_FOR_QUANT_METHOD_CLAIM",
            "richiede_intervento_umano": True,
            "motivo": (
                f"Blocco L1 (S10/S11/S19): il claim '{claim_id}' è di tipo '{ctype}' ma la fonte "
                f"dispone solo di Abstract (has_full_text={has_full_text}, section='{section_source}'). "
                "Diotima vieta di certificare claim quantitativi o metodologici senza ispezione del full text L2."
            ),
            "trace_levels": trace_levels,
        }

    # --- L2: Full-Text Span Verification & 5-Step Decision Tree (S12-S16, S20) ---
    quote_verified = bool(span_evidence.get("quote_verified_in_fulltext", True))
    coordinates_verified = bool(span_evidence.get("coordinates_verified", True))
    contradicts_claim = bool(span_evidence.get("contradicts_claim", False))
    numeric_mismatch = bool(span_evidence.get("numeric_mismatch", False))
    numeric_missing_unquantified = bool(span_evidence.get("numeric_missing_unquantified", False))
    vague_or_preliminary = bool(span_evidence.get("vague_or_preliminary", False))

    err_codes = []
    if not quote_verified:
        err_codes.append("E1")
    if not coordinates_verified:
        err_codes.append("E2")
    if numeric_mismatch or numeric_missing_unquantified:
        err_codes.append("E7")

    if contradicts_claim or numeric_mismatch or not quote_verified:
        esito_l2 = "contrasta"
        passo_5 = 2
    elif vague_or_preliminary:
        esito_l2 = "insufficiente"
        passo_5 = 3
    elif numeric_missing_unquantified or bool(span_evidence.get("partial_scope", False)):
        esito_l2 = "parziale"
        passo_5 = 4
    else:
        esito_l2 = "supporta"
        passo_5 = 5

    trace_levels["L2_fulltext_span_verification"] = {
        "standard": ["S12", "S13", "S14", "S15", "S16", "S20"],
        "section": span_evidence.get("section", "Body"),
        "page_or_sid": span_evidence.get("sid_or_page", "p. 1"),
        "passo_5passi_attivato": passo_5,
        "esito_L2": esito_l2,
        "codici_errore_L2": err_codes,
        "bloccante_M4b": bool(set(err_codes) & {"E1", "E2", "E7"}),
    }

    # --- L3: Critical Appraisal & Collider Bias Correction (S01-S06 & McElreath Cap. 6) ---
    vaglio_l3 = vaglio_epistemico_mcelreath(
        study_design=str(appr.get("study_design", "simulation")),
        rob2_or_robins_risk=str(appr.get("rob_risk", "moderate")),
        grade_certainty=str(appr.get("grade_certainty", "moderate")),
        newsworthiness_z=float(appr.get("newsworthiness_z", 1.0)),
        has_verified_full_text=has_full_text,
        sample_size_studies_or_records=int(appr.get("sample_size", 10)),
    )
    trace_levels["L3_critical_appraisal_collider"] = vaglio_l3

    # --- L4: Multi-Agent Categorical Error Marginalization & Human Adjudication (S07-S09, Cap. 15) ---
    if reader_provenance_l4 is not None and reader_votes_l4 is None:
        raise ValueError(
            "reader_provenance_l4 dichiarata ma reader_votes_l4 assente: dichiarare prima i voti dei lettori"
        )
    if reader_votes_l4 is None:
        # (C08/C06) NIENTE "consenso doppio": senza lettori indipendenti dichiarati le
        # osservazioni sono = le derivazioni esistenti (esito L2), 1 solo letto e l'indipendenza
        # NON e' sostenuta: adjudicazione umana richiesta.
        voti_osservati_l4 = [esito_l2]
        sorgente_voti = "derivate_da_L2_senza_lettori_indipendenti"
        numero_lettori_osservati = 1
        indipendenza_lettori = False
        reader_provenanza_tracciata: Optional[Dict[str, Any]] = None
        consolidamento_l4: Optional[Dict[str, Any]] = None
    else:
        if not isinstance(reader_votes_l4, (list, tuple)):
            raise ValueError(f"reader_votes_l4 deve essere una lista di Stati; ricevuto: {reader_votes_l4!r}")
        if len(reader_votes_l4) == 0:
            raise ValueError("reader_votes_l4 dichiarato ma vuoto: spostare absent o registrare lettori veri")

        # (C06 riv. 2026-10-19) L'indipendenza dei voti dichiarati non si assume: va ATTESTATA
        # dalla provenienza. Senza provenienza, o con attestazione non valida, i voti dichiarati
        # NON alimentano la verosimiglianza R volte: vengono consolidati in UNA sola osservazione
        # (nessun doppio aggiornamento che produca quasi-certezza sintetica), con flag indipendenza
        # False e adjudicazione umana richiesta.
        if reader_provenance_l4 is not None:
            if not isinstance(reader_provenance_l4, dict):
                raise ValueError(
                    f"reader_provenance_l4 deve essere un oggetto provenienza; ricevuto: {reader_provenance_l4!r}"
                )
            ids_lettori = reader_provenance_l4.get("id_lettori")
            attestata = reader_provenance_l4.get("indipendenza_attestata")
            if not (
                isinstance(ids_lettori, (list, tuple))
                and len(ids_lettori) > 0
                and all(isinstance(_id, str) and _id.strip() for _id in ids_lettori)
            ):
                raise ValueError(
                    "reader_provenance_l4.id_lettori deve essere una lista non vuota di stringhe "
                    f"non vuote (una per voto); ricevuto: {ids_lettori!r}"
                )
            # [O4 rev. 2026-10-19] review_r3_finale.md §5: un id con spazi iniziali/finali
            # non distingue in modo affidabile due lettori; senza questo controllo
            # ["L1", "L1 "] passava l'univocità e produceva un MAP 0.9969 sintetico.
            bordi_spaziati = [_id for _id in ids_lettori if _id != _id.strip()]
            if bordi_spaziati:
                raise ValueError(
                    "reader_provenance_l4.id_lettori contiene id con spazi iniziali o finali "
                    "(whitespace per str.strip()): usare id senza spazi ai bordi; ricevuti: "
                    f"{bordi_spaziati!r}"
                )
            if not isinstance(attestata, bool):
                raise ValueError(
                    "reader_provenance_l4.indipendenza_attestata deve essere un booleano (true/false), "
                    f"non una stringa; ricevuto: {attestata!r}"
                )
            if len(list(ids_lettori)) != len(reader_votes_l4):
                raise ValueError(
                    "reader_provenance_l4.id_lettori deve avere un id per ogni voto dichiarato "
                    f"({len(reader_votes_l4)}); ricevuti: {len(list(ids_lettori))}"
                )
            if len(set(ids_lettori)) != len(list(ids_lettori)):
                raise ValueError(
                    "reader_provenance_l4.id_lettori contiene id duplicati: l'indipendenza richiede "
                    "un id distinto per ciascun lettore; ricevuti: "
                    f"{list(ids_lettori)!r}"
                )
            reader_provenanza_tracciata = {
                "id_lettori": list(ids_lettori),
                "indipendenza_attestata": attestata,
            }
        else:
            reader_provenanza_tracciata = None

        if reader_provenanza_tracciata is not None and reader_provenanza_tracciata["indipendenza_attestata"]:
            # Due lettori reali indipendenti ammessi anche con esiti uguali: la concordanza
            # fra lettori attestati distinti resta overturnabile entro la soglia di entropia.
            voti_osservati_l4 = list(reader_votes_l4)
            sorgente_voti = "lettori_registrati_dal_chiamante_con_attestazione_indipendenza"
            numero_lettori_osservati = len(voti_osservati_l4)
            indipendenza_lettori = True
            consolidamento_l4 = None
        else:
            voti_osservati_l4 = [reader_votes_l4[0]]
            sorgente_voti = "lettori_registrati_dal_chiamante_senza_attestazione_indipendenza"
            numero_lettori_osservati = 1
            indipendenza_lettori = False
            consolidamento_l4 = {
                "consolidato_a_una_osservazione": True,
                "motivo": (
                    "voti dichiarati senza provenienza con attestazione di indipendenza "
                    "(id distinti): usare R volte la stessa provenienza UPDATE e' un doppio "
                    "aggiornamento che genera quasi-certezza sintetica (McElreath Cap. 15 §15.3)"
                ),
                "voti_dichiarati_non_marginalizzati": list(reader_votes_l4),
                "reader_provenance_ricevuta": reader_provenanza_tracciata,
            }
    l4_marg = marginalizza_errore_categoriale_l4(
        voti_osservati_l4,
        sorgente_voti=sorgente_voti,
        numero_lettori_osservati=numero_lettori_osservati,
        indipendenza_lettori_sostenuta=indipendenza_lettori,
    )
    richiede_umano_finale = (
        l4_marg["richiede_adjudicazione_umana"]
        or bool(err_codes)
        or vaglio_l3["peso_epistemico_diotima"] < 0.45
    )
    trace_levels["L4_multi_agent_and_human_adjudication"] = {
        "standard": ["S07", "S08", "S09", "McElreath_Cap15_Sec15_3"],
        "marginalizzazione_categoriale": l4_marg,
        "richiede_intervento_umano_finale": richiede_umano_finale,
        "sorgente_voti": sorgente_voti,
        "numero_lettori_osservati": numero_lettori_osservati,
        "indipendenza_lettori_sostenuta": indipendenza_lettori,
        "reader_provenance_l4": reader_provenanza_tracciata,
        "consolidamento_voti_non_attestati": consolidamento_l4,
    }

    return {
        "claim_id": claim_id,
        "claim_text": claim_text,
        "livello_completato": "L4",
        "esito_diotima": l4_marg["stato_map"] if "stato_map" in l4_marg else l4_marg["stato_posteriore_MAP"],
        "esito_L2_5passi": esito_l2,
        "tipo_errore": ", ".join(err_codes) if err_codes else None,
        "peso_epistemico_mcelreath": vaglio_l3["peso_epistemico_diotima"],
        "entropia_posteriore_L4": l4_marg["entropia_shannon_normalizzata"],
        "richiede_intervento_umano": richiede_umano_finale,
        "trace_levels": trace_levels,
    }


# ============================================================================
# 5. OVERRIDE UMANO APPEND-ONLY
# ============================================================================


def registra_human_override(
    target_id: str,
    decisione_golem_precedente: str,
    nuova_decisione_umana: str,
    motivazione_metodologica: str,
    revisore_id: str,
    codice_regola_invocata: str = "L4_HUMAN_ADJUDICATION",
    timestamp_iso: str = "2026-10-18T16:25:00Z",
) -> Dict[str, Any]:
    """
    Registra un intervento umano motivato (`diotima_human_override`) che sovrascrive o
    congela il verdetto automatico del Golem statistico (McElreath Cap. 1: *The Golem of Prague*),
    generando un record append-only firmato con hash SHA-256 deterministico.
    """
    if not motivazione_metodologica or len(motivazione_metodologica.strip()) < 10:
        raise ValueError(
            "L'intervento umano richiede una motivazione metodologica esplicita (>= 10 caratteri)."
        )

    payload_canonical = json.dumps(
        {
            "target_id": target_id,
            "decisione_golem_precedente": decisione_golem_precedente,
            "nuova_decisione_umana": nuova_decisione_umana,
            "motivazione_metodologica": motivazione_metodologica.strip(),
            "revisore_id": revisore_id,
            "codice_regola_invocata": codice_regola_invocata,
            "timestamp_iso": timestamp_iso,
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    sha256_seal = hashlib.sha256(payload_canonical.encode("utf-8")).hexdigest()

    return {
        "evento": "HUMAN_OVERRIDE_APPEND_ONLY",
        "target_id": target_id,
        "revisore_id": revisore_id,
        "codice_regola_invocata": codice_regola_invocata,
        "decisione_golem_precedente": decisione_golem_precedente,
        "nuova_decisione_umana": nuova_decisione_umana,
        "motivazione_metodologica": motivazione_metodologica.strip(),
        "timestamp_iso": timestamp_iso,
        "golem_congelato": True,
        "sha256_audit_seal": sha256_seal,
    }
