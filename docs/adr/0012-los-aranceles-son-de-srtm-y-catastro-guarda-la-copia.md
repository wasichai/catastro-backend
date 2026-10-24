# ADR-012: Los aranceles son de srtm, y su cuenta de servicio escribe la copia con que valúa el catastro

**Estado**: aceptada · 2026-10-24 · enmienda [ADR-007](0007-srtm-lee-con-una-cuenta-de-servicio.md)

## Contexto

El arancel por m² de cada frente es un valor normativo que publica la municipalidad cada año. Hasta ahora llegaba al
catastro desde la geodatabase con `import_aranceles.py`, y srtm no lo veía más que a través de las valuaciones. srtm
lo registra ahora en su módulo de normativa, con verificación de doble firma (srtm-backend#186), y el catastro tiene
que valuar con ese mismo valor: si cada uno tuviera el suyo, la brecha mediría la diferencia entre dos tablas de
aranceles y no entre lo declarado y lo levantado.

## Alternativas

- **Que el catastro pida el arancel a srtm en cada valuación**: una dependencia en tiempo de ejecución en sentido
  contrario al del [ADR-007](0007-srtm-lee-con-una-cuenta-de-servicio.md), y cada página del GET esperaría a srtm.
- **Que el catastro siga siendo dueño y srtm lo lea**: el registro con doble firma ya es de srtm; habría dos lugares
  donde editar el mismo valor.
- **Una cuenta de servicio aparte para escribir**: separa los permisos, pero es otra credencial que rotar por
  organización para un solo objeto.

## Decisión

- srtm es el dueño de los aranceles. El catastro guarda la **copia** en su objeto `arancel`, con la que valúa.
- El rol `SRTM_LECTOR` (`model/roles.json`) gana `CREATE`, `UPDATE` y `DELETE` sobre `arancel`; sobre los otros
  cuatro objetos sigue siendo solo `READ`. El nombre del rol no cambia, para no romper las cuentas que ya lo tienen.
- `import_aranceles.py` sigue sirviendo para cargar un catastro desde la geodatabase mientras srtm no tenga los
  aranceles de esa organización.

## Consecuencias

- La cuenta de srtm ya no es de solo lectura: su secreto protege también la tabla de aranceles del catastro.
- Un arancel editado a mano en el admin del catastro se pisa en la siguiente escritura de srtm; se corrige en srtm.
- Las cuentas ya creadas reciben el permiso con `python3 -I apply_roles.py` contra cada Core.
- Si después hace falta separar lectura y escritura, es un rol nuevo y un ADR que enmiende este.
