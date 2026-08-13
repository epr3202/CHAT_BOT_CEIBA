# Slice 2A Catalogos Prompt

## T1, caso faltante

TC-CAT-019 | Tipo de evento con un asset PROACTIVE y tres ON_REQUEST |
El envio proactivo encola exactamente uno (el PROACTIVE); los ON_REQUEST
nunca se disparan proactivamente.

## T2, campo requerido

CatalogEventTypeMap: catalog_asset_id, event_type (enum existente),
send_mode (enum PROACTIVE | ON_REQUEST, default ON_REQUEST), constraint
unico sobre (catalog_asset_id, event_type). El envio proactivo del
orquestador filtra send_mode = PROACTIVE y active = true. La solicitud
explicita (EXPLICIT_REQUEST) envia los assets PROACTIVE del event_type,
sin dedupe; la seleccion de complementarios por tema queda fuera del slice.
