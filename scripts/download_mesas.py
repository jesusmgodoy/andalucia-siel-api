#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from andalucia_siel.client import BASE_URL, SielApiError, SielClient
from andalucia_siel.quality import assess_record, retryable_record
from andalucia_siel.storage import open_text, raw_path as find_raw_path, read_records, replace_records, unique_records

TCONVOCATORIA_AUTONOMICAS = 5
CAUTONOMA_ANDALUCIA = 1

CONTEXT_FIELDS = [
    "tconvocatoria",
    "fconvocatoria",
    "provincia_clave",
    "provincia_nombre",
    "municipio_clave",
    "municipio_nombre",
    "distrito_clave",
    "distrito_nombre",
    "seccion_clave",
    "seccion_valor",
    "mesa_clave",
    "mesa_valor",
]

SUMMARY_FIELDS = [
    "censo",
    "abstenciones",
    "votostotales",
    "votosnulos",
    "votosvalidos",
    "votosblanco",
    "votoscandidatura",
    "nummesas",
]

DOWNLOAD_FIELDS = [
    "fuente_registro",
    "estado_descarga",
    "error_descarga",
    "estado_calidad",
    "incidencias_calidad",
]

LONG_FIELDS = CONTEXT_FIELDS + SUMMARY_FIELDS + [
    *DOWNLOAD_FIELDS,
    "conjunto",
    "numvotos",
    "porcentajeVotos",
    "diputados",
]

RAUSENTES_CONTEXT_FIELDS = [
    "tconvocatoria",
    "fconvocatoria",
    "ambito",
    "provincia_clave",
    "provincia_nombre",
]

RAUSENTES_LONG_FIELDS = RAUSENTES_CONTEXT_FIELDS + SUMMARY_FIELDS + [
    *DOWNLOAD_FIELDS,
    "conjunto",
    "numvotos",
    "porcentajeVotos",
    "diputados",
]

COMPLETE_BASE_FIELDS = [
    "tipo_registro",
    "ambito",
    *DOWNLOAD_FIELDS,
    "tconvocatoria",
    "fconvocatoria",
    "provincia_clave",
    "provincia_nombre",
    "municipio_clave",
    "municipio_nombre",
    "distrito_clave",
    "distrito_nombre",
    "seccion_clave",
    "seccion_valor",
    "mesa_clave",
    "mesa_valor",
    "censo",
    "votantes",
    "abstenciones",
    "participacion_pct",
    "abstencion_pct",
    "votos_nulos",
    "nulos_pct_votantes",
    "votos_validos",
    "votos_blanco",
    "blanco_pct_validos",
    "votos_candidaturas",
]

MISSING_PARTY_VOTES_STATUSES = {
    "cera_no_disponible",
    "mesa_no_disponible",
    "escrutinio_no_disponible",
    "error_interno_script",
}


