# ADR-004: Las tablas normativas son CSV versionados en el jar, citan su fuente y nunca convierten un hueco en cero

**Estado**: aceptada · 2026-10-19

## Contexto

La valorización usa tablas publicadas: los valores unitarios de edificación (R.M. N.° 277-2025-VIVIENDA, Anexo I por
región), las obras complementarias (Anexo III), la depreciación del Reglamento Nacional de Tasaciones y unos pocos
parámetros anuales (factor de oficialización 0.68, % de actualización, +5 % desde el 5.° piso). Cambian una vez al
año como mucho, y un error de transcripción cambia el autoavalúo de miles de predios. Los cuadros tienen casillas sin
valor (`.....`) y celdas sin dato (`*` en el RNT).

## Alternativas

- **Objetos del Core editables en el admin**: cualquiera podría cambiarlas sin revisión, y no habría fuente ni prueba.
- **Leerlas del corpus de normativa en tiempo de ejecución**: otra dependencia en el arranque.

## Decisión

- Viven en `src/main/resources/tablas/`, un CSV por tabla, región y año (`valores-unitarios-<region>-<anio>.csv`).
- Cada archivo abre con líneas `#` que citan su fuente (norma, anexo, ruta en el corpus de normativa, sha256 cuando es
  copia exacta); las filas van tal como en la fuente.
- Se cargan una vez por región al arrancar (`Tablas.de(region)`, bean `TablasPorRegion`). Un archivo mal formado hace
  **fallar el arranque**, no la primera valuación.
- Cada tabla tiene su prueba en `TablasTest`, celda por celda o por sha256. Una tabla transcrita de un PDF se
  transcribe por dos métodos independientes y la verifica una persona antes del commit.
- Una celda `.....` o `*` es **nulo, nunca cero**: el motor la convierte en un `motivo`
  ([ADR-005](0005-el-motor-es-una-funcion-pura.md)).
- `Tablas` responde con el vocabulario de la fuente (`Concreto`, `Muy Bueno`); llevar los enums del catastro a él es
  cosa del motor (D2, D3).

## Consecuencias

- Cambiar una tabla es un PR con su prueba y un release; queda en la historia quién la cambió y con qué fuente.
- Una tabla de un año nuevo es un archivo nuevo, no una edición del anterior.
- Una municipalidad no puede ajustar una tabla sin un release. Lo que sí es local (la región,
  [ADR-006](0006-la-region-es-de-la-organizacion.md); el mapeo uso → tabla de depreciación, D1) está separado.
