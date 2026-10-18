src/sistema_electoral_malaga.py
"""
SISTEMA INTEGRAL DE METODOLOGÍA ELECTORAL Y ANÁLISIS CENSAL
Provincia: Málaga (Elecciones Autonómicas 2026 vs. Generales 2023 / Autonómicas 2022)
Sujeto a: LOREG, LO 1/2025, Ley 52/1997, Ley 12/1989 y RGPD
"""

import pandas as pd
import numpy as np

# ==============================================================================
# 1. INVENTARIO DE FUENTES Y REGISTROS ELECTORALES CONSOLIDADOS
# ==============================================================================

DATOS_PROVINCIALES = {
    "censo_electoral": 1240000,
    "autonomicas_2022": {
        "votos_aa": 24388,
        "porcentaje_aa": 3.76,
        "capital_votos_aa": 11327,
        "capital_porcentaje_aa": 4.61,
        "escanos_aa": 0
    },
    "generales_2023": {
        "participacion_pct": 67.20,
        "votos_sumar": 95662,
        "porcentaje_sumar": 12.20,
        "votos_psoe": 236935,
        "porcentaje_psoe": 30.28,
        "capital_votos_sumar": 39104,
        "capital_porcentaje_sumar": 13.44,
        "capital_votos_psoe": 89594,
        "capital_porcentaje_psoe": 30.79,
        "candidatura_aa_malaga": False  # AA no concurrió en Málaga (solo Cádiz)
    },
    "autonomicas_2026": {
        "participacion_pct": 62.40,
        "votos_aa": 69100,
        "porcentaje_aa": 9.33,
        "escanos_aa": 1,
        "diputado": "Luis Rodrigo",
        "capital_votos_aa": 31300,
        "capital_porcentaje_aa": 11.20,
        "votos_pora": 44100,
        "porcentaje_pora": 5.95,
        "capital_votos_pora": 16941,
        "capital_porcentaje_pora": 6.06,
        "capital_votos_psoe": 55261,
        "capital_porcentaje_psoe": 19.97
    }
}

