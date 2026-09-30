def forward_migration():
    sql = "CREATE TABLE system_telemetry (id BIGSERIAL PRIMARY KEY, cpu REAL NOT NULL);"
    return sql
