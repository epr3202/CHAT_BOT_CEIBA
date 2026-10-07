-- G1 pago: exclusivamente lectura; no muestra teléfonos, cuentas ni llaves.
-- Wrapper: ssh -o BatchMode=yes ceiba-staging-deploy 'cd /home/deploy/chat_bot_ceiba && docker compose exec -T -e PGOPTIONS="-c default_transaction_read_only=on -c statement_timeout=15000" db sh -c "exec psql -U \"\$POSTGRES_USER\" -d \"\$POSTGRES_DB\" -X -v ON_ERROR_STOP=1 -P pager=off"' < ~/g1-payment-2026-10-07.sql
\set ON_ERROR_STOP on
\pset pager off
BEGIN READ ONLY;
SET LOCAL TIME ZONE 'UTC';
\d message
\d outbox
\echo 'Conversaciones del cliente de la conversación forense 206'
SELECT id, state, pending_action, last_question_code, active_lead_id, created_at, last_message_at,
       CASE WHEN jsonb_typeof(booking_draft)='object' THEN booking_draft - 'customer_name' - 'name' END AS booking_draft
FROM conversation WHERE customer_id=(SELECT customer_id FROM conversation WHERE id=206)
ORDER BY id;
\echo 'Reservas actuales del cliente'
SELECT reservation_id, conversation_id, lead_id, plan_id, status, price_cop, amount_paid_cop,
       payment_kind, starts_at, ends_at, calendar_status, created_at, updated_at
FROM reservation WHERE customer_id=(SELECT customer_id FROM conversation WHERE id=206)
ORDER BY created_at;
\echo 'Comprobantes: decisión humana y vínculo'
SELECT id, conversation_id, message_id, reservation_id, lead_id, review_status, amount_cop,
       reviewed_by_agent_id, reviewed_at, download_status, created_at, updated_at
FROM payment_evidence WHERE customer_id=(SELECT customer_id FROM conversation WHERE id=206)
ORDER BY id;
\echo 'Propuestas IA del comprobante: sin datos extraídos'
SELECT r.review_id, r.evidence_id, r.status, r.suggestion, r.suggested_amount_cop,
       r.ai_execution_id, r.attempt_number, r.created_at
FROM payment_evidence_review r JOIN payment_evidence e ON e.id=r.evidence_id
WHERE e.customer_id=(SELECT customer_id FROM conversation WHERE id=206)
ORDER BY r.created_at;
\echo 'Knowledge: versiones y estado, sin valores bancarios'
SELECT code, version, status, allowed_variables
FROM knowledge_entry
WHERE code IN ('RESP-PAYMENT-004','RESP-PAYMENT-001','RESP-BOOKING-PARTIAL-001',
 'RESP-BOOKING-PAYMENT-001','RESP-HANDOFF-001','RESP-HANDOFF-002','RESP-EVENT-DATA-003')
ORDER BY code, version;
\echo 'Mensajes del cliente posteriores al 6 de octubre: texto de entrada conocido únicamente'
SELECT id, conversation_id, direction, created_at,
       CASE WHEN direction='INBOUND' AND content#>>'{text,body}' IN
          ('Hola Me gustaría agendar una pedida de mano para el 14',
           'Me interesa confesión bajo la luna','8','Emerson','Si','Sí','si','sí')
            THEN content#>>'{text,body}' ELSE '[texto omitido]' END AS known_text
FROM message WHERE conversation_id IN
 (SELECT id FROM conversation WHERE customer_id=(SELECT customer_id FROM conversation WHERE id=206))
