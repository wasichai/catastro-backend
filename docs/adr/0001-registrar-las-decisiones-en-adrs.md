# ADR-001: Las decisiones se registran en ADRs

**Estado**: aceptada · 2026-10-20

## Contexto

Hasta ahora las decisiones de catastro-backend vivían en el README (la sección «Decisiones normativas», D1 a D12) y en
los mensajes de commit. El README describe cómo es el sistema hoy; no dice por qué se eligió así, qué se descartó ni
cuándo cambió. Cuando una decisión cambia (D1 se investigó y se amplió, D4 ganó `techo_incluido`), el README se
reescribe y la historia se pierde.

wasichai registra sus decisiones en `docs/adr/` (69 hasta hoy), y srtm-backend las cita (ADR-036, ADR-040...).

## Alternativas

- **Seguir solo con el README**: barato, pero mezcla el estado con la historia y no deja ver qué se descartó.
- **Un único documento de decisiones**: crece sin orden y se edita en lugar de enmendarse.
- **Issues de GitHub**: se pierden fuera del repositorio y no viajan con el código.

## Decisión

Un archivo por decisión en `docs/adr/`, numerado en orden (`NNNN-titulo-en-minusculas.md`), con el formato de wasichai:

```markdown
# ADR-NNN: Título que dice la decisión

**Estado**: aceptada · AAAA-MM-DD

## Contexto
## Alternativas
## Decisión
## Consecuencias
```

- **Una decisión no se edita para cambiarla**: un ADR posterior la enmienda o la reemplaza, y los dos lo dicen en su
  línea de estado (`enmendada por ADR-NNN`, `reemplaza a ADR-NNN`). Se corrigen erratas y enlaces, nada más.
- **Entran** las decisiones de arquitectura (cómo se integra con srtm, qué se guarda, dónde viven las tablas) y las
  **normativas** (cómo se lee la norma donde la norma no es clara o la municipalidad decide).
- **El ADR va en el mismo PR** que implementa la decisión, y [`README.md`](README.md) lo lista.
- Los ADR-001 a ADR-010 se escribieron juntos el 2026-10-20 y recogen lo ya decidido desde el arranque del proyecto
  (2026-10-19); su fecha es la de la decisión, no la del archivo.

## Consecuencias

- El README del proyecto describe el estado y enlaza al ADR que lo justifica; la historia queda en `docs/adr/`.
- Un cambio normativo (por ejemplo, la respuesta pendiente de D1 sobre institucional en 02 o 03) es un ADR nuevo que
  enmienda al anterior, no un párrafo reescrito.
- Cuesta un archivo más por decisión. Las decisiones menores (un nombre, un refactor) no lo necesitan.
