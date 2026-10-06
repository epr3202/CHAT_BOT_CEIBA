BEGIN READ ONLY;
\d audit_event
\d catalog_event_type_map
SELECT a.id, a.actor, a.action, a.entity, a.created_at AT TIME ZONE 'UTC' AS created_at_utc,
 a.new_value::jsonb - 'phone_number' - 'recipient_phone_number' AS new_value,
 a.old_value::jsonb - 'phone_number' - 'recipient_phone_number' AS old_value
FROM audit_event a WHERE a.entity = 'catalog_event_type_map'
 AND ((a.new_value::jsonb->>'catalog_asset_id') = 'd34aebc0-6d51-44e2-99be-dc214afe672f'
 OR (a.old_value::jsonb->>'catalog_asset_id') = 'd34aebc0-6d51-44e2-99be-dc214afe672f')
ORDER BY a.created_at, a.id;
\d catalog_send
\d outbox
\d conversation
\d lead
\d event
SELECT o.id AS outbox_id, o.created_at AT TIME ZONE 'UTC' AS created_at_utc,
 o.conversation_id, '***' || right(o.recipient_phone_number, 4) AS phone_masked,
 o.status, o.sent_at AT TIME ZONE 'UTC' AS sent_at_utc,
 s.catalog_send_id, s.trigger,
 e.event_type AS current_lead_event_type,
 'catalog_send/outbox has no historical event_type column' AS historical_type_note
FROM outbox o LEFT JOIN catalog_send s ON s.outbound_message_id = o.id
LEFT JOIN event e ON e.lead_id = s.lead_id
WHERE o.catalog_asset_id = 'd34aebc0-6d51-44e2-99be-dc214afe672f'
 AND o.message_kind = 'DOCUMENT' AND o.created_at >= timestamptz '2026-10-05 13:30:00 UTC'
ORDER BY o.created_at, o.id;
\d audit_event
SELECT id, actor, action, created_at AT TIME ZONE 'UTC' AS created_at_utc,
 new_value::jsonb - 'phone_number' - 'recipient_phone_number' AS new_value
FROM audit_event WHERE created_at >= timestamptz '2026-10-05 13:30:00 UTC'
 AND action LIKE 'CATALOG%'
 AND new_value::jsonb->>'catalog_asset_id' = 'd34aebc0-6d51-44e2-99be-dc214afe672f'
ORDER BY created_at, id;
ROLLBACK;
