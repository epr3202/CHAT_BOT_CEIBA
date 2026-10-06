BEGIN READ ONLY;
\d ai_execution
SELECT task, prompt_version, count(*) AS total,
 count(*) FILTER (WHERE error_reason = 'INVALID_JSON') AS invalid_json,
 round(100.0 * count(*) FILTER (WHERE error_reason = 'INVALID_JSON') / count(*), 2) AS percentage,
 min(length(raw_output)) FILTER (WHERE error_reason = 'INVALID_JSON') AS failed_min_length,
 percentile_cont(0.5) WITHIN GROUP (ORDER BY length(raw_output)) FILTER (WHERE error_reason = 'INVALID_JSON') AS failed_median_length,
 max(length(raw_output)) FILTER (WHERE error_reason = 'INVALID_JSON') AS failed_max_length
FROM ai_execution WHERE created_at >= now() - interval '30 days'
GROUP BY task, prompt_version ORDER BY task, prompt_version;
ROLLBACK;
