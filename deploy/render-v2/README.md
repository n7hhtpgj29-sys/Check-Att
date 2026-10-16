# Attendance V2 staging

Create a new Render service from feature/v2-vps-migration, never change main or the production service. Supabase schema attendance_v2 is ready. Next: implement isolated app and collector, connect DATABASE_URL privately, verify health, then configure 08:15 and 20:15 scheduled jobs. Do not send LINE yet.
