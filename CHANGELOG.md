# Changelog

## [1.2.0](https://github.com/wasichai/catastro-backend/compare/v1.1.0...v1.2.0) (2026-10-28)


### Features

* **brechas:** importar srtm_brecha_nivel del corte analítico ([#73](https://github.com/wasichai/catastro-backend/issues/73)) ([6f713a7](https://github.com/wasichai/catastro-backend/commit/6f713a7d8e22abb1c2350620de3d67fd90865ecf)), closes [#72](https://github.com/wasichai/catastro-backend/issues/72)
* **brechas:** los niveles de una ficha en la API de brechas ([#76](https://github.com/wasichai/catastro-backend/issues/76)) ([55d729e](https://github.com/wasichai/catastro-backend/commit/55d729e0707712ed13d61f9d04d0d4dc6d399f98)), closes [#75](https://github.com/wasichai/catastro-backend/issues/75)

## [1.1.0](https://github.com/wasichai/catastro-backend/compare/v1.0.0...v1.1.0) (2026-10-26)


### Features

* **api:** las valuaciones traen las construcciones (piso, sección y área) ([#71](https://github.com/wasichai/catastro-backend/issues/71)) ([4be92a1](https://github.com/wasichai/catastro-backend/commit/4be92a121e02cd37b1dc85d7a87cd90076f23ccb))
* **gis:** el WMS de GeoServer pide un usuario y solo sirve las capas de su organización ([#68](https://github.com/wasichai/catastro-backend/issues/68)) ([46403ac](https://github.com/wasichai/catastro-backend/commit/46403ac9f6475fcba30ed69c66d7e5567c785007))
* **vias:** alias revisados de nombres de vía (--alias, --proponer-alias) ([#65](https://github.com/wasichai/catastro-backend/issues/65)) ([9d1b92b](https://github.com/wasichai/catastro-backend/commit/9d1b92b310a9c0298fc2ce32bfac9b7c68128e44))

## [1.0.0](https://github.com/wasichai/catastro-backend/compare/v0.1.0...v1.0.0) (2026-10-25)


### Features

* **api:** GET /api/catastro/cambios, los cambios del catastro desde un cursor ([#36](https://github.com/wasichai/catastro-backend/issues/36)) ([fe8978e](https://github.com/wasichai/catastro-backend/commit/fe8978e1a589ee9ebbab2c65a9660d4392844c8f))
* **brechas:** API del dashboard de brechas para catastro-ui ([#53](https://github.com/wasichai/catastro-backend/issues/53)) ([#57](https://github.com/wasichai/catastro-backend/issues/57)) ([279d4ad](https://github.com/wasichai/catastro-backend/commit/279d4ad847fec9a81a79742402ac08861fe963d0))
* **dev:** GeoServer en el compose para publicar capas WMS ([#54](https://github.com/wasichai/catastro-backend/issues/54)) ([#55](https://github.com/wasichai/catastro-backend/issues/55)) ([d6a849c](https://github.com/wasichai/catastro-backend/commit/d6a849cb5dec37a09fbe96cbe601e3b19f8d095a))
* entregas del levantamiento (upsert con historia en el audit log) ([#28](https://github.com/wasichai/catastro-backend/issues/28)) ([fcd555d](https://github.com/wasichai/catastro-backend/commit/fcd555d5ba51ff064832cd9dad1634cfa6f53ffe))
* **gis:** vistas de mapa y capas WMS con estilo para aranceles y brechas ([#60](https://github.com/wasichai/catastro-backend/issues/60)) ([93a6919](https://github.com/wasichai/catastro-backend/commit/93a6919b164aa47060d2792aee0da816ab909241))
* **model:** el libro de comparación de Ica a una entrega, con titulares y vínculo ([#38](https://github.com/wasichai/catastro-backend/issues/38)) ([8a158c5](https://github.com/wasichai/catastro-backend/commit/8a158c50fb92d12ce3ee775b7a82548fb0436f2d))
* **modelo:** corte de brecha, sus fichas y la bandeja de decisiones ([#52](https://github.com/wasichai/catastro-backend/issues/52)) ([#56](https://github.com/wasichai/catastro-backend/issues/56)) ([6307cef](https://github.com/wasichai/catastro-backend/commit/6307cefdc8d76852e691b9ecd47c25a5d05b0df3))
* **modelo:** reporte de fichas sin arancel vigente y corrección por entrega ([#51](https://github.com/wasichai/catastro-backend/issues/51)) ([24165f8](https://github.com/wasichai/catastro-backend/commit/24165f883c9c71e47827f68a3e77b573336720c1))
* titulares del levantamiento y GET /api/catastro/titulares ([#32](https://github.com/wasichai/catastro-backend/issues/32)) ([dba20d7](https://github.com/wasichai/catastro-backend/commit/dba20d714239ba315968fc1988de3a94b1efe07b))
* **vias:** asignación LOTES para los códigos de urbanización ([#47](https://github.com/wasichai/catastro-backend/issues/47)) ([#50](https://github.com/wasichai/catastro-backend/issues/50)) ([8921789](https://github.com/wasichai/catastro-backend/commit/8921789269c439ba90a85835a80c13e1b878f9b8))
* **vias:** tramos de vía con su arancel e import_vias.py ([#42](https://github.com/wasichai/catastro-backend/issues/42)) ([#43](https://github.com/wasichai/catastro-backend/issues/43)) ([90e9f03](https://github.com/wasichai/catastro-backend/commit/90e9f03f41ed52c11dbfac5cebff472cb0134362))
* vínculo de cada ficha con rentas y los códigos del SNIC ([#31](https://github.com/wasichai/catastro-backend/issues/31)) ([16cee88](https://github.com/wasichai/catastro-backend/commit/16cee88e1fd89b088851eef212c6e4307473e178))


### Bug Fixes

* **model:** ajustes de la revisión final del carril A (conversor de Ica y docs) ([#39](https://github.com/wasichai/catastro-backend/issues/39)) ([b1c5179](https://github.com/wasichai/catastro-backend/commit/b1c517918d40ce0d176939ab5e90549d17e43e9f))
* **modelo:** titulares del libro v3, condición opcional y alias codigo_municipal ([#49](https://github.com/wasichai/catastro-backend/issues/49)) ([f55965c](https://github.com/wasichai/catastro-backend/commit/f55965cf31750c99bee7fded740db4e6d72d9ebd))
* **model:** parse_date no se cae con un número de serie fuera de rango ([#40](https://github.com/wasichai/catastro-backend/issues/40)) ([ece77bd](https://github.com/wasichai/catastro-backend/commit/ece77bd8947c0da96308172dd266a2ed29b073b5))
* **valuacion:** un predio rústico sale sin valor con PREDIO_RUSTICO (valuacion-v3) ([#37](https://github.com/wasichai/catastro-backend/issues/37)) ([0216871](https://github.com/wasichai/catastro-backend/commit/0216871af23f07b7897a9902fbfa62955c16b6e7))
* **vias:** import_vias.py con el gpkg real de Ica ([#45](https://github.com/wasichai/catastro-backend/issues/45)) ([#46](https://github.com/wasichai/catastro-backend/issues/46)) ([0110ad6](https://github.com/wasichai/catastro-backend/commit/0110ad63cccc86601df786c4d281103485bf6e45))


### Documentation

* **adr:** ADR-011 y ADR-012, y preparar el release 1.0.0 ([#20](https://github.com/wasichai/catastro-backend/issues/20)) ([ff1fcbd](https://github.com/wasichai/catastro-backend/commit/ff1fcbd5019cf180da1eefa717a23fc64f2a5a63))
* **adr:** el ADR-013 enmienda al ADR-008 ([#30](https://github.com/wasichai/catastro-backend/issues/30)) ([8f65aba](https://github.com/wasichai/catastro-backend/commit/8f65abaaa24daeb254aa582ba09d3f30c223fc64))

## 0.1.0 (2026-10-24)


### Features

* **api:** valuaciones por año para srtm con cuenta de servicio ([dca8e7b](https://github.com/wasichai/catastro-backend/commit/dca8e7b2df6f37b94f774d4a0a9b7120f38d9e64))
* **model:** import_fichas.py lee la clasificación y la sección de cada piso ([054f13e](https://github.com/wasichai/catastro-backend/commit/054f13e414955d015bf7263c1b093e354e431078))
* **model:** objetos del catastro e importadores de fichas, aranceles y lotes ([133d4dd](https://github.com/wasichai/catastro-backend/commit/133d4ddcd8a0223297741c902a17e572efcc358a))
* **model:** región de la organización en configuracion_catastro ([85486a3](https://github.com/wasichai/catastro-backend/commit/85486a3afd14c00d87b6cc95ffea03166a57ae8a))
* **roles:** la cuenta de servicio de srtm escribe los aranceles ([cd72b14](https://github.com/wasichai/catastro-backend/commit/cd72b14fb9fbe8a99a55ec8941f0c593d5525252))
* **roles:** la cuenta de servicio de srtm escribe los aranceles ([#18](https://github.com/wasichai/catastro-backend/issues/18)) ([fc2e67e](https://github.com/wasichai/catastro-backend/commit/fc2e67ea965cb0c5b2fada099535f0cef269dfa4))
* **tablas:** obras complementarias de la costa, anexo III.2 verificado ([d716a69](https://github.com/wasichai/catastro-backend/commit/d716a696d38fc4c82f049d07b30867ff532271a3)), closes [#9](https://github.com/wasichai/catastro-backend/issues/9)
* **tablas:** tablas por región y valores unitarios de la costa 2026 ([75c3ccc](https://github.com/wasichai/catastro-backend/commit/75c3cccbe963a41ea1669c70dfd2f18b43c4bda9))
* **tablas:** valores unitarios selva 2026, depreciación rnt, obras y parámetros ([a394fcd](https://github.com/wasichai/catastro-backend/commit/a394fcdd39e5d0c281bb72861a9ae6ea3bade654))
* **valuacion:** depreciación por construcción y secciones de un piso ([0dae5af](https://github.com/wasichai/catastro-backend/commit/0dae5af4f151b83e77169a7435c71ba73e1beb0c))
* **valuacion:** detalle por piso y por obra en la valuación del motor ([0175bc0](https://github.com/wasichai/catastro-backend/commit/0175bc0323ff09adbe0467c42e8218a8fa7ec5fd))
* **valuacion:** el motor nombra la región de su cuadro y no salta obras sin cuadro ([c6d432f](https://github.com/wasichai/catastro-backend/commit/c6d432f32759e6c351f015336bfd5583dd406b76))
* **valuacion:** indicador techo_incluido para muros D de drywall ([5a9ad18](https://github.com/wasichai/catastro-backend/commit/5a9ad1898e29335df50e0749880e0bc3b8f81492))
* **valuacion:** indicador techo_incluido para muros D de drywall ([2501a69](https://github.com/wasichai/catastro-backend/commit/2501a6967598686af70e26c6989abcd71178dcb2))
* **valuacion:** las valuaciones usan la región de la organización que llama ([8deb349](https://github.com/wasichai/catastro-backend/commit/8deb34985a35b0e383b97a73a77edd92c5f7cffa))
* **valuacion:** motor de autoavalúo (terreno, construcción, obras) ([f268023](https://github.com/wasichai/catastro-backend/commit/f2680236f202b7c5bc500faaf7e69c64891f1b00))
* **valuacion:** región por organización y tablas de la costa ([1c93fd0](https://github.com/wasichai/catastro-backend/commit/1c93fd07d11c9a986ac5b7d9e812e875e8788973))
* **valuacion:** tabla de depreciación y sección de cada construcción ([0280328](https://github.com/wasichai/catastro-backend/commit/028032888241aec223d51a2fee61f14a1c94b630))
* **valuacion:** valuar insumos sueltos (POST /api/catastro/valuacion) ([6ebda0c](https://github.com/wasichai/catastro-backend/commit/6ebda0cb04dbf98b501d5b3b3ca647e77b0fe933))
* **valuacion:** valuar insumos sueltos (POST /api/catastro/valuacion) ([c79d84e](https://github.com/wasichai/catastro-backend/commit/c79d84ece97f9898a4f28d050f73f6ec6d8a15fa)), closes [#16](https://github.com/wasichai/catastro-backend/issues/16)


### Bug Fixes

* **model:** clasificación numérica de un xlsx y una sección ilegible ([e880ed9](https://github.com/wasichai/catastro-backend/commit/e880ed9650d3e5d5eb07cb3f6964f7379742e719))
* **model:** código real en el ejemplo de codigo_vu (CERCOS METALICOS|88) ([827a4cd](https://github.com/wasichai/catastro-backend/commit/827a4cd1ca7926e38c9a08fe8851503efe07340b))
* **model:** fichas idempotentes por llave natural en pisos y obras ([edc1c6d](https://github.com/wasichai/catastro-backend/commit/edc1c6d83456a823a3ddec5740d3fa65479b68be))
* **model:** los comandos corren bajo python3 -I ([0af6ecd](https://github.com/wasichai/catastro-backend/commit/0af6ecd1b65b3b8674bc13b10238684a5b89e77c))
* **model:** reparar fichas a medias, listar todos los problemas y salir 2 ante entradas ilegibles ([775ec80](https://github.com/wasichai/catastro-backend/commit/775ec8089687e62f0874a478b3dc88fcef231391))
* **tablas:** cuadro selva fijado entero, csv con crlf y D2 con la grafía del RNT ([46c0adc](https://github.com/wasichai/catastro-backend/commit/46c0adc5d346e9215b1cdf179f58d5396aec870e))
* **tablas:** D1 investigado, institucional a la tabla 02 y los 324 usos con tabla ([db6e454](https://github.com/wasichai/catastro-backend/commit/db6e45498fd0d0ddda843f05a2738c33bb4a338f))
* **valuacion:** D1 y D4 investigados: tabla por uso y muros A sin techos ([310422f](https://github.com/wasichai/catastro-backend/commit/310422fb5a1fe9f28c358fa2fa8b105960a40004))
* **valuacion:** muros A no considera techos, como dice la nota del cuadro ([07e663f](https://github.com/wasichai/catastro-backend/commit/07e663fec8a21ca8f5b554f827acd77c67d61002))
* **valuacion:** región como función probada, en la respuesta y orden de actualización ([a7fb3cc](https://github.com/wasichai/catastro-backend/commit/a7fb3cc10774c4169d860744584537bbe0a45275))
* **valuacion:** tabla del uso antes de lo declarado por piso u obra, áreas y cantidades negativas ([0006b2b](https://github.com/wasichai/catastro-backend/commit/0006b2bdff8fa5d95bb7f2bf6c7884e8c49be5be))