def now_utc() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def sort_clave_valor(items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(items, key=lambda item: (str(item.get("valor", "")), str(item.get("clave", ""))))


def pct(part: int | float | None, total: int | float | None) -> float | None:
    if part is None or total in (None, 0):
        return None
    return round((part / total) * 100, 4)


def api_error_detail(exc: BaseException) -> dict[str, Any]:
    detail = {"message": str(exc)}
    url = getattr(exc, "url", None)
    status_code = getattr(exc, "status_code", None)
    response_text = getattr(exc, "response_text", None)
    if url:
        detail["url"] = url
    if status_code:
        detail["status_code"] = status_code
    if response_text:
        detail["response_text"] = response_text
    return detail


def error_text(errors: list[dict[str, Any]] | None) -> str | None:
    if not errors:
        return None
    parts = []
    for error in errors:
        endpoint = error.get("endpoint")
        status_code = error.get("status_code")
        message = error.get("message")
        prefix = endpoint or "api"
        if status_code:
            prefix = f"{prefix} HTTP {status_code}"
        parts.append(f"{prefix}: {message}")
    return " | ".join(parts)


def download_fields(record: dict[str, Any], default_fuente: str) -> dict[str, Any]:
    return {
        "fuente_registro": record.get("fuente_registro", default_fuente),
        "estado_descarga": record.get("estado_descarga", "ok"),
        "error_descarga": record.get("error_descarga") or error_text(record.get("errors")),
        **assess_record(record),
    }


def party_votes_are_known(record: dict[str, Any]) -> bool:
    return (record.get("estado_descarga", "ok") not in MISSING_PARTY_VOTES_STATUSES
            and assess_record(record)["estado_calidad"] != "incompleto")


def record_votes(record: dict[str, Any]) -> list[dict[str, Any]]:
    scrutiny = record.get("escrutinio")
    votes = scrutiny.get("votos") if isinstance(scrutiny, dict) else None
    return [vote for vote in votes if isinstance(vote, dict)] if isinstance(votes, list) else []


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def read_ndjson(path: Path) -> Iterable[dict[str, Any]]:
    return read_records(path)


def count_ndjson_records(path: Path) -> int:
    return sum(1 for _ in read_ndjson(path))


def mesa_params(context: dict[str, Any]) -> dict[str, Any]:
    return {
        "cautonoma": CAUTONOMA_ANDALUCIA,
        "tconvocatoria": context["tconvocatoria"],
        "fconvocatoria": context["fconvocatoria"],
        "provincia": context["provincia_clave"],
        "municipio": context["municipio_clave"],
        "distrito": context["distrito_clave"],
        "seccion": context["seccion_valor"],
        "mesa": context["mesa_valor"],
    }


def context_key(context: dict[str, Any]) -> tuple[Any, ...]:
    return (
        context.get("tconvocatoria"),
        context.get("fconvocatoria"),
        context.get("provincia_clave"),
        context.get("municipio_clave"),
        context.get("distrito_clave"),
        str(context.get("seccion_valor")),
        str(context.get("mesa_valor")),
    )


def list_municipio_mesa_contexts(
    client: SielClient,
    fconvocatoria: int,
    provincia: dict[str, Any],
    municipio: dict[str, Any],
) -> list[dict[str, Any]]:
    provincia_clave = int(provincia["clave"])
    municipio_clave = int(municipio["clave"])
    base = {
        "cautonoma": CAUTONOMA_ANDALUCIA,
        "tconvocatoria": TCONVOCATORIA_AUTONOMICAS,
        "fconvocatoria": fconvocatoria,
        "provincia": provincia_clave,
        "municipio": municipio_clave,
    }
    contexts: list[dict[str, Any]] = []
    distritos = sort_clave_valor(client.opciones("distrito", base))
    for distrito in distritos:
        distrito_clave = int(distrito["clave"])
        secciones = sort_clave_valor(client.opciones("seccion", {**base, "distrito": distrito_clave}))
        for seccion in secciones:
            mesas = sort_clave_valor(
                client.opciones(
                    "mesa",
                    {
                        **base,
                        "distrito": distrito_clave,
                        "seccion": seccion["valor"],
                    },
                )
            )
            for mesa in mesas:
                contexts.append(
                    {
                        "tconvocatoria": TCONVOCATORIA_AUTONOMICAS,
                        "fconvocatoria": fconvocatoria,
                        "provincia_clave": provincia_clave,
                        "provincia_nombre": provincia["valor"],
                        "municipio_clave": municipio_clave,
                        "municipio_nombre": municipio["valor"],
                        "distrito_clave": distrito_clave,
                        "distrito_nombre": distrito["valor"],
                        "seccion_clave": seccion["clave"],
                        "seccion_valor": seccion["valor"],
                        "mesa_clave": mesa["clave"],
                        "mesa_valor": mesa["valor"],
                    }
                )
    return contexts


def iter_mesa_contexts(
    client: SielClient,
    fconvocatoria: int,
    province_filter: set[int] | None = None,
    limit: int | None = None,
    workers: int = 1,
) -> Iterable[dict[str, Any]]:
    base = {
        "cautonoma": CAUTONOMA_ANDALUCIA,
        "tconvocatoria": TCONVOCATORIA_AUTONOMICAS,
        "fconvocatoria": fconvocatoria,
    }
    provincias = sort_clave_valor(client.opciones("provincia", {"cautonoma": CAUTONOMA_ANDALUCIA}))
    yielded = 0

    for provincia in provincias:
        provincia_clave = int(provincia["clave"])
        if province_filter and provincia_clave not in province_filter:
            continue

        municipios = sort_clave_valor(
            client.opciones(
                "municipio",
                {**base, "provincia": provincia_clave},
            )
        )
        print(
            f"[{fconvocatoria}] {provincia['valor']}: {len(municipios)} municipios",
            file=sys.stderr,
        )

        if limit is None and workers > 1:
            completed = 0
            with ThreadPoolExecutor(max_workers=workers) as executor:
                futures = {
                    executor.submit(list_municipio_mesa_contexts, client, fconvocatoria, provincia, municipio): municipio
                    for municipio in municipios
                }
                for future in as_completed(futures):
                    completed += 1
                    for context in future.result():
                        yield context
                    if completed % 25 == 0 or completed == len(municipios):
                        print(
                            f"[{fconvocatoria}] {provincia['valor']}: "
                            f"{completed}/{len(municipios)} municipios enumerados",
                            file=sys.stderr,
                        )
            continue

        for municipio in municipios:
            for context in list_municipio_mesa_contexts(client, fconvocatoria, provincia, municipio):
                yield context
                yielded += 1
                if limit is not None and yielded >= limit:
                    return


def download_mesa(client: SielClient, context: dict[str, Any]) -> dict[str, Any]:
    params = mesa_params(context)
    source = {
        "api_base": client.base_url,
        "resumen_url": client.build_url("/v1/resumen/mesa", params),
        "escrutinio_url": client.build_url("/v1/escrutinio/ambito/mesa", params),
        "params": params,
    }
    record = {
        "source": {
            **source,
        },
        "context": context,
        "fuente_registro": "api_mesa",
        "estado_descarga": "ok",
        "error_descarga": None,
        "errors": [],
    }
    try:
        resumen = client.resumen_mesa(params)
    except SielApiError as exc:
        detail = {"endpoint": "resumen/mesa", **api_error_detail(exc)}
        record.update(
            {
                "resumen": {},
                "escrutinio": {"votos": []},
                "fuente_registro": "catalogo_mesa",
                "estado_descarga": "mesa_no_disponible",
                "errors": [detail],
                "error_descarga": error_text([detail]),
            }
        )
        return record

    record["resumen"] = resumen
    try:
        record["escrutinio"] = client.escrutinio_mesa(params)
        return record
    except SielApiError as exc:
        detail = {"endpoint": "escrutinio/ambito/mesa", **api_error_detail(exc)}
        votos_candidatura = resumen.get("votoscandidatura")
        votos_totales = resumen.get("votostotales")
        record.update(
            {
                "escrutinio": {},
                "fuente_registro": "api_resumen_mesa_parcial",
                "estado_descarga": "resumen_cero_sin_escrutinio" if votos_candidatura == 0 and votos_totales == 0 else "escrutinio_no_disponible",
                "errors": [detail],
                "error_descarga": error_text([detail]),
            }
        )
        return record


def unavailable_mesa_record(client: SielClient, context: dict[str, Any], exc: BaseException) -> dict[str, Any]:
    params = mesa_params(context)
    detail = {"endpoint": "download_mesa", **api_error_detail(exc)}
    return {
        "source": {
            "api_base": client.base_url,
            "resumen_url": client.build_url("/v1/resumen/mesa", params),
            "escrutinio_url": client.build_url("/v1/escrutinio/ambito/mesa", params),
            "params": params,
        },
        "context": context,
        "resumen": {},
        "escrutinio": {"votos": []},
        "fuente_registro": "catalogo_mesa",
        "estado_descarga": "error_interno_script",
        "errors": [detail],
        "error_descarga": error_text([detail]),
    }


def iter_rausentes_contexts(
    client: SielClient,
    fconvocatoria: int,
    province_filter: set[int] | None = None,
) -> Iterable[dict[str, Any]]:
    if province_filter is None:
        yield {
            "tconvocatoria": TCONVOCATORIA_AUTONOMICAS,
            "fconvocatoria": fconvocatoria,
            "ambito": "cautonoma",
            "provincia_clave": None,
            "provincia_nombre": None,
        }

    provincias = sort_clave_valor(client.opciones("provincia", {"cautonoma": CAUTONOMA_ANDALUCIA}))
    for provincia in provincias:
        provincia_clave = int(provincia["clave"])
        if province_filter and provincia_clave not in province_filter:
            continue
        yield {
            "tconvocatoria": TCONVOCATORIA_AUTONOMICAS,
            "fconvocatoria": fconvocatoria,
            "ambito": "provincia",
            "provincia_clave": provincia_clave,
            "provincia_nombre": provincia["valor"],
        }


def rausentes_params(context: dict[str, Any]) -> dict[str, Any]:
    params = {
        "cautonoma": CAUTONOMA_ANDALUCIA,
        "tconvocatoria": context["tconvocatoria"],
        "fconvocatoria": context["fconvocatoria"],
    }
    if context["ambito"] == "provincia":
        params["provincia"] = context["provincia_clave"]
    return params


def download_rausentes_record(client: SielClient, context: dict[str, Any]) -> dict[str, Any]:
    ambito = context["ambito"]
    params = rausentes_params(context)
    return {
        "source": {
            "api_base": client.base_url,
            "resumen_url": client.build_url(f"/v1/resumen/rausentes/{ambito}", params),
            "escrutinio_url": client.build_url(f"/v1/escrutinio/ambito/rausentes/{ambito}", params),
            "params": params,
        },
        "context": context,
        "fuente_registro": "api_cera",
        "estado_descarga": "ok",
        "error_descarga": None,
        "errors": [],
        "resumen": client.resumen_rausentes(ambito, params),
        "escrutinio": client.escrutinio_rausentes(ambito, params),
    }


def unavailable_rausentes_record(client: SielClient, context: dict[str, Any], exc: BaseException) -> dict[str, Any]:
    ambito = context["ambito"]
    params = rausentes_params(context)
    detail = {"endpoint": f"rausentes/{ambito}", **api_error_detail(exc)}
    return {
        "source": {
            "api_base": client.base_url,
            "resumen_url": client.build_url(f"/v1/resumen/rausentes/{ambito}", params),
            "escrutinio_url": client.build_url(f"/v1/escrutinio/ambito/rausentes/{ambito}", params),
            "params": params,
        },
        "context": context,
        "fuente_registro": "catalogo_cera",
        "estado_descarga": "cera_no_disponible",
        "error_descarga": error_text([detail]),
        "errors": [detail],
        "resumen": {},
        "escrutinio": {"votos": []},
    }


def base_csv_row(record: dict[str, Any]) -> dict[str, Any]:
    context = record["context"]
    resumen = record.get("resumen", {})
    row = {field: context.get(field) for field in CONTEXT_FIELDS}
    row.update({field: resumen.get(field) for field in SUMMARY_FIELDS})
    row.update(download_fields(record, "api_mesa"))
    return row


def base_rausentes_csv_row(record: dict[str, Any]) -> dict[str, Any]:
    context = record["context"]
    resumen = record.get("resumen", {})
    row = {field: context.get(field) for field in RAUSENTES_CONTEXT_FIELDS}
    row.update({field: resumen.get(field) for field in SUMMARY_FIELDS})
    row.update(download_fields(record, "api_cera"))
    return row


def write_catalog_csv(path: Path, contexts: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CONTEXT_FIELDS)
        writer.writeheader()
        writer.writerows(contexts)


def read_catalog_csv(path: Path) -> list[dict[str, Any]]:
    contexts: list[dict[str, Any]] = []
    int_fields = {
        "tconvocatoria",
        "fconvocatoria",
        "provincia_clave",
        "municipio_clave",
        "distrito_clave",
        "seccion_clave",
        "mesa_clave",
    }
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            context: dict[str, Any] = {}
            for field in CONTEXT_FIELDS:
                value = row.get(field)
                if field in int_fields and value not in (None, ""):
                    context[field] = int(value)
                else:
                    context[field] = value
            contexts.append(context)
    return contexts


def sort_mesa_contexts(contexts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        contexts,
        key=lambda context: (
            context["provincia_clave"],
            context["municipio_clave"],
            context["distrito_clave"],
            str(context["seccion_valor"]),
            str(context["mesa_valor"]),
        ),
    )


def write_long_csv(ndjson_path: Path, csv_path: Path) -> int:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    row_count = 0
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=LONG_FIELDS)
        writer.writeheader()
        for record in read_ndjson(ndjson_path):
            base = base_csv_row(record)
            for voto in record_votes(record):
                row = dict(base)
                row.update(
                    {
                        "conjunto": voto.get("conjunto"),
                        "numvotos": voto.get("numvotos"),
                        "porcentajeVotos": voto.get("porcentajeVotos"),
                        "diputados": voto.get("diputados"),
                    }
                )
                writer.writerow(row)
                row_count += 1
    return row_count


