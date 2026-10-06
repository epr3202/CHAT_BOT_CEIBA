BEGIN READ ONLY;
\d reservation
\d event
\d conversation
\d customer
\d audit_event
WITH target AS (
 SELECT r.* FROM reservation r JOIN event e ON e.event_id = r.event_id
 WHERE e.event_type = 'ROMANTIC_DINNER' AND r.conversation_id IS NOT NULL
 AND (r.status = 'RESERVED' OR EXISTS (
  SELECT 1 FROM audit_event a WHERE a.action = 'RESERVATION_STATUS_CHANGED'
  AND a.new_value->>'reservation_id' = r.reservation_id::text
  AND a.new_value->>'status' = 'RESERVED'))
 ORDER BY r.updated_at DESC, r.created_at DESC LIMIT 1
)
SELECT c.id AS conversation_id, '***' || right(u.phone_number, 4) AS phone_masked,
 c.state, c.pending_action, c.last_question_code, c.active_lead_id,
 e.event_type, e.event_date, t.reservation_id, t.status AS reservation_status,
 t.starts_at AT TIME ZONE 'UTC' AS starts_at_utc,
 t.created_at AT TIME ZONE 'UTC' AS reservation_created_at_utc,
 t.updated_at AT TIME ZONE 'UTC' AS reservation_updated_at_utc
FROM target t JOIN conversation c ON c.id = t.conversation_id
JOIN customer u ON u.id = c.customer_id JOIN event e ON e.event_id = t.event_id;
\d reservation
\d event
\d conversation
\d audit_event
WITH target AS (
 SELECT r.* FROM reservation r JOIN event e ON e.event_id = r.event_id
 WHERE e.event_type = 'ROMANTIC_DINNER' AND r.conversation_id IS NOT NULL
 AND (r.status = 'RESERVED' OR EXISTS (
  SELECT 1 FROM audit_event a WHERE a.action = 'RESERVATION_STATUS_CHANGED'
  AND a.new_value->>'reservation_id' = r.reservation_id::text
  AND a.new_value->>'status' = 'RESERVED'))
 ORDER BY r.updated_at DESC, r.created_at DESC LIMIT 1
)
SELECT a.id, a.actor, a.action, a.entity, a.created_at AT TIME ZONE 'UTC' AS created_at_utc,
 (SELECT jsonb_object_agg(key, value) FROM jsonb_each(CASE WHEN jsonb_typeof(a.old_value::jsonb) = 'object' THEN a.old_value::jsonb ELSE '{}'::jsonb END)
  WHERE key IN ('conversation_id','lead_id','event_id','reservation_id','event_type','state',
   'pending_action','last_question_code','status','plan_code','plan_id','event_date',
   'starts_at','price_cop','trigger','catalog_asset_id','send_mode','source')) AS old_value,
 (SELECT jsonb_object_agg(key, value) FROM jsonb_each(CASE WHEN jsonb_typeof(a.new_value::jsonb) = 'object' THEN a.new_value::jsonb ELSE '{}'::jsonb END)
  WHERE key IN ('conversation_id','lead_id','event_id','reservation_id','event_type','state',
   'pending_action','last_question_code','status','plan_code','plan_id','event_date',
   'starts_at','price_cop','trigger','catalog_asset_id','send_mode','source')) AS new_value
FROM audit_event a CROSS JOIN target t
WHERE a.new_value->>'conversation_id' = t.conversation_id::text
 OR a.old_value->>'conversation_id' = t.conversation_id::text
 OR a.new_value->>'lead_id' = t.lead_id::text OR a.old_value->>'lead_id' = t.lead_id::text
 OR a.new_value->>'event_id' = t.event_id::text OR a.old_value->>'event_id' = t.event_id::text
 OR a.new_value->>'reservation_id' = t.reservation_id::text
 OR a.old_value->>'reservation_id' = t.reservation_id::text
ORDER BY a.created_at, a.id;
ROLLBACK;
