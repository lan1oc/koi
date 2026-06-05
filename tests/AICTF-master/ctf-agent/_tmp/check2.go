package main

import (
"database/sql"
"fmt"
_ "modernc.org/sqlite"
)

func main() {
db, err := sql.Open("sqlite", `D:\AI\AICTF\ctf-agent\backend\data\ctf-agent.db`)
if err != nil { panic(err) }
defer db.Close()
// Simulate the fixed migration
migrations := []string{
"ALTER TABLE agent_memories ADD COLUMN tags TEXT DEFAULT '[]'",
"ALTER TABLE agent_memories ADD COLUMN embedding BLOB",
}
for _, m := range migrations {
_, err := db.Exec(m)
if err != nil {
fmt.Printf("  migration: %s => %v\n", m, err)
} else {
fmt.Printf("  migration: %s => OK\n", m)
}
}
// Now check schema
rows, _ := db.Query("PRAGMA table_info(agent_memories)")
defer rows.Close()
fmt.Println("\n=== agent_memories columns (after fix) ===")
for rows.Next() {
var cid int; var name, typ string; var notnull int; var dflt sql.NullString; var pk int
rows.Scan(&cid, &name, &typ, &notnull, &dflt, &pk)
fmt.Printf("  %d: %s %s\n", cid, name, typ)
}
}
