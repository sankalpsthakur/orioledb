#!/bin/bash
# Run the #1313 differential matrix against the server named by PGHOST/PGPORT/
# PGDATABASE and summarise it.
#
#   run_matrix.sh LABEL OUTDIR [--setup]
#
# --setup loads the tables first (once per cluster).  Writes OUTDIR/matrix-LABEL.out
# (raw psql output), OUTDIR/wrong-LABEL.txt (the WRONG case ids, sorted) and prints
# the summary.  Exit status is 0 unless the harness itself broke (psql error,
# timeout, or a case count other than 260).
set -u

label=$1
outdir=$2
setup=${3:-}
here=$(cd "$(dirname "$0")" && pwd)
mkdir -p "$outdir"

python3 "$here/gen_matrix.py" "$outdir" ${HEAP_ONLY:+--heap-only} > /dev/null

if [ "$setup" = "--setup" ]; then
	timeout 300 psql -X -q -At -v ON_ERROR_STOP=1 -f "$outdir/setup_matrix.sql" || { echo "setup failed"; exit 1; }
fi

start=$(date +%s)
timeout 900 psql -X -q -At -v ON_ERROR_STOP=0 -f "$outdir/matrix.sql" > "$outdir/matrix-$label.out" 2>&1
rc=$?
end=$(date +%s)

total=$(grep -c '^CASE ' "$outdir/matrix-$label.out")
ok=$(grep -c '^CASE .* OK ' "$outdir/matrix-$label.out")
wrong=$(grep -c '^CASE .* WRONG ' "$outdir/matrix-$label.out")
errors=$(grep -ciE '^(ERROR|psql:)' "$outdir/matrix-$label.out")
grep '^CASE .* WRONG ' "$outdir/matrix-$label.out" | sed 's/ WRONG .*//' | sort > "$outdir/wrong-$label.txt"

echo "=== matrix [$label]: $wrong wrong, $ok ok, $total cases, $errors errors, psql rc=$rc, $((end - start)) s"
echo "--- plans used (one per table/index/direction):"
awk '/^PARALLEL-PLAN /{p=""} /^PLAN /{p=$0} /index (only )?scan of/{if (p != "") print p ": " $0}' "$outdir/matrix-$label.out" | sort -u
echo "--- wrong cases:"
grep '^CASE .* WRONG ' "$outdir/matrix-$label.out" || echo "(none)"
echo "--- parallel probe (exploratory, not a gate):"
grep -E '^PARALLEL ' "$outdir/matrix-$label.out" || echo "(no output)"
awk '/^PLAN /{p=""} /^PARALLEL-PLAN /{p=$0} /Parallel|Gather|scan of/{if (p != "") print p ": " $0}' "$outdir/matrix-$label.out" | head -20
if [ "$errors" != 0 ]; then
	echo "--- errors:"
	grep -iE '^(ERROR|psql:)' "$outdir/matrix-$label.out" | head -20
fi

[ "$rc" = 0 ] && [ "$errors" = 0 ] && [ "$total" = 260 ] || { echo "harness problem (rc=$rc errors=$errors total=$total)"; exit 1; }
exit 0