MUNICIPIOS_DESTACADOS = [
    {"municipio": "Alameda", "comarca": "Antequera", "votos_aa_2026": 365, "pct_aa_2026": 13.18, "votos_sumar_2023": 677, "pct_sumar_2023": 21.84, "censo_aprox": 4200},
    {"municipio": "Alpandeire", "comarca": "Serranía de Ronda", "votos_aa_2026": 15, "pct_aa_2026": 12.29, "votos_sumar_2023": 18, "pct_sumar_2023": 12.67, "censo_aprox": 220},
    {"municipio": "Monda", "comarca": "Sierra de las Nieves", "votos_aa_2026": 116, "pct_aa_2026": 11.24, "votos_sumar_2023": 239, "pct_sumar_2023": 21.05, "censo_aprox": 1900},
    {"municipio": "Cuevas de San Marcos", "comarca": "Antequera", "votos_aa_2026": 201, "pct_aa_2026": 10.74, "votos_sumar_2023": None, "pct_sumar_2023": None, "censo_aprox": 2900},
    {"municipio": "Arriate", "comarca": "Serranía de Ronda", "votos_aa_2026": 226, "pct_aa_2026": 9.96, "votos_sumar_2023": 731, "pct_sumar_2023": 31.29, "censo_aprox": 3300},
    {"municipio": "Mijas", "comarca": "Costa del Sol Occidental", "votos_aa_2026": 2955, "pct_aa_2026": 9.87, "votos_sumar_2023": None, "pct_sumar_2023": None, "censo_aprox": 62000},
    {"municipio": "Cútar", "comarca": "Axarquía", "votos_aa_2026": 21, "pct_aa_2026": 9.33, "votos_sumar_2023": None, "pct_sumar_2023": None, "censo_aprox": 450},
    {"municipio": "Benalmádena", "comarca": "Costa del Sol Occidental", "votos_aa_2026": 2534, "pct_aa_2026": 9.07, "votos_sumar_2023": None, "pct_sumar_2023": None, "censo_aprox": 48000},
    {"municipio": "Coín", "comarca": "Valle del Guadalhorce", "votos_aa_2026": 916, "pct_aa_2026": 9.07, "votos_sumar_2023": 1085, "pct_sumar_2023": 10.67, "censo_aprox": 17500},
    {"municipio": "Algatocín", "comarca": "Serranía de Ronda", "votos_aa_2026": 37, "pct_aa_2026": 9.00, "votos_sumar_2023": None, "pct_sumar_2023": None, "censo_aprox": 650},
    {"municipio": "Benarrabá", "comarca": "Serranía de Ronda", "votos_aa_2026": 23, "pct_aa_2026": 8.81, "votos_sumar_2023": 28, "pct_sumar_2023": 10.93, "censo_aprox": 420},
    {"municipio": "Benaoján", "comarca": "Serranía de Ronda", "votos_aa_2026": 61, "pct_aa_2026": 8.68, "votos_sumar_2023": None, "pct_sumar_2023": None, "censo_aprox": 1200},
    {"municipio": "Jimera de Líbar", "comarca": "Serranía de Ronda", "votos_aa_2026": 22, "pct_aa_2026": 8.66, "votos_sumar_2023": 18, "pct_sumar_2023": 6.66, "censo_aprox": 320},
    {"municipio": "Ojén", "comarca": "Sierra de las Nieves", "votos_aa_2026": 140, "pct_aa_2026": 8.66, "votos_sumar_2023": 177, "pct_sumar_2023": 10.84, "censo_aprox": 2800},
    {"municipio": "Cartajima", "comarca": "Serranía de Ronda", "votos_aa_2026": 6, "pct_aa_2026": 4.47, "votos_sumar_2023": None, "pct_sumar_2023": None, "censo_aprox": 210},
    {"municipio": "Igualeja", "comarca": "Serranía de Ronda", "votos_aa_2026": 17, "pct_aa_2026": 4.15, "votos_sumar_2023": None, "pct_sumar_2023": None, "censo_aprox": 680},
    {"municipio": "Jubrique", "comarca": "Serranía de Ronda", "votos_aa_2026": 11, "pct_aa_2026": 3.97, "votos_sumar_2023": None, "pct_sumar_2023": None, "censo_aprox": 510},
    {"municipio": "Júzcar", "comarca": "Serranía de Ronda", "votos_aa_2026": 4, "pct_aa_2026": 3.22, "votos_sumar_2023": None, "pct_sumar_2023": None, "censo_aprox": 200},
    {"municipio": "Benadalid", "comarca": "Serranía de Ronda", "votos_aa_2026": 4, "pct_aa_2026": 3.41, "votos_sumar_2023": None, "pct_sumar_2023": None, "censo_aprox": 190}
]

OBJETIVOS_COMARCALES = [
    {"comarca": "Comarca de Málaga (Capital)", "censo_aprox": 435000, "votos_aa_2026": 31300, "pct_aa_2026": 11.20, "meta_votos": 38500, "pct_recursos": 45},
    {"comarca": "Costa del Sol Occidental", "censo_aprox": 365000, "votos_aa_2026": 18500, "pct_aa_2026": 7.80, "meta_votos": 22000, "pct_recursos": 25},
    {"comarca": "Axarquía", "censo_aprox": 135000, "votos_aa_2026": 6200, "pct_aa_2026": 6.90, "meta_votos": 7500, "pct_recursos": 10},
    {"comarca": "Valle del Guadalhorce", "censo_aprox": 105000, "votos_aa_2026": 5800, "pct_aa_2026": 7.90, "meta_votos": 6800, "pct_recursos": 8},
    {"comarca": "Comarca de Antequera / Nororma", "censo_aprox": 80000, "votos_aa_2026": 3800, "pct_aa_2026": 7.20, "meta_votos": 4600, "pct_recursos": 6},
    {"comarca": "Serranía de Ronda", "censo_aprox": 42000, "votos_aa_2026": 2600, "pct_aa_2026": 8.40, "meta_votos": 3400, "pct_recursos": 4},
    {"comarca": "Sierra de las Nieves", "censo_aprox": 18000, "votos_aa_2026": 900, "pct_aa_2026": 8.10, "meta_votos": 1200, "pct_recursos": 2}
]

