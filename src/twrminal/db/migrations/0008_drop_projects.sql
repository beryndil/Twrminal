-- v0.2.9 teardown: projects were the wrong primitive.
--
-- Tags carry everything projects would have carried (memories land
-- in v0.2.7, default working_dir + model land in v0.2.10). One
-- primitive, not two. Pinned tag = "project".
--
-- Existing sessions are wiped per Dave's call — no production data
-- existed at the time of this migration. Messages + tool_calls
-- cascade via their ON DELETE FK. session_tags cascade too (and
-- carry nothing worth keeping since the sessions are gone).
--
-- tag_memories and sessions.session_instructions from 0007 stay;
-- only the projects half of 0007 is being unwound.

DELETE FROM sessions;

DROP INDEX IF EXISTS idx_sessions_project;

ALTER TABLE sessions DROP COLUMN project_id;

DROP TABLE IF EXISTS projects;
