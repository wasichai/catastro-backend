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

## Primer release: 0.1.0

Salió el 2026-10-24 (wasichai/catastro-backend#1). Para forzar esa versión, el manifest partía de `0.0.0` y la config
traía `"release-as": "0.1.0"`; se quitó al mezclar ese PR, porque si no cada PR siguiente volvería a proponer 0.1.0.
Para forzar otra versión, se vuelve a poner `release-as` y se quita después del release. Mientras la versión sea 0.x,
un `feat:` sube el minor y un `fix:` el patch (`bump-minor-pre-major`).

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
