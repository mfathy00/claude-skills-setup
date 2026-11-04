
CREATE TABLE settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE tasks(id TEXT PRIMARY KEY, spec TEXT NOT NULL, state TEXT NOT NULL,
 created REAL NOT NULL, updated REAL NOT NULL, owner TEXT, attempt TEXT,
 approval TEXT, result_ref TEXT, detail TEXT, accepted TEXT);
CREATE TABLE dependencies(task_id TEXT, depends_on TEXT, PRIMARY KEY(task_id,depends_on));
CREATE TABLE subscriptions(task_id TEXT, kind TEXT, PRIMARY KEY(task_id,kind));
CREATE TABLE artifacts(ref TEXT PRIMARY KEY, body BLOB NOT NULL, size INTEGER NOT NULL);
CREATE TABLE events(seq INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT NOT NULL,
 external_id TEXT NOT NULL, kind TEXT NOT NULL, ref TEXT NOT NULL, created REAL NOT NULL,
 UNIQUE(source,external_id));
CREATE TABLE inbox(task_id TEXT, event_seq INTEGER, PRIMARY KEY(task_id,event_seq));
CREATE TABLE attempts(id TEXT PRIMARY KEY, task_id TEXT NOT NULL, owner TEXT NOT NULL,
 started REAL NOT NULL, ended REAL, status TEXT NOT NULL, reserved_cents INTEGER NOT NULL, context_ref TEXT NOT NULL);
CREATE TABLE audit(seq INTEGER PRIMARY KEY AUTOINCREMENT, at REAL NOT NULL,
 task_id TEXT, action TEXT NOT NULL, detail TEXT NOT NULL);
CREATE INDEX task_state ON tasks(state,created);
