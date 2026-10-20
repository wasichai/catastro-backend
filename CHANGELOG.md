# Changelog

## 0.1.0 (2026-10-20)


### Features

* **api:** valuaciones por año para srtm con cuenta de servicio ([dca8e7b](https://github.com/wasichai/catastro-backend/commit/dca8e7b2df6f37b94f774d4a0a9b7120f38d9e64))
* **model:** import_fichas.py lee la clasificación y la sección de cada piso ([054f13e](https://github.com/wasichai/catastro-backend/commit/054f13e414955d015bf7263c1b093e354e431078))
* **model:** objetos del catastro e importadores de fichas, aranceles y lotes ([133d4dd](https://github.com/wasichai/catastro-backend/commit/133d4ddcd8a0223297741c902a17e572efcc358a))
* **model:** región de la organización en configuracion_catastro ([85486a3](https://github.com/wasichai/catastro-backend/commit/85486a3afd14c00d87b6cc95ffea03166a57ae8a))
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
