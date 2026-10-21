# Publicar una edición de datos

Los datasets se alojan en **GitHub Releases**, separados del historial Git.
GitHub Pages sirve la página estática desde `docs/`.

La edición `datos-2026-10-21-v1` contiene 13 ZIP individuales, un ZIP conjunto,
guía, calidad, procedencia, catálogo y SHA-256. Excluye referendos, SQLite,
configuración de servidores y borradores de correspondencia.

## Reproducir los paquetes

Desde una copia verificada con el manifiesto y la auditoría:

```sh
python3 scripts/package_datasets.py \
  --snapshot ./parlamento_20261021 \
  --output ./publicacion-datos-2026-10-21-v1 \
  --version datos-2026-10-21-v1
```

El programa comprueba hashes del origen, copia los gzip sin modificarlos, retira
la ruta local de SQLite de los metadatos, crea los paquetes y verifica sus CRC.
No sobrescribe una carpeta existente. `upload-manifest.json` es un auxiliar de
subida, no un dataset. Adjunte a una release los archivos de esa lista y compruebe
sus tamaños y SHA-256 antes de publicar. No incorpore los paquetes al historial Git.

Copie `catalogo.json`, `LEEME.md`, `CALIDAD.md` y `REUTILIZACION.md` a `docs/` y ejecute:

```sh
python3 scripts/build_download_page.py
```

Configure GitHub Pages con `main`, carpeta `/docs`. Los enlaces apuntan a una
versión concreta de los datos. Para correcciones, cree una edición con un
identificador nuevo, conserve las anteriores, documente las diferencias y
regenere el catálogo y la página. Cambiar la versión no subsana las incidencias.