def write_wide_csv(ndjson_path: Path, csv_path: Path) -> int:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    conjuntos: list[str] = []
    seen: set[str] = set()
    for record in read_ndjson(ndjson_path):
        for voto in record_votes(record):
            conjunto = voto.get("conjunto")
            if conjunto and conjunto not in seen:
                seen.add(conjunto)
                conjuntos.append(conjunto)

    fieldnames = CONTEXT_FIELDS + SUMMARY_FIELDS + DOWNLOAD_FIELDS + sorted(conjuntos)
    row_count = 0
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for record in read_ndjson(ndjson_path):
            row = base_csv_row(record)
            default_value = 0 if party_votes_are_known(record) else None
            row.update({conjunto: default_value for conjunto in conjuntos})
            for voto in record_votes(record):
                conjunto = voto.get("conjunto")
                if conjunto:
                    row[conjunto] = voto.get("numvotos", 0)
            writer.writerow(row)
            row_count += 1
    return row_count


def write_rausentes_long_csv(ndjson_path: Path, csv_path: Path) -> int:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    row_count = 0
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=RAUSENTES_LONG_FIELDS)
        writer.writeheader()
        for record in read_ndjson(ndjson_path):
            base = base_rausentes_csv_row(record)
            for voto in record_votes(record):
                row = dict(base)
                row.update(
                    {
                        "conjunto": voto.get("conjunto"),
                        "numvotos": voto.get("numvotos"),
                        "porcentajeVotos": voto.get("porcentajeVotos"),
                        "diputados": voto.get("diputados"),
                    }
                )
                writer.writerow(row)
                row_count += 1
    return row_count


