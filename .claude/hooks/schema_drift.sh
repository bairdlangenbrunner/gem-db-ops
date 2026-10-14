#!/bin/sh
# SessionStart hook: at most once a week, compare the live GEM Postgres schema
# with docs/gem_schema.dbml. On drift, regenerate the file and tell the session
# what changed so it can sync the code and docs. Silent when the schema matches,
# when GEM_READONLY_DB_URL is unset, or when the database can't be reached.
cd "${CLAUDE_PROJECT_DIR:-$(dirname "$0")/../..}" || exit 0
stamp="$(git rev-parse --git-dir 2>/dev/null)/schema_check_stamp"
if [ -f "$stamp" ] && [ -z "$(find "$stamp" -mtime +6)" ]; then
    exit 0
fi
[ -n "$GEM_READONLY_DB_URL" ] || exit 0

changes=$(python schema_dbml.py --check 2>/dev/null)
case $? in
    0) touch "$stamp"; exit 0 ;;
    1) ;;
    *) exit 0 ;;  # no connection: try again next session
esac
python schema_dbml.py 2>/dev/null && touch "$stamp"
cat <<MSG
Schema drift: the live GEM Postgres no longer matches docs/gem_schema.dbml, so this hook regenerated it (uncommitted). Changes:
$changes

Before other database work, sync the repo to the new schema: give new tables a home in schema_dbml.py GROUPS, add new lookup tables to gem_query.REFERENCE_TABLES and new project types to gem_query.PROJECT_TYPES, check whether any pull reads a dropped or renamed column, and update CLAUDE.md and docs/ALL_FIELDS_STATUS.md where they describe the changed tables. Tell the user what drifted.
MSG
