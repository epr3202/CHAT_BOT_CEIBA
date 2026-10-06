BEGIN READ ONLY;
\d catalog_event_type_map
\d audit_event
SELECT m.id AS map_id, m.event_type, m.send_mode,
 m.created_at AT TIME ZONE 'UTC' AS map_created_at_utc,
 a.id AS audit_id, a.actor, a.action, a.created_at AT TIME ZONE 'UTC' AS audit_created_at_utc
FROM catalog_event_type_map m LEFT JOIN audit_event a
 ON a.action = 'CATALOG_EVENT_TYPES_REPLACED'
 AND a.new_value::jsonb->>'catalog_asset_id' = m.catalog_asset_id::text
 AND a.new_value::jsonb->'event_types' ? m.event_type
 AND a.created_at = m.created_at
WHERE m.catalog_asset_id = 'd34aebc0-6d51-44e2-99be-dc214afe672f' AND m.id IN (9, 10)
ORDER BY m.id;
ROLLBACK;