def write_rausentes_wide_csv(ndjson_path: Path, csv_path: Path) -> int:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    conjuntos: list[str] = []
    seen: set[str] = set()
    for record in read_ndjson(ndjson_path):
        for voto in record_votes(record):
            conjunto = voto.get("conjunto")
            if conjunto and conjunto not in seen:
                seen.add(conjunto)
                conjuntos.append(conjunto)

    fieldnames = RAUSENTES_CONTEXT_FIELDS + SUMMARY_FIELDS + DOWNLOAD_FIELDS + sorted(conjuntos)
    row_count = 0
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for record in read_ndjson(ndjson_path):
            row = base_rausentes_csv_row(record)
            default_value = 0 if party_votes_are_known(record) else None
            row.update({conjunto: default_value for conjunto in conjuntos})
            for voto in record_votes(record):
                conjunto = voto.get("conjunto")
                if conjunto:
                    row[conjunto] = voto.get("numvotos", 0)
            writer.writerow(row)
            row_count += 1
    return row_count


def iter_complete_source_records(mesas_path: Path, rausentes_path: Path | None) -> Iterable[dict[str, Any]]:
    for record in read_ndjson(mesas_path):
        yield {"tipo_registro": "mesa", "ambito": "mesa", "record": record}

    if rausentes_path is None or not rausentes_path.exists():
        return

    for record in read_ndjson(rausentes_path):
        context = record.get("context", {})
        if context.get("ambito") != "provincia":
            continue
        yield {"tipo_registro": "cera", "ambito": "cera_provincia", "record": record}


def complete_row_base(source: dict[str, Any]) -> dict[str, Any]:
    record = source["record"]
    context = record["context"]
    resumen = record.get("resumen", {})
    votantes = resumen.get("votostotales")
    censo = resumen.get("censo")
    votos_validos = resumen.get("votosvalidos")

    if source["tipo_registro"] == "mesa":
        row = {
            "tipo_registro": "mesa",
            "ambito": "mesa",
            **download_fields(record, "api_mesa"),
            "tconvocatoria": context.get("tconvocatoria"),
            "fconvocatoria": context.get("fconvocatoria"),
            "provincia_clave": context.get("provincia_clave"),
            "provincia_nombre": context.get("provincia_nombre"),
            "municipio_clave": context.get("municipio_clave"),
            "municipio_nombre": context.get("municipio_nombre"),
            "distrito_clave": context.get("distrito_clave"),
            "distrito_nombre": context.get("distrito_nombre"),
            "seccion_clave": context.get("seccion_clave"),
            "seccion_valor": context.get("seccion_valor"),
            "mesa_clave": context.get("mesa_clave"),
            "mesa_valor": context.get("mesa_valor"),
        }
    else:
        row = {
            "tipo_registro": "cera",
            "ambito": "cera_provincia",
            **download_fields(record, "api_cera"),
            "tconvocatoria": context.get("tconvocatoria"),
            "fconvocatoria": context.get("fconvocatoria"),
            "provincia_clave": context.get("provincia_clave"),
            "provincia_nombre": context.get("provincia_nombre"),
            "municipio_clave": None,
            "municipio_nombre": None,
            "distrito_clave": None,
            "distrito_nombre": None,
            "seccion_clave": None,
            "seccion_valor": None,
            "mesa_clave": "CERA",
            "mesa_valor": "CERA",
        }

    row.update(
        {
            "censo": censo,
            "votantes": votantes,
            "abstenciones": resumen.get("abstenciones"),
            "participacion_pct": pct(votantes, censo),
            "abstencion_pct": pct(resumen.get("abstenciones"), censo),
            "votos_nulos": resumen.get("votosnulos"),
            "nulos_pct_votantes": pct(resumen.get("votosnulos"), votantes),
            "votos_validos": votos_validos,
            "votos_blanco": resumen.get("votosblanco"),
            "blanco_pct_validos": pct(resumen.get("votosblanco"), votos_validos),
            "votos_candidaturas": resumen.get("votoscandidatura"),
        }
    )
    return row


