-- workflow_type: which workflow produced this job (explorer | exploiter | main | web)
ALTER TABLE jobs ADD COLUMN workflow_type TEXT;

CREATE INDEX IF NOT EXISTS idx_jobs_workflow_type ON jobs(workflow_type);
