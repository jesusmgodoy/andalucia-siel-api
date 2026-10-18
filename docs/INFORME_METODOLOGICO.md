docs/INFORME_METODOLOGICO.md add electoral methodology report and decision trees
# Sistema Integral de Metodología Electoral y Análisis Censal (Málaga)

## 1. Árboles Estructurales y de Decisión Metodológica

### Árbol 1: Estructura Orgánica y Gobernanza Institucional (Roles e Independencia)
* **Dirección Operativa del Proyecto**
  * **Jefe/a de Equipo**: Priorización de sprints, asignación de cargas y resolución de cuellos de botella técnicos.
  * **Coordinador/a de Proyecto**: Gestión de cronograma, riesgos y dependencias.
* **Fiscalización Jurídico-Institucional (Independencia y Veto Legal Bloqueante)**
  * **Secretario/a de la JEP (Letrado/a de la Administración de Justicia - LAJ)**:
    * Fe pública electoral y custodia registral (LOREG art. 10 y LO 1/2025).
    * Certificación vinculante de correspondencia territorial entre mesas y secciones censales.
    * Enlace permanente interelectoral.
  * **Abogado/a del Estado**:
    * Asesoramiento preventivo y representación del Estado (Ley 52/1997).
    * Enlace técnico-jurídico con la Junta Electoral Central (JEC).
    * Control de legalidad en acceso a microdatos censales (LOREG art. 41).
* **Equipo de Métodos y Datos**
  * **Ingeniero/a de Datos**: Arquitectura relacional SQL/PostGIS, Docker, Airflow y pipelines reproducibles.
  * **Especialista GIS / Geógrafo/a**: Armonización topológica, interpolación areal y análisis geoespacial ($G_i^*$).
  * **Data Scientist / Estadístico/a**: Inferencia ecológica bayesiana, modelado MCMC y proyecciones electorales.
  * **Demógrafo/a Censal**: Estructura de hogares, flujos migratorios e indicadores de vulnerabilidad.
  * **Sociólogo/a Territorial**: Validación contextual y contraste cualitativo comunitario.
* **Calidad, Auditoría y Privacidad**
  * **QA / Reproducibilidad**: Tests de integración, congelamiento de versiones en Git y reproducibilidad de código.
  * **Auditor/a de Sesgos**: Detección de sesgos de no respuesta, control de varianza censal y paridad algorítmica.
  * **Especialista Legal / Privacidad**: Evaluación de Impacto (EIPD), calibración de algoritmos de $k$-anonimato ($n \ge 500$) y RGPD/LOPDGDD.
* **Comunicación y Difusión**
  * **Comunicación / Visualización**: Interfaces analíticas, cuadros de mando interactivos y notas técnicas.

### Árbol 2: Árbol de Decisión y Priorización Operativa (Escala de 6 Niveles)
* **Nivel 1: Cumplimiento Legal y Privacidad (Condición Bloqueante Absoluta)**
  * ¿Se respeta el secreto estadístico (Ley 12/1989) y $k \ge 500$?
    * **No**: Paralización inmediata del pipeline. Agregación obligatoria a nivel subcomarcal.
    * **Sí**: Proseguir a la validación de correspondencia mesas-secciones.
  * ¿Existe certificación fehaciente del Secretario/a de la JEP (LAJ)?
    * **No**: Veto bloqueante. Detener modelización.
    * **Sí**: Autorizar paso a Fase 1.
* **Nivel 2: Disponibilidad y Calidad de Fuentes**
  * Control de integridad en bases escrutadas (BOE/BOJA) y completitud de metadatos del INE.
* **Nivel 3: Dependencias Técnicas**
  * Despliegue de esquemas relacionales e interpolación areal catastral previa a la modelización.
* **Nivel 4: Impacto Analítico en Decisiones**
  * Estimación de parámetros bayesianos y localización de bolsas de voto latente.
* **Nivel 5: Esfuerzo y Plazo de Entrega**
  * Optimización de horas técnicas y ajuste a los sprints quincenales.
* **Nivel 6: Mitigación de Riesgos Reputacionales o de Impugnación**
  * Eliminación de imputaciones causales falaces en la divulgación de resultados.