def write_complete_csv(mesas_path: Path, rausentes_path: Path | None, csv_path: Path) -> int:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    conjuntos: list[str] = []
    seen: set[str] = set()
    for source in iter_complete_source_records(mesas_path, rausentes_path):
        for voto in record_votes(source["record"]):
            conjunto = voto.get("conjunto")
            if conjunto and conjunto not in seen:
                seen.add(conjunto)
                conjuntos.append(conjunto)

    fieldnames = COMPLETE_BASE_FIELDS + sorted(conjuntos)
    row_count = 0
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for source in iter_complete_source_records(mesas_path, rausentes_path):
            record = source["record"]
            row = complete_row_base(source)
            default_value = 0 if party_votes_are_known(record) else None
            row.update({conjunto: default_value for conjunto in conjuntos})
            for voto in record_votes(record):
                conjunto = voto.get("conjunto")
                if conjunto:
                    row[conjunto] = voto.get("numvotos", 0)
            writer.writerow(row)
            row_count += 1
    return row_count


def write_mesa_incidents_csv(ndjson_path: Path, csv_path: Path) -> int:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = CONTEXT_FIELDS + DOWNLOAD_FIELDS + ["resumen_url", "escrutinio_url"]
    row_count = 0
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for record in read_ndjson(ndjson_path):
            status = record.get("estado_descarga", "ok")
            if status == "ok" and not record.get("errors") and assess_record(record)["estado_calidad"] == "ok":
                continue
            row = {field: record.get("context", {}).get(field) for field in CONTEXT_FIELDS}
            row.update(download_fields(record, "api_mesa"))
            source = record.get("source", {})
            row["resumen_url"] = source.get("resumen_url")
            row["escrutinio_url"] = source.get("escrutinio_url")
            writer.writerow(row)
            row_count += 1
    return row_count


def count_download_statuses(ndjson_path: Path) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in read_ndjson(ndjson_path):
        status = record.get("estado_descarga", "ok")
        counts[status] = counts.get(status, 0) + 1
    return dict(sorted(counts.items()))


def save_source_metadata(client: SielClient, output_dir: Path) -> None:
    raw_dir = output_dir / "raw"
    opciones_dir = raw_dir / "opciones"
    write_json(raw_dir / "api_docs.json", client.api_docs())
    write_json(
        opciones_dir / "fconvocatoria_t5.json",
        client.opciones("fconvocatoria", {"tconvocatoria": TCONVOCATORIA_AUTONOMICAS}),
    )
    write_json(
        opciones_dir / "provincias.json",
        client.opciones("provincia", {"cautonoma": CAUTONOMA_ANDALUCIA}),
    )


def list_convocatorias(client: SielClient) -> None:
    convocatorias = client.opciones("fconvocatoria", {"tconvocatoria": TCONVOCATORIA_AUTONOMICAS})
    print("clave,valor")
    for item in convocatorias:
        print(f"{item['clave']},{item['valor']}")


def catalog_scope(fconvocatoria: int, province_filter: set[int] | None, limit: int | None) -> dict[str, Any]:
    return {"version": 1, "fconvocatoria": fconvocatoria, "tconvocatoria": 5,
            "provinces": sorted(province_filter) if province_filter else None, "limit_mesas": limit}


def catalog_digest(contexts: list[dict[str, Any]]) -> str:
    keys = sorted(context_key(c) for c in contexts)
    return hashlib.sha256(json.dumps(keys, ensure_ascii=False).encode()).hexdigest()


def check_catalog(contexts: list[dict[str, Any]], election: int) -> set[tuple]:
    if not contexts:
        raise ValueError(f"Catálogo vacío para {election}; no se puede declarar completo.")
    keys = set()
    for context in contexts:
        if context.get("fconvocatoria") != election or context.get("tconvocatoria") != 5:
            raise ValueError("El catálogo contiene otra convocatoria.")
        if any(context.get(field) in (None, "") for field in (
            "provincia_clave", "municipio_clave", "distrito_clave", "seccion_valor", "mesa_valor")):
            raise ValueError("El catálogo contiene una clave incompleta.")
        key = context_key(context)
        if key in keys:
            raise ValueError(f"Clave duplicada en catálogo: {key}")
        keys.add(key)
    return keys


def cera_key(context: dict[str, Any]) -> tuple:
    return (context.get("tconvocatoria"), context.get("fconvocatoria"),
            context.get("ambito"), context.get("provincia_clave"))


def update_raw(client, contexts, path, election, key, fetch, fallback, workers, resume, overwrite, retry_failed):
    existing = unique_records(path, key, election) if resume and not overwrite else {}
    expected = {key(context) for context in contexts}
    if set(existing) - expected:
        raise ValueError("El raw contiene registros fuera del ámbito solicitado. Usa otra carpeta para reducir el ámbito.")
    pending = [ctx for ctx in contexts if key(ctx) not in existing
               or (retry_failed and retryable_record(existing[key(ctx)]))]
    replacements = {}
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = "a" if resume and path.exists() and not overwrite else "w"
    with open_text(path, mode) as handle:
        with ThreadPoolExecutor(max_workers=max(workers, 1)) as executor:
            futures = {executor.submit(fetch, client, ctx): ctx for ctx in pending}
            for future in as_completed(futures):
                ctx = futures[future]
                try:
                    record = future.result()
                except Exception as exc:
                    record = fallback(client, ctx, exc)
                identity = key(ctx)
                if identity in existing:
                    # Retry replacements never append a duplicate identity.
                    replacements[identity] = record
                else:
                    handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
                    handle.flush()
                existing[identity] = record
    if replacements:
        replace_records(path, (existing[k] for k in sorted(existing, key=str)))
    return existing