# ==============================================================================
# 2. ALGORITMO D'HONDT Y COSTES DE ESCAÑO SEGÚN PARTICIPACIÓN
# ==============================================================================

def calcular_dhondt(votos_partidos: dict, num_escanos: int) -> dict:
    """
    Calcula el reparto de escaños aplicando la Ley D'Hondt oficial (LOREG Art. 163).
    """
    cocientes = []
    for partido, votos in votos_partidos.items():
        for d in range(1, num_escanos + 1):
            cocientes.append({
                "partido": partido,
                "divisor": d,
                "cociente": votos / d,
                "escanos_previos": d - 1
            })
    df_cocientes = pd.DataFrame(cocientes)
    df_cocientes = df_cocientes.sort_values(by="cociente", ascending=False).reset_index(drop=True)
    df_cocientes["escaño_asignado"] = df_cocientes.index + 1
    
    escanos_finales = df_cocientes.head(num_escanos)
    resumen = escanos_finales["partido"].value_counts().to_dict()
    for p in votos_partidos:
        if p not in resumen:
            resumen[p] = 0
            
    corte_ultimo_escaño = df_cocientes.iloc[num_escanos - 1]["cociente"]
    partido_ultimo_escaño = df_cocientes.iloc[num_escanos - 1]["partido"]
    corte_primer_excluido = df_cocientes.iloc[num_escanos]["cociente"]
    partido_primer_excluido = df_cocientes.iloc[num_escanos]["partido"]
    
    return {
        "distribucion": resumen,
        "ultimo_escaño": {
            "puesto": num_escanos,
            "partido": partido_ultimo_escaño,
            "cociente": corte_ultimo_escaño
        },
        "primer_excluido": {
            "puesto": num_escanos + 1,
            "partido": partido_primer_excluido,
            "cociente": corte_primer_excluido
        },
        "tabla_cocientes": df_cocientes.head(num_escanos + 3)
    }

def simular_escenarios_escaño(censo: int, escenarios_part: list) -> pd.DataFrame:
    """
    Modela los 3 escenarios de participación para Generales (11 escaños) y Autonómicas (17 escaños).
    """
    resultados_simulacion = []
    
    for part in escenarios_part:
        votantes = censo * (part / 100.0)
        votos_validos = votantes * 0.985  # Deducido 1.5% nulos
        
        # --- Escenario Generales (11 escaños)
        votos_gen = {
            "PP": votos_validos * 0.380,
            "PSOE": votos_validos * 0.295,
            "VOX": votos_validos * 0.150,
            "SUMAR": votos_validos * 0.090
        }
        res_gen = calcular_dhondt(votos_gen, 11)
        votos_necesarios_gen = res_gen["ultimo_escaño"]["cociente"] + 1
        pct_necesario_gen = (votos_necesarios_gen / votos_validos) * 100
        
        # --- Escenario Autonómicas (17 escaños)
        votos_aut = {
            "PP": votos_validos * 0.4407,
            "PSOE-A": votos_validos * 0.1997,
            "VOX": votos_validos * 0.1350,
            "AA": votos_validos * 0.0933,
            "PorA": votos_validos * 0.0595
        }
        res_aut = calcular_dhondt(votos_aut, 17)
        corte_17 = res_aut["ultimo_escaño"]["cociente"]
        votos_necesarios_aut_1 = corte_17 + 1
        pct_necesario_aut_1 = (votos_necesarios_aut_1 / votos_validos) * 100
        votos_necesarios_aut_2 = (corte_17 * 2) + 1
        pct_necesario_aut_2 = (votos_necesarios_aut_2 / votos_validos) * 100
        
        resultados_simulacion.append({
            "participacion_pct": part,
            "votos_validos": int(votos_validos),
            # Generales
            "gen_votos_corte_escaño_11": int(votos_necesarios_gen),
            "gen_pct_corte_escaño_11": round(pct_necesario_gen, 2),
            "gen_rival_directo": f"{res_gen['ultimo_escaño']['partido']} (cociente: {int(res_gen['ultimo_escaño']['cociente'])})",
            # Autonómicas
            "aut_votos_corte_1er_escaño": int(votos_necesarios_aut_1),
            "aut_pct_corte_1er_escaño": round(pct_necesario_aut_1, 2),
            "aut_votos_corte_2do_escaño": int(votos_necesarios_aut_2),
            "aut_pct_corte_2do_escaño": round(pct_necesario_aut_2, 2),
            "aut_rival_escaño_17": f"{res_aut['ultimo_escaño']['partido']} (cociente: {int(corte_17)})"
        })
        
    return pd.DataFrame(resultados_simulacion)

