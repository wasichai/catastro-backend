# ADR-007: srtm lee las valuaciones con una cuenta de servicio de solo lectura, por páginas estables

**Estado**: aceptada · 2026-10-19

## Contexto

srtm-backend necesita todas las valuaciones de un año de una organización, sin que una persona inicie sesión, y no
debe poder escribir en el catastro. Son miles de predios.

## Alternativas

- **Un usuario humano compartido**: su clave termina en un archivo de configuración y tiene los permisos de una
  persona.
- **Leer la base del catastro directamente**: acopla srtm al esquema físico y salta los permisos de wasichai.
- **Un solo GET con todo el año**: una respuesta enorme y un timeout cuando el padrón crece.

## Decisión

- srtm entra con una **cuenta de servicio** de wasichai (ADR-043 de wasichai), con `clientId` y `clientSecret`, y pide
  su token con `POST /api/auth/token`. La crea `model/crear_cuenta_srtm.py`, que imprime el secreto una sola vez.
- La cuenta tiene un solo rol, `SRTM_LECTOR` (`model/roles.json`, sincronizado por `apply_roles.py`): `READ` sobre los
  cinco objetos y nada más.
- `GET /api/catastro/valuaciones?anio=&page=&size=` pagina por `codigo_municipal`, así que las páginas son estables;
  `size` de 1 a 500. Lee como quien llama: sin token 401, sin permiso 403 de core, un parámetro inválido 422 que lo
  nombra.
- Cada ítem trae siempre todas sus llaves, `loteGeom` en GeoJSON EPSG:4326 incluido.

## Consecuencias

- srtm guarda un `clientId`/`clientSecret` por organización (`SRTM_CATASTRO_ORGANIZACIONES_<CLAVE>_*`); rotarlo es
  `POST /api/service-accounts/{id}/secret`.
- Un permiso dado a mano a `SRTM_LECTOR` en el admin se pierde en el siguiente `apply_roles.py`: el rol es el de
  `roles.json`.
- La forma de la respuesta es un contrato con srtm-backend (`ClienteCatastro`): una llave nueva se agrega; una que se
  quita o cambia de sentido se coordina con un PR en srtm.