def export_convocatoria(output_dir: Path, election: int, raw_only: bool = False,
                        include_cera: bool = True) -> dict[str, Any]:
    mesas_path = find_raw_path(output_dir, f"mesas_{election}")
    catalog_path = output_dir / "processed" / f"mesas_{election}_catalog.csv"
    scope_path = output_dir / f"catalog_scope_{election}.json"
    if not mesas_path.exists() or not catalog_path.exists():
        raise ValueError("Se requieren raw y catálogo para verificar la cobertura; reanuda primero la descarga.")
    contexts = read_catalog_csv(catalog_path)
    expected = check_catalog(contexts, election)
    records = unique_records(mesas_path, context_key, election)
    if set(records) != expected:
        raise ValueError(f"Raw incompleto o ajeno al catálogo: {len(expected - set(records))} ausentes, "
                         f"{len(set(records) - expected)} ajenos. Reanuda antes de exportar.")
    scope = json.loads(scope_path.read_text()) if scope_path.exists() else None
    if scope and (scope.get("version") != 1 or scope.get("catalog_digest") != catalog_digest(contexts)
                  or scope.get("fconvocatoria") != election or scope.get("tconvocatoria") != 5):
        raise ValueError("El catálogo no coincide con sus metadatos; reanuda para actualizarlo.")
    cera_path = find_raw_path(output_dir, f"rausentes_{election}") if include_cera else None
    cera_records = unique_records(cera_path, cera_key, election) if cera_path and cera_path.exists() else {}
    for record in cera_records.values():
        ctx = record["context"]
        if (ctx.get("ambito") not in {"cautonoma", "provincia"}
                or (ctx["ambito"] == "provincia" and ctx.get("provincia_clave") is None)
                or (ctx["ambito"] == "cautonoma" and ctx.get("provincia_clave") is not None)):
            raise ValueError("El raw CERA contiene una identidad territorial inválida.")
    provinces = {ctx["provincia_clave"] for ctx in contexts}
    expected_provinces = set(scope.get("expected_provinces", [])) if scope else set()
    actual_cera = {r["context"].get("provincia_clave") for r in cera_records.values()
                   if r["context"].get("ambito") == "provincia"}
    if actual_cera - (set(scope["provinces"]) if scope and scope.get("provinces") else expected_provinces or provinces):
        raise ValueError("CERA fuera del ámbito del catálogo; usa una carpeta separada.")
    coverage_complete = bool(scope and scope.get("enumeration_complete") and scope.get("provinces") is None
                             and scope.get("limit_mesas") is None and len(expected_provinces) == 8
                             and provinces == expected_provinces and actual_cera == expected_provinces)
    suffix = "completo" if coverage_complete else "parcial"
    complete_path = output_dir / "processed" / f"andalucia_{election}_{suffix}.csv"
    incidents_path = output_dir / "processed" / f"mesas_{election}_incidencias.csv"
    quality_path = output_dir / "processed" / f"calidad_{election}.csv"
    incident_rows = write_mesa_incidents_csv(mesas_path, incidents_path)
    quality_counts = {}
    with quality_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["tipo_registro", "clave", "estado_descarga", "estado_calidad", "incidencias_calidad"])
        writer.writeheader()
        for kind, items in (("mesa", records), ("cera", cera_records)):
            for key, record in items.items():
                quality = assess_record(record)
                state = quality["estado_calidad"]
                quality_counts[state] = quality_counts.get(state, 0) + 1
                if state != "ok":
                    writer.writerow({"tipo_registro": kind, "clave": json.dumps(key),
                                     "estado_descarga": record.get("estado_descarga", "ok"), **quality})
    files = {"raw_ndjson": str(mesas_path), "catalog_csv": str(catalog_path),
             "incidents_csv": str(incidents_path), "quality_csv": str(quality_path)}
    counts = {"mesas": len(records), "download_statuses": count_download_statuses(mesas_path),
              "incidents": incident_rows, "quality_statuses": quality_counts}
    for name in ("long", "wide"):
        path = output_dir / "processed" / f"mesas_{election}_{name}.csv"
        counts[f"{name}_rows"] = None if raw_only else (write_long_csv if name == "long" else write_wide_csv)(mesas_path, path)
        files[f"{name}_csv"] = None if raw_only else str(path)
    counts["complete_rows"] = None if raw_only else write_complete_csv(
        mesas_path, cera_path if cera_records else None, complete_path)
    files["complete_csv"] = None if raw_only else str(complete_path)
    # Remove stale derived files with a misleading coverage suffix.
    for name in ("completo", "parcial"):
        stale = output_dir / "processed" / f"andalucia_{election}_{name}.csv"
        if raw_only or stale != complete_path:
            stale.unlink(missing_ok=True)
    manifest_path = output_dir / f"manifest_{election}.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    manifest.update({"source": {"home_page": "https://resultadoseleccionesandalucia.es/", "api_base": BASE_URL},
                     "generated_at": now_utc(), "tconvocatoria": 5, "fconvocatoria": election,
                     "scope": scope, "coverage_complete": coverage_complete,
                     "include_cera": include_cera,
                     "data_complete": coverage_complete and quality_counts.get("incompleto", 0) == 0,
                     "quality_ok": quality_counts.get("incompleto", 0) + quality_counts.get("inconsistente", 0) == 0,
                     "counts": counts, "files": files})
    write_json(manifest_path, manifest)
    return {"complete_rows": counts["complete_rows"], "complete_csv": files["complete_csv"],
            "incident_rows": incident_rows, "incidents_csv": str(incidents_path),
            "coverage_complete": coverage_complete, "download_statuses": counts["download_statuses"]}