AND created_at >= '2026-10-06 00:00:00+00'
ORDER BY created_at, id;
\echo 'Auditoría seleccionada: montos, vínculo, transiciones y handoff'
WITH selected AS (
 SELECT * FROM audit_event a WHERE created_at >= '2026-10-02 00:00:00+00'
 AND (new_value::jsonb->>'conversation_id' IN ('196','197','208','209')
  OR old_value::jsonb->>'conversation_id' IN ('196','197','208','209')
  OR new_value::jsonb->>'reservation_id'='f3fb9b04-1f40-4172-b9e2-b157b1ecf41a'
  OR new_value::jsonb->>'evidence_id' IN ('6','7','8')
  OR old_value::jsonb->>'evidence_id' IN ('6','7','8'))
)
SELECT a.id, a.created_at, a.actor, a.action, a.entity, a.request_id,
 (SELECT jsonb_object_agg(j.key,j.value) FROM jsonb_each(CASE WHEN jsonb_typeof(a.old_value::jsonb)='object' THEN a.old_value::jsonb ELSE '{}'::jsonb END) j
  WHERE j.key IN ('conversation_id','reservation_id','evidence_id','state','status','review_status','pending_action','last_question_code','amount_cop','amount_paid_cop','missing_cop','result','reason','detail','handoff_id')) AS old_filtered,
 (SELECT jsonb_object_agg(j.key,j.value) FROM jsonb_each(CASE WHEN jsonb_typeof(a.new_value::jsonb)='object' THEN a.new_value::jsonb ELSE '{}'::jsonb END) j
  WHERE j.key IN ('conversation_id','reservation_id','evidence_id','state','status','review_status','pending_action','last_question_code','amount_cop','amount_paid_cop','missing_cop','result','reason','detail','handoff_id')) AS new_filtered,
 CASE WHEN action IN ('HANDOFF_CREATED','RESERVATION_STATUS_CHANGED','CONVERSATION_STATE_TRANSITION','PAYMENT_EVIDENCE_ACCEPTED','RESERVATION_PAYMENT_PARTIAL') THEN reason END AS reason
FROM selected a ORDER BY created_at,id;
\echo 'IA en los flujos 208/209: no extracción bancaria cruda'
SELECT id, conversation_id, task, created_at, request_id, success, validation_status,
 parsed_output->>'primary_intent' AS primary_intent, parsed_output->>'requested_action' AS requested_action,
 parsed_output->>'handoff_reason' AS handoff_reason
FROM ai_execution WHERE conversation_id IN (208,209) ORDER BY created_at,id;
\echo 'Fechas y hora reales, y confirmación incorrecta: mensajes concretos sin datos bancarios'
SELECT id, conversation_id, created_at, content#>>'{text,body}' AS body
FROM message WHERE id IN (6899,6901,6908,6913,6915) ORDER BY id;
\echo 'Outbox con código inferido, nunca cuerpo/caption'
WITH templates AS (
 SELECT k.id,k.code,k.version,k.status,k.created_at,k.answer_template,
 k.answer_template ~ '\{[A-Za-z_][A-Za-z_0-9]*\}' AS has_variables,
 (SELECT string_agg(replace(replace(replace(f.part,chr(92),chr(92)||chr(92)),'%',chr(92)||'%'),'_',chr(92)||'_'),'%' ORDER BY f.position)
  FROM regexp_split_to_table(k.answer_template,'\{[A-Za-z_][A-Za-z_0-9]*\}') WITH ORDINALITY f(part,position)) AS pattern
 FROM knowledge_entry k
), bodies AS (
 SELECT o.*, CASE WHEN message_kind='DOCUMENT' THEN payload#>>'{document,caption}' ELSE payload#>>'{text,body}' END AS body
 FROM outbox o WHERE conversation_id IN (196,197,208,209) AND created_at >= '2026-10-02 00:00:00+00'
)
SELECT o.id,outbox_message.id AS outbound_message_id,o.conversation_id,o.message_id AS trigger_message_id,o.created_at,o.status,o.sent_at,
 coalesce(jsonb_agg(jsonb_build_object('code',k.code,'version',k.version,'status_now',k.status) ORDER BY k.code,k.version) FILTER(WHERE k.id IS NOT NULL),'[]'::jsonb) AS inferred_templates
FROM bodies o
LEFT JOIN message outbox_message ON outbox_message.conversation_id=o.conversation_id AND outbox_message.direction='OUTBOUND'
 AND outbox_message.content::jsonb=o.payload::jsonb
LEFT JOIN templates k ON k.created_at<=o.created_at AND
 ((NOT k.has_variables AND o.body=k.answer_template) OR (k.has_variables AND o.body LIKE k.pattern ESCAPE E'\\'))
GROUP BY o.id,outbox_message.id,o.conversation_id,o.message_id,o.created_at,o.status,o.sent_at ORDER BY o.created_at,o.id;
ROLLBACK;
