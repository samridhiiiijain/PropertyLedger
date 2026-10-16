-- Run this as a database administrator after the tables are initialized.
-- Replace the role name if your deployment uses a different application role.

REVOKE CREATE ON SCHEMA public FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM propertyledger_query;
GRANT CONNECT ON DATABASE propertyledger TO propertyledger_query;
GRANT USAGE ON SCHEMA public TO propertyledger_query;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO propertyledger_query;

ALTER DEFAULT PRIVILEGES FOR ROLE propertyledger_admin IN SCHEMA public
GRANT SELECT ON TABLES TO propertyledger_query;
