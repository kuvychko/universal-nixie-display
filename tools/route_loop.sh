#!/bin/sh
# Route with retries: nets that fail in a pass are routed first in the next one (no rip-up in
# route_pcb.py, so order is the lever). Usage: sh tools/route_loop.sh [passes]
cd "$(dirname "$0")/.." || exit 1
echo "[]" > build/promote.json
i=0
while [ $i -lt "${1:-6}" ]; do
    i=$((i + 1))
    uv run tools/route_pcb.py build/geom.json build/routes.json build/promote.json > build/route.log 2>&1
    failed=$(python -c "import json; print(json.dumps(json.load(open('build/routes.json'))['failed']))")
    echo "pass $i: failed $failed"
    [ "$failed" = "[]" ] && exit 0
    python -c "
import json
p = json.load(open('build/promote.json')); f = json.load(open('build/routes.json'))['failed']
json.dump(f + [n for n in p if n not in f], open('build/promote.json', 'w'))"
done
exit 1
