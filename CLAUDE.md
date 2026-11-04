# alerta-camaras-datos

Base pública de cámaras de velocidad y de semáforo de la Argentina. La consume la app Android
«Alerta de cámaras» (se baja el JSON desde este repo). Repo **público**: nada de secretos ni datos personales.

## Estructura
- `publicar/`: lo que baja la app → `camaras.json`, `semaforos.json`, `version.json`. Formato en `README.md`.
- `datos/`: fuentes crudas y últimas versiones buenas (`datos/fuentes/`), crudos de OpenStreetMap.
- `herramientas/`: scripts Python (`actualizar_base.py` arma todo; `sentido.py` calcula el sentido; `cruce.py`,
  `completar_velocidades.py`, `semaforos.py` auxiliares).
- `.github/workflows/actualizar.yml`: corre cada lunes 8:00 UTC y publica con el bot de GitHub.

## Comandos
- Armar la base completa: `python -I herramientas/actualizar_base.py` (tarda; baja fuentes de internet).
- Instalar dependencias: no hay `requirements.txt`; los scripts usan la librería estándar (a confirmar).
- Correr la acción a mano: pestaña Actions → «Actualizar cámaras» → Run workflow.

## Cómo verificar un cambio
- Correr `actualizar_base.py` y revisar `publicar/version.json` (cantidades y estado de cada fuente).
- Comparar contra la base publicada: si la nueva tiene menos del 85 %, el script no publica (no desactivar ese corte).
- No hay tests automáticos: a confirmar; se propone agregar uno para `sentido.py`.

## Reglas que no se rompen
- Formatos de `camaras.json` / `semaforos.json` son contrato con la app: no cambiar el orden de columnas sin
  versionar la app.
- `sentido` solo cuando es seguro; ante duda, `-1`.
- Si una fuente falla, se usa su última versión buena; nunca se publica una base vacía.
- Licencias: OSM (ODbL, la base derivada se comparte igual), BA Data (CC BY 2.5 AR). Mantener los créditos del README.
- Los commits de los lunes los hace el bot: no pisar con cambios locales sin hacer `git pull` antes.
