# Releases

Igual que srtm-backend y wasichai: [release-please](https://github.com/googleapis/release-please) sobre Conventional
Commits.

## Flujo

1. Se mergean commits convencionales (`feat:`, `fix:`, ...) a `main`.
2. `release-please.yml` corre en cada push a `main` y abre (o actualiza) un PR de release que sube `version=` en
   `gradle.properties` y escribe `CHANGELOG.md`.
3. Al mergear ese PR, release-please crea el tag `vX.Y.Z` y el GitHub Release.
4. El release dispara `release.yml`: compila `./gradlew bootJar` con la versión del tag y adjunta
   `catastro-backend-X.Y.Z.jar` y su `.sha256` al release.

## Versiones forzadas: 0.1.0 y 1.0.0

Para forzar una versión, `release-please-config.json` trae `"release-as": "X.Y.Z"`, y **se quita después de mezclar
ese PR de release**; si no, cada PR siguiente volvería a proponer la misma versión.

- **0.1.0** (wasichai/catastro-backend#1): el manifest partía de `0.0.0` y la config traía `"release-as": "0.1.0"`.
- **1.0.0**: la config trae `"release-as": "1.0.0"`. El PR de release que abra release-please propone exactamente
  1.0.0; al mezclarlo, quitar `release-as`.

`release-as` no basta: release-please solo abre el PR si hay algo para el CHANGELOG desde el último release
(`No user facing commits found ... - skipping`). Por eso `changelog-sections` muestra también `docs:` (las guías y los
ADRs son parte de lo que se entrega); `build:` (las dependencias de dependabot), `ci:`, `chore:`, `refactor:`, `test:`
y `style:` quedan ocultos y no abren un release por sí solos.

Desde 1.0.0, un `feat:` sube el minor, un `fix:` el patch y un cambio que rompe el contrato con srtm (`feat!:` o
`BREAKING CHANGE:`) el major. Antes de 1.0.0, un cambio que rompía subía solo el minor (`bump-minor-pre-major`).

## No cambiar el título del PR de release

release-please reconoce su PR por el título (`chore(main): release X.Y.Z`) y la etiqueta `autorelease: pending`. Si
se cambia el título antes de mezclarlo, el workflow no crea el tag ni el release (`Bad pull request title`) y aborta en
cada push siguiente (`There are untagged, merged release PRs outstanding`). Pasó con 0.1.0, cuyo título se cambió a
`feat(main)!: release 0.1.0`. Se arregla devolviéndole el título original al PR ya mezclado; el siguiente push a
`main` crea el tag y el release.

## La versión del jar y la del motor

Son cosas distintas. La del jar (`gradle.properties`) la sube release-please. La del motor
(`ValuacionesService.VERSION`, `valuacion-vN`) solo cambia cuando cambia la aritmética de la valorización, a mano y en
el mismo PR, porque srtm-backend la guarda con cada corrida de la brecha
([ADR-003](../adr/0003-valorizar-al-vuelo-sin-guardar.md)). Un release que cambia la versión del motor lo dice en la
descripción del PR (`feat(valuacion): ...`), para que quien despliega sepa que las cifras cambian.

## Secreto (una vez)

`RELEASE_PLEASE_TOKEN`: PAT fine-grained sobre este repo con Contents y Pull requests en lectura/escritura. Un
release creado con el `GITHUB_TOKEN` del workflow no dispara otros workflows, y sin PAT `release.yml` no correría.
Sin el secreto, `release-please.yml` usa `GITHUB_TOKEN` (requiere Settings → Actions → General → permitir que
Actions cree PRs) y el jar habría que adjuntarlo a mano.