# ==============================================================================
# 3. MODELO DE TRANSFERENCIAS Y VULNERABILIDAD AL VOTO ÚTIL
# ==============================================================================

def modelar_transferencias_y_riesgo(votos_totales_aa: int = 69100):
    """
    Descompone las fuentes nutricias del voto de AA e implementa las tasas de fuga en Generales.
    """
    fuentes = [
        {"origen": "Sumar 2023 / PorA", "peso_pct": 41.2, "votos": int(votos_totales_aa * 0.412), "riesgo_min_pct": 30.0, "riesgo_max_pct": 40.0, "destino": "Confluencia Estatal / Voto Útil"},
        {"origen": "Núcleo Fiel AA 2022", "peso_pct": 30.1, "votos": int(votos_totales_aa * 0.301), "riesgo_min_pct": 5.0, "riesgo_max_pct": 10.0, "destino": "Fidelidad Andalucista"},
        {"origen": "Descontento PSOE", "peso_pct": 16.0, "votos": int(votos_totales_aa * 0.160), "riesgo_min_pct": 65.0, "riesgo_max_pct": 75.0, "destino": "Retorno Táctico al PSOE"},
        {"origen": "Abstención / Juventud", "peso_pct": 12.7, "votos": int(votos_totales_aa * 0.127), "riesgo_min_pct": 35.0, "riesgo_max_pct": 45.0, "destino": "Re-abstención"}
    ]
    df_fuentes = pd.DataFrame(fuentes)
    df_fuentes["votos_riesgo_min"] = (df_fuentes["votos"] * (df_fuentes["riesgo_min_pct"] / 100.0)).astype(int)
    df_fuentes["votos_riesgo_max"] = (df_fuentes["votos"] * (df_fuentes["riesgo_max_pct"] / 100.0)).astype(int)
    
    total_riesgo_min = df_fuentes["votos_riesgo_min"].sum()
    total_riesgo_max = df_fuentes["votos_riesgo_max"].sum()
    
    resumen_riesgo = {
        "votos_totales_aa_2026": votos_totales_aa,
        "fuga_minima_estimada": total_riesgo_min,
        "fuga_maxima_estimada": total_riesgo_max,
        "pct_fuga_minimo": round((total_riesgo_min / votos_totales_aa) * 100, 2),
        "pct_fuga_maximo": round((total_riesgo_max / votos_totales_aa) * 100, 2),
        "suelo_retenido_min": votos_totales_aa - total_riesgo_max,
        "suelo_retenido_max": votos_totales_aa - total_riesgo_min
    }
    
    return df_fuentes, resumen_riesgo

# ==============================================================================
# 4. AUDITORÍA DE PRIVACIDAD Y REGLA DE K-ANONIMATO (LEY 12/1989)
# ==============================================================================