def download_convocatoria(client: SielClient, fconvocatoria: int, output_dir: Path,
                         workers: int, province_filter: set[int] | None, limit: int | None,
                         raw_only: bool, overwrite: bool, resume: bool,
                         retry_failed: bool = False, compress_raw: bool = False,
                         include_cera: bool = True, defer_export: bool = False) -> None:
    raw_path = find_raw_path(output_dir, f"mesas_{fconvocatoria}", compress_raw)
    catalog_path = output_dir / "processed" / f"mesas_{fconvocatoria}_catalog.csv"
    scope_path = output_dir / f"catalog_scope_{fconvocatoria}.json"
    if raw_path.exists() and not overwrite and not resume:
        raise ValueError(f"{raw_path} ya existe. Usa --resume o --overwrite.")
    requested = catalog_scope(fconvocatoria, province_filter, limit)
    saved = json.loads(scope_path.read_text()) if scope_path.exists() else {}
    reusable = resume and catalog_path.exists() and saved.get("enumeration_complete") and all(
        saved.get(k) == value for k, value in requested.items())
    contexts = read_catalog_csv(catalog_path) if reusable else None
    if contexts is not None and saved.get("catalog_digest") != catalog_digest(contexts):
        contexts = None
    if contexts is None:
        print(f"[{fconvocatoria}] enumerando el ámbito solicitado", file=sys.stderr)
        contexts = sort_mesa_contexts(list(iter_mesa_contexts(client, fconvocatoria, province_filter, limit, workers)))
        check_catalog(contexts, fconvocatoria)
        # Validate existing identities before changing the catalog or scope.
        existing = unique_records(raw_path, context_key, fconvocatoria) if resume else {}
        if set(existing) - {context_key(ctx) for ctx in contexts}:
            raise ValueError("El raw contiene mesas fuera del ámbito solicitado; usa otra carpeta.")
        provinces = client.opciones("provincia", {"cautonoma": 1})
        write_catalog_csv(catalog_path, contexts)
        write_json(scope_path, {**requested, "enumeration_complete": True,
                               "expected_provinces": sorted(int(p["clave"]) for p in provinces),
                               "catalog_digest": catalog_digest(contexts), "created_at": now_utc()})
    check_catalog(contexts, fconvocatoria)
    update_raw(client, contexts, raw_path, fconvocatoria, context_key, download_mesa,
               unavailable_mesa_record, workers, resume, overwrite, retry_failed)
    if not defer_export:
        export_convocatoria(output_dir, fconvocatoria, raw_only, include_cera)


def download_rausentes(client: SielClient, fconvocatoria: int, output_dir: Path,
                       province_filter: set[int] | None, raw_only: bool, overwrite: bool,
                       resume: bool = False, retry_failed: bool = False,
                       compress_raw: bool = False) -> dict[str, Any]:
    path = find_raw_path(output_dir, f"rausentes_{fconvocatoria}", compress_raw)
    if path.exists() and not overwrite and not resume:
        raise ValueError(f"{path} ya existe. Usa --resume o --overwrite.")
    contexts = list(iter_rausentes_contexts(client, fconvocatoria, province_filter))
    records = update_raw(client, contexts, path, fconvocatoria, cera_key,
                         download_rausentes_record, unavailable_rausentes_record,
                         1, resume, overwrite, retry_failed)
    files = {"raw_ndjson": str(path)}
    for name, writer in (("long", write_rausentes_long_csv), ("wide", write_rausentes_wide_csv)):
        target = output_dir / "processed" / f"rausentes_{fconvocatoria}_{name}.csv"
        if not raw_only:
            writer(path, target)
        files[f"{name}_csv"] = None if raw_only else str(target)
    statuses = count_download_statuses(path)
    return {"counts": {"agregados": len(records), "downloaded": statuses.get("ok", 0),
                       "failed": len(records) - statuses.get("ok", 0), "download_statuses": statuses},
            "files": files, "note": "CERA agregado para Andalucía y sus provincias."}


def build_complete_from_existing(output_dir: Path, fconvocatoria: int,
                                 include_cera: bool = True) -> dict[str, Any]:
    return export_convocatoria(output_dir, fconvocatoria, include_cera=include_cera)


def parse_convocatorias(values: list[str] | None) -> list[int]:
    if not values:
        return []
    parsed: list[int] = []
    for value in values:
        for part in value.split(","):
            part = part.strip()
            if part:
                parsed.append(int(part))
    return parsed


