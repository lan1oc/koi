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
rows, err := db.Query("PRAGMA table_info(agent_memories)")
if err != nil { panic(err) }
defer rows.Close()
fmt.Println("=== agent_memories columns ===")
for rows.Next() {
var cid int; var name, typ string; var notnull int; var dflt sql.NullString; var pk int
rows.Scan(&cid, &name, &typ, &notnull, &dflt, &pk)
fmt.Printf("  %d: %s %s (notnull=%d pk=%d)\n", cid, name, typ, notnull, pk)
}
rows2, _ := db.Query("PRAGMA table_info(tip_items)")
defer rows2.Close()
fmt.Println("=== tip_items columns ===")
for rows2.Next() {
var cid int; var name, typ string; var notnull int; var dflt sql.NullString; var pk int
rows2.Scan(&cid, &name, &typ, &notnull, &dflt, &pk)
fmt.Printf("  %d: %s %s (notnull=%d pk=%d)\n", cid, name, typ, notnull, pk)
}
}
