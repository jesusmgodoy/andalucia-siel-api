"""Checks on source data; never repair or impute the original figures."""
from __future__ import annotations

from typing import Any


def assess_record(record: dict[str, Any]) -> dict[str, Any]:
    issues: list[str] = []
    incomplete = False
    summary = record.get("resumen") if isinstance(record.get("resumen"), dict) else {}
    scrutiny = record.get("escrutinio") if isinstance(record.get("escrutinio"), dict) else {}
    params = record.get("source", {}).get("params", {})
    context = record.get("context", {})
    if "provincia_clave" in context:
        params = {"cautonoma": 1, "tconvocatoria": context.get("tconvocatoria"),
                  "fconvocatoria": context.get("fconvocatoria")}
        if context.get("ambito") != "cautonoma":
            params["provincia"] = context.get("provincia_clave")
        if "mesa_valor" in context:
            params.update({"municipio": context.get("municipio_clave"),
                           "distrito": context.get("distrito_clave"),
                           "seccion": context.get("seccion_valor"), "mesa": context.get("mesa_valor")})
    for name, payload in (("resumen", summary), ("escrutinio", scrutiny)):
        identity = payload.get("idescrutinio") if isinstance(payload.get("idescrutinio"), dict) else {}
        for key, expected in params.items():
            actual = identity.get(key)
            if isinstance(actual, dict):
                actual = actual.get("valor" if key in {"mesa", "seccion"} else "clave")
            if actual is None:
                incomplete = True
                issues.append(f"{name}: falta identidad {key}")
            elif str(actual) != str(expected):
                issues.append(f"{name}: identidad {key}={actual!r}, esperada {expected!r}")

    for total, parts in (
        ("censo", ("votostotales", "abstenciones")),
        ("votostotales", ("votosvalidos", "votosnulos")),
        ("votosvalidos", ("votosblanco", "votoscandidatura")),
    ):
        values = [summary.get(k) for k in (total, *parts)]
        if not all(isinstance(v, int) and not isinstance(v, bool) and v >= 0 for v in values):
            incomplete = True
            issues.append(f"campos ausentes o inválidos: {total}, {', '.join(parts)}")
        elif values[0] != sum(values[1:]):
            issues.append(f"{total}={values[0]} != {'+'.join(parts)}={sum(values[1:])}")

    votes = scrutiny.get("votos")
    if not isinstance(votes, list) or any(
        not isinstance(v, dict) or not v.get("conjunto")
        or not isinstance(v.get("numvotos"), int) or isinstance(v.get("numvotos"), bool)
        or v["numvotos"] < 0 for v in (votes if isinstance(votes, list) else [])
    ):
        incomplete = True
        issues.append("lista de votos ausente o inválida")
    else:
        names = [v["conjunto"] for v in votes]
        if len(names) != len(set(names)):
            issues.append("candidaturas duplicadas")
        total = sum(v["numvotos"] for v in votes)
        if total != summary.get("votoscandidatura"):
            issues.append(f"suma de candidaturas={total} != votoscandidatura={summary.get('votoscandidatura')}")
    # Older archives synthesized an empty scrutiny from a zero summary after
    # HTTP failure. Keep those bytes, but never certify the fabricated vote list.
    if (record.get("estado_descarga") == "ok_sin_votos"
            and any("escrutinio" in str(e.get("endpoint", "")) for e in (record.get("errors") or []) if isinstance(e, dict))):
        incomplete = True
        issues.append("resumen a cero sin escrutinio original; cero real no verificado")
    if record.get("estado_descarga", "ok") not in {"ok", "ok_sin_votos"}:
        incomplete = True
    state = "incompleto" if incomplete else "inconsistente" if issues else "ok"
    return {"estado_calidad": state, "incidencias_calidad": " | ".join(issues) or None}


def retryable_record(record: dict[str, Any]) -> bool:
    return (record.get("estado_descarga", "ok") not in {"ok", "ok_sin_votos"}
            or assess_record(record)["estado_calidad"] == "incompleto")