def main() -> int:
    parser = argparse.ArgumentParser(description="Descarga resultados de mesas desde la API SIEL.")
    parser.add_argument("--list-convocatorias", action="store_true", help="Muestra las convocatorias disponibles y termina.")
    parser.add_argument("--all", action="store_true", help="Selecciona todas las elecciones al Parlamento de Andalucía disponibles.")
    parser.add_argument("--check", action="store_true", help="Comprueba agregados y una mesa por provincia, sin descarga masiva.")
    parser.add_argument("--retry-failed", action="store_true", help="Con --resume, reintenta registros fallidos o incompletos.")
    parser.add_argument("--compress-raw", action="store_true", help="Comprime nuevos raw como NDJSON gzip.")
    parser.add_argument("--convocatoria", action="append", help="Convocatoria a descargar, por ejemplo 202206. Se puede repetir o separar por comas.")
    parser.add_argument("--output", default="data", help="Directorio de salida. Por defecto: data")
    parser.add_argument("--workers", type=int, default=6, help="Descargas concurrentes de mesas. Por defecto: 6")
    parser.add_argument("--timeout", type=float, default=30.0, help="Timeout por petición HTTP en segundos. Por defecto: 30")
    parser.add_argument("--retries", type=int, default=2, help="Reintentos por petición HTTP. Por defecto: 2")
    parser.add_argument("--province", action="append", type=int, help="Filtra por código de provincia INE, por ejemplo 4 o 41.")
    parser.add_argument("--limit-mesas", type=int, help="Límite de mesas para pruebas rápidas.")
    parser.add_argument("--raw-only", action="store_true", help="Solo escribe el NDJSON bruto, sin CSV derivados.")
    parser.add_argument("--skip-rausentes", action="store_true", help="No descarga CERA/residentes ausentes.")
    parser.add_argument("--rausentes-only", action="store_true", help="Descarga solo CERA/residentes ausentes.")
    parser.add_argument("--complete-only", action="store_true", help="Genera solo el CSV completo desde raw ya descargado.")
    parser.add_argument("--resume", action="store_true", help="Reanuda una descarga parcial de mesas ya existente.")
    parser.add_argument("--overwrite", action="store_true", help="Sobrescribe una descarga existente.")
    tls = parser.add_mutually_exclusive_group()
    tls.add_argument("--verify-tls", dest="verify_tls", action="store_true", default=True, help="Verifica certificados TLS (predeterminado).")
    tls.add_argument("--insecure", dest="verify_tls", action="store_false", help="Desactiva explícitamente la verificación de certificados TLS.")
    args = parser.parse_args()

    if args.rausentes_only and args.skip_rausentes:
        parser.error("--rausentes-only no se puede combinar con --skip-rausentes")
    if args.complete_only and (args.rausentes_only or args.raw_only):
        parser.error("--complete-only no se puede combinar con --rausentes-only ni --raw-only")
    if args.resume and args.overwrite:
        parser.error("--resume y --overwrite son mutuamente excluyentes")

    if args.all and args.convocatoria:
        parser.error("--all y --convocatoria son mutuamente excluyentes")
    if args.retry_failed and not args.resume:
        parser.error("--retry-failed requiere --resume")
    if args.workers < 1 or args.timeout <= 0 or args.retries < 0 or (args.limit_mesas is not None and args.limit_mesas < 1):
        parser.error("workers, timeout y limit-mesas deben ser positivos; retries no puede ser negativo")
    if args.complete_only and (args.province or args.limit_mesas or args.resume or args.overwrite or args.retry_failed):
        parser.error("--complete-only utiliza el ámbito guardado; no admite filtros ni opciones de descarga")
    if args.check and any((args.raw_only, args.rausentes_only, args.complete_only, args.resume,
                           args.overwrite, args.retry_failed, args.limit_mesas, args.compress_raw)):
        parser.error("--check no se puede combinar con opciones de descarga o reconstrucción")

    client = SielClient(verify_tls=args.verify_tls, timeout=args.timeout, retries=args.retries, pool_size=max(args.workers, 32))
    output_dir = Path(args.output)
    if not output_dir.is_absolute():
        output_dir = PROJECT_ROOT / output_dir

    try:
        if args.list_convocatorias:
            list_convocatorias(client)
            return 0
        if args.all or (args.check and not args.convocatoria):
            convocatorias = [int(item["clave"]) for item in client.opciones("fconvocatoria", {"tconvocatoria": 5})]
        else:
            convocatorias = list(dict.fromkeys(parse_convocatorias(args.convocatoria)))
        if not convocatorias:
            parser.error("usa --all, --convocatoria, --check o --list-convocatorias")
        province_filter = set(args.province) if args.province else None
        if province_filter and not province_filter <= {4, 11, 14, 18, 21, 23, 29, 41}:
            parser.error("--province debe ser un código INE de una provincia de Andalucía")
        if args.check:
            from check_siel import run_check
            return run_check(client, convocatorias, output_dir, province_filter, not args.skip_rausentes)
        if args.complete_only:
            for election in convocatorias:
                result = build_complete_from_existing(output_dir, election, not args.skip_rausentes)
                print(f"[{election}] CSV generado: {result['complete_csv']} (cobertura completa: {result['coverage_complete']})", file=sys.stderr)
            return 0
        save_source_metadata(client, output_dir)
        for election in convocatorias:
            partidos = client.opciones("partido/cautonoma", {"cautonoma": 1, "tconvocatoria": 5, "fconvocatoria": election})
            write_json(output_dir / "raw" / "opciones" / f"partidos_{election}.json", partidos)
            if not args.rausentes_only:
                download_convocatoria(client, election, output_dir, args.workers, province_filter,
                                      args.limit_mesas, args.raw_only, args.overwrite, args.resume,
                                      args.retry_failed, args.compress_raw, not args.skip_rausentes, defer_export=True)
            cera_manifest = None
            if not args.skip_rausentes:
                cera_manifest = download_rausentes(client, election, output_dir, province_filter,
                                                   args.raw_only, args.overwrite, args.resume,
                                                   args.retry_failed, args.compress_raw)
            if args.rausentes_only:
                write_json(output_dir / f"manifest_{election}_rausentes.json",
                           {"fconvocatoria": election, "fetched_at": now_utc(), "rausentes": cera_manifest})
            if find_raw_path(output_dir, f"mesas_{election}").exists():
                result = export_convocatoria(output_dir, election, args.raw_only, not args.skip_rausentes)
                manifest_path = output_dir / f"manifest_{election}.json"
                manifest = json.loads(manifest_path.read_text())
                manifest["last_download_run_at"] = now_utc()
                if cera_manifest:
                    manifest["rausentes"] = cera_manifest
                else:
                    manifest.pop("rausentes", None)
                write_json(manifest_path, manifest)
                print(f"[{election}] listo: {manifest_path}; cobertura completa: {result['coverage_complete']}", file=sys.stderr)
    except (SielApiError, ValueError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
