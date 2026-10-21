# Cámaras de velocidad y de semáforo: AMBA y rutas de Buenos Aires

Base de cámaras de control (fotomultas) del AMBA y de las rutas que salen de Buenos Aires. La usa una app
personal que avisa al acercarse a una cámara. Se arma sólo con datos públicos y se actualiza sola cada lunes.

## Archivos (`publicar/`)

| Archivo | Contenido |
|---|---|
| `camaras.json` | Cámaras de velocidad: `[[id, latitud, longitud, velocidad máxima km/h], ...]` |
| `semaforos.json` | Cámaras de semáforo: `[[id, latitud, longitud, sentido controlado en grados o -1], ...]` |
| `version.json` | `fecha` (cuándo cambiaron las cámaras), `revisado` (última revisión), cantidades y estado de cada fuente |

## Cómo se actualiza

`.github/workflows/actualizar.yml` corre cada lunes `herramientas/actualizar_base.py`:

1. Baja cada fuente. Si una falla, usa su última versión buena (`datos/fuentes/`).
2. Une las fuentes (a menos de 60 m es la misma cámara) y completa la máxima que falta con la de la calle en
   OpenStreetMap.
3. Si la base nueva tiene menos del 85 % de la publicada, no la publica.

## Fuentes y licencias

- **OpenStreetMap**: © colaboradores de OpenStreetMap. Esta base contiene información de OpenStreetMap, disponible
  bajo la [Open Database License (ODbL)](https://opendatacommons.org/licenses/odbl/); la base derivada se
  comparte bajo la misma licencia.
- **Provincia de Buenos Aires**: equipos fijos de constatación,
  [InfraccionesBA](https://infraccionesba.gba.gob.ar/equiposDeConstatacion).
- **Ciudad de Buenos Aires**: cámaras fijas de control vehicular,
  [BA Data](https://data.buenosaires.gob.ar/dataset/camaras-fijas-control-vehicular) (CC BY 2.5 AR).
- **Agencia Nacional de Seguridad Vial**: radares fijos autorizados en rutas nacionales
  ([mapa oficial](https://www.argentina.gob.ar/seguridadvial/radares-fijos-y-moviles-autorizados-para-operar-en-rutas-nacionales)).

Datos con fines informativos: pueden faltar cámaras o haber cámaras que ya no estén. La velocidad que manda es
la de la señal en la calle.
