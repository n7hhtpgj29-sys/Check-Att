-- Attendance V2 schema for Supabase PostgreSQL
-- Apply manually in Supabase SQL Editor after review.
-- Creates only attendance_v2 schema; does not alter public tables.
BEGIN;
CREATE SCHEMA IF NOT EXISTS attendance_v2;
CREATE TABLE IF NOT EXISTS attendance_v2.departments (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code text NOT NULL UNIQUE CHECK (code ~ '^[A-Z0-9_-]{1,24}$'),
  name text NOT NULL,
  active boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS attendance_v2.employees (
  employee_no text PRIMARY KEY,
  full_name text NOT NULL,
  department_id bigint NOT NULL REFERENCES attendance_v2.departments(id),
  shift text NOT NULL CHECK (shift IN ('D','N')),
  active boolean NOT NULL DEFAULT true,
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS employees_department_shift_idx ON attendance_v2.employees(department_id,shift,active);
CREATE TABLE IF NOT EXISTS attendance_v2.schedule_settings (
  department_id bigint NOT NULL REFERENCES attendance_v2.departments(id),
  shift text NOT NULL CHECK (shift IN ('D','N')),
  enabled boolean NOT NULL DEFAULT false,
  run_time time NOT NULL,
  timezone text NOT NULL DEFAULT 'Asia/Bangkok' CHECK (timezone='Asia/Bangkok'),
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (department_id,shift)
);
CREATE TABLE IF NOT EXISTS attendance_v2.attendance_runs (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  department_id bigint NOT NULL REFERENCES attendance_v2.departments(id),
  shift text NOT NULL CHECK (shift IN ('D','N')),
  work_date date NOT NULL,
  trigger_type text NOT NULL CHECK (trigger_type IN ('manual','scheduled')),
  status text NOT NULL DEFAULT 'running' CHECK (status IN ('running','completed','partial','failed')),
  started_at timestamptz NOT NULL DEFAULT now(),
  finished_at timestamptz,
  total_employees integer NOT NULL DEFAULT 0 CHECK(total_employees>=0),
  missing_count integer NOT NULL DEFAULT 0 CHECK(missing_count>=0),
  error_count integer NOT NULL DEFAULT 0 CHECK(error_count>=0),
  error_message text,
  -- one scheduled attempt per department, shift, work date; manual runs may repeat
  scheduled_key text UNIQUE
);
CREATE INDEX IF NOT EXISTS attendance_runs_lookup_idx ON attendance_v2.attendance_runs(department_id,shift,work_date DESC,started_at DESC);
CREATE TABLE IF NOT EXISTS attendance_v2.attendance_results (
  run_id bigint NOT NULL REFERENCES attendance_v2.attendance_runs(id) ON DELETE CASCADE,
  employee_no text NOT NULL REFERENCES attendance_v2.employees(employee_no),
  status text NOT NULL CHECK(status IN ('SCAN_FOUND','NO_SCAN_IN_WINDOW','QUERY_ERROR','INCOMPLETE')),
  scan_in timestamptz,
  queried_at timestamptz NOT NULL DEFAULT now(),
  detail text,
  PRIMARY KEY (run_id,employee_no)
);
CREATE INDEX IF NOT EXISTS attendance_results_status_idx ON attendance_v2.attendance_results(run_id,status);
-- Restricted schema: do not expose employee data through Supabase client roles.
REVOKE ALL ON SCHEMA attendance_v2 FROM PUBLIC, anon, authenticated;
REVOKE ALL ON ALL TABLES IN SCHEMA attendance_v2 FROM PUBLIC, anon, authenticated;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA attendance_v2 FROM PUBLIC, anon, authenticated;
ALTER DEFAULT PRIVILEGES IN SCHEMA attendance_v2 REVOKE ALL ON TABLES FROM PUBLIC, anon, authenticated;
ALTER DEFAULT PRIVILEGES IN SCHEMA attendance_v2 REVOKE ALL ON SEQUENCES FROM PUBLIC, anon, authenticated;
COMMIT;