def auditar_secreto_estadistico(lista_municipios: list, umbral_k: int = 500) -> pd.DataFrame:
    """
    Verifica si una unidad territorial cumple k >= 500 para permitir cruces sociodemográficos.
    """
    auditoria = []
    for m in lista_municipios:
        censo = m["censo_aprox"]
        es_seguro = censo >= umbral_k
        accion_requerida = "Tratamiento individual permitido" if es_seguro else "BLOQUEO: Agrupación subcomarcal obligatoria"
        auditoria.append({
            "municipio": m["municipio"],
            "comarca": m["comarca"],
            "censo_aprox": censo,
            "votos_aa": m["votos_aa_2026"],
            "cumple_k_anonimato": es_seguro,
            "dictamen_juridico": accion_requerida
        })
    return pd.DataFrame(auditoria)

# ==============================================================================
# 5. EJECUCIÓN PRINCIPAL Y SALIDAS ANALÍTICAS
# ==============================================================================

if __name__ == "__main__":
    print("================================================================================")
    print("REPORTE METODOLÓGICO Y MATRICIAL: MÁLAGA (ADELANTE ANDALUCÍA)")
    print("================================================================ calculated\n")
    
    # 1. Simulación D'Hondt
    censo_ref = DATOS_PROVINCIALES["censo_electoral"]
    escenarios = [60.0, 67.0, 72.0]
    df_escenarios = simular_escenarios_escaño(censo_ref, escenarios)
    
    print("--- 1. ANÁLISIS DE COSTES DE ESCAÑO (SISTEMA D'HONDT) ---")
    print(df_escenarios.to_string(index=False))
    print("\n")
    
    # 2. Descomposición de transferencias
    df_transf, resumen_riesgo = modelar_transferencias_y_riesgo(DATOS_PROVINCIALES["autonomicas_2026"]["votos_aa"])
    print("--- 2. TRANSFERENCIAS DE VOTO Y FUENTES NUTRICIAS ---")
    print(df_transf[["origen", "peso_pct", "votos", "riesgo_min_pct", "riesgo_max_pct", "destino"]].to_string(index=False))
    print("\nBalance de Vulnerabilidad en Elecciones Generales:")
    print(f" - Fuga estimada por voto útil: {resumen_riesgo['fuga_minima_estimada']:,} a {resumen_riesgo['fuga_maxima_estimada']:,} votos ({resumen_riesgo['pct_fuga_minimo']}% - {resumen_riesgo['pct_fuga_maximo']}%)")
    print(f" - Suelo fiel retenido: {resumen_riesgo['suelo_retenido_min']:,} a {resumen_riesgo['suelo_retenido_max']:,} votos\n")
    
    # 3. Plan Comarcal
    df_comarcas = pd.DataFrame(OBJETIVOS_COMARCALES)
    df_comarcas["crecimiento_necesario"] = df_comarcas["meta_votos"] - df_comarcas["votos_aa_2026"]
    print("--- 3. REPARTO DE OBJETIVOS ESTRATÉGICOS POR COMARCA (META: 84.000 VOTOS) ---")
    print(df_comarcas[["comarca", "censo_aprox", "votos_aa_2026", "meta_votos", "crecimiento_necesario", "pct_recursos"]].to_string(index=False))
    print("\n")
    
    # 4. Auditoría de Secreto Estadístico
    df_seguridad = auditar_secreto_estadistico(MUNICIPIOS_DESTACADOS)
    inseguros = df_seguridad[~df_seguridad["cumple_k_anonimato"]]
    print("--- 4. AUDITORÍA DE SECRETO ESTADÍSTICO (LEY 12/1989: FILTRO k >= 500) ---")
    print(f"Municipios con riesgo de reidentificación detectados: {len(inseguros)}")
    print(inseguros[["municipio", "comarca", "censo_aprox", "votos_aa", "dictamen_juridico"]].to_string(index=False))
    print("\n================================================================================")

