R0 convierte las adaptaciones diagnósticas en preparación explícita de tests. Parte de
`97bd4de96a9fdd59fb8f0f92865d3c7c16f48caa`; producto histórico
`89356876a04bc836ea9b2c223ff8aba2b424ffde`. No modifica producto ni auditorías.

`configure_test_database` exige TEST_DATABASE_URL, asigna DATABASE_URL y limpia la caché
antes de crear settings/engines. Sustituye el destino fijo de la fixture de catálogos y
la captura al importar del helper de preparación. Monkeypatch restaura las variables y
el lifecycle de fixtures limpia la caché al terminar.

Tres tests declaran usefixtures para un doble respx que solo acepta POST al endpoint
exacto de OpenRouter y el prompt/instrucción de extracción de tipo. Retorna JSON válido
con un tipo ajeno al catálogo. El cliente, parser, normalizador y persistencia siguen
siendo reales. Exige una llamada y rechaza peticiones inesperadas. Ocho casos de calidad
comprueban configuración, contrato HTTP, uso y retirada del doble.

El launcher deriva de run_ci.py del diagnóstico: conserva recursos Docker con nonce,
red interna, extracción Git y artefactos. R0 añade SHA candidato, lista explícita de
rutas y comparación de todos los blobs protegidos del commit base de R0. El driver
conserva el guard de red y exige destino, rol, propietario, versión y system_identifier
de la instancia recién creada antes de exponer una conexión a los fixtures. Nunca usa
que el nombre contenga test como única autorización de reset.

Solo se activa quality-r0.yml por push a quality/r0-*. Los dos jobs prueban el mismo
GITHUB_SHA verificado contra checkout: catorce nodos más ocho casos nuevos, y suite
completa, respectivamente. Ruff verifica producto, tests y auxiliares nuevos con la
configuración original. Los hooks pytest solo registran resultados por fase. El driver
no genera copias diagnósticas ni sustituye comportamiento de tests.

Referencias de identidad y disparadores:
[contextos de GitHub](https://docs.github.com/en/actions/reference/workflows-and-actions/contexts)
y [eventos](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows).
Los workflows históricos/deploy se preservan y no se activan en esta rama.

Limitaciones: fixtures metadata; sin migrate-cycle, sin nueva migración ni lock;
dependencias resueltas registradas; proveedores simulados. Un PASS R0 es una regresión
de calidad nueva y no reescribe el histórico 613/14 ni cierra H01-H29. H02 sigue abierto
y bloquea la aprobación del producto. No se repiten aquí sus reproducciones.