### Árbol 3: Descomposición de Flujos del Voto de Adelante Andalucía (Mayo 2026) y Riesgo de Voto Útil
* **Voto Adelante Andalucía Mayo 2026: 9,33% provincial (~69.100 votos)**
  * **Aporte Sumar / Por Andalucía 2023**: 41,2% (28.000 – 29.500 votos)
    * *Riesgo en Generales*: Medio-Alto (30% – 40% vulnerable; 8.600 – 11.500 votos en peligro por confluencia o voto útil).
  * **Núcleo Fiel Adelante Andalucía 2022**: 30,1% (20.500 – 21.000 votos)
    * *Riesgo en Generales*: Muy Bajo (<10% vulnerable; base andalucista de izquierdas blindada).
  * **Descontento y Fuga del PSOE 2023**: 16,0% (10.500 – 11.500 votos)
    * *Riesgo en Generales*: Muy Alto (65% – 75% vulnerable; 7.200 – 8.200 votos en riesgo de retorno táctico anti-PP/Vox).
  * **Abstención y Nuevos Votantes (Juventud)**: 12,7% (8.500 – 9.500 votos)
    * *Riesgo en Generales*: Medio (35% – 45% vulnerable; 3.100 – 4.000 votos con riesgo de re-abstención).
* **Balance de Vulnerabilidad en Elecciones Generales:**
  * **Suelo Retenido Seguro**: ~65,7% – 72,5% (45.400 – 50.200 votos; ~6,1% – 6,7% provincial).
  * **Fuga Total Estimada por Voto Útil / Polarización**: 27,5% – 34,3% (18.900 – 23.700 votos).

### Árbol 4: Árbol de Decisión Territorial y Asignación Comarcal (Meta: 84.000 votos)
* **Comarca de Málaga Capital (Meta: 38.500 votos / +7.200)**
  * *Distritos Populares de Alta Densidad* (Carretera de Cádiz, Cruz de Humilladero, Palma-Palmilla): Reducción de la abstención mediante presencia de calle centrada en alquiler y carestía.
  * *Distritos Jóvenes y Expansión* (Puerto de la Torre, Teatinos, Churriana): Consolidación de cuotas superiores al 12%.
  * *Distrito Málaga Este*: Desinversión operativa total (techo conservador >60% PP; AA <4,5%).
* **Costa del Sol Occidental (Meta: 22.000 votos / +3.500)**
  * *Grandes Bastiones Urbanos* (Mijas, Benalmádena): Reforzar penetración superior al 9%.
  * *Bolsas de Abstención Laboral* (Marbella, Fuengirola, Estepona): Campaña dirigida a trabajadores de hostelería y servicios.
* **Axarquía (Meta: 7.500 votos / +1.300)**
  * *Franja Litoral* (Vélez-Málaga, Rincón de la Victoria): Movilización urbana.
  * *Interior Comarcal* (Cútar 9,33%, Frigiliana 8,18%): Preservación del voto andalucista agrario.
* **Valle del Guadalhorce (Meta: 6.800 votos / +1.000)**
  * *Cabeceras* (Coín 9,07%, Álora 7,76%): Movilización en torno a infraestructuras (Cercanías C-2) y gestión del agua.
* **Comarca de Antequera / Nororma (Meta: 4.600 votos / +800)**
  * *Bastión Principal* (Alameda 13,18%, Cuevas de San Marcos 10,74%): Extensión del modelo hacia Campillos, Mollina y Archidona.
* **Serranía de Ronda (Meta: 3.400 votos / +800)**
  * *Enclaves de Montaña* (Arriate 9,96%, Alpandeire 12,29%, Algatocín 9,00%): Mantenimiento de redes locales; respeto a enclaves de IU (pacto tácito de no fricción).
* **Sierra de las Nieves (Meta: 1.200 votos / +300)**
  * *Núcleos Clave* (Monda 11,24%, Ojén 8,66%): Conexión entre reivindicación rural y periferia costera.

---

## 2. Síntesis de Resultados Generados

1. **Coste del Escaño en Elecciones Generales (11 escaños):**
   * *Al 60% de participación*: se requieren ~55.000 votos (7,50%), disputándose directamente contra el segundo diputado de Vox (cociente en 54.963).
   * *Al 67% de participación*: se requieren ~61.500 votos (7,50%), compitiendo frente al segundo de Vox (cociente en 61.375) y el quinto del PP (62.194).
   * *Al 72% de participación*: se requieren ~66.000 votos (7,51%), disputándose contra el segundo de Vox (cociente en 65.956) y el cuarto del PSOE (64.856).

2. **Coste del Escaño en Elecciones Autonómicas (17 escaños):**
   * La retención del primer diputado oscila entre 35.900 votos (al 60%) y 43.100 votos (al 72%), umbral ampliamente cubierto por los 69.100 votos actuales.
   * La conquista del segundo diputado requiere alcanzar entre 71.800 votos (al 60%) y 86.200 votos (al 72%), arrebatándole el escaño 17 al Partido Popular.

3. **Filtro de Privacidad Activado:**
   * Pequeños municipios de la Serranía de Ronda y Axarquía (Alpandeire, Cútar, Benarrabá, Jimera de Líbar, Cartajima, Júzcar, Benadalid) quedan formalmente bloqueados para cruces directos con microdatos de renta y demografía, exigiéndose su reporte consolidado a nivel subcomarcal.
