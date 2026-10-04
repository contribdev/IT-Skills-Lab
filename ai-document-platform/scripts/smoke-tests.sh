#!/bin/bash
# End-to-end smoke test for the AI Document Intelligence Platform.
# Usage: ./scripts/smoke-test.sh

set -e

NODE_IP=$(kubectl get nodes -o jsonpath='{.items[0].status.addresses[?(@.type=="InternalIP")].address}')
API="http://127.0.0.1:8080"

echo "=== Clean state ==="
PGPASSWORD=admin123 psql -h $NODE_IP -p 30432 -U app -d documents -c 'DELETE FROM documents;' > /dev/null
rclone delete local:documents/originals/ 2>/dev/null || true
rclone delete local:documents/extracted/ 2>/dev/null || true
rclone delete local:documents/results/ 2>/dev/null || true
curl -s -u app:admin123 -X DELETE http://localhost:15672/api/queues/%2F/ocr.queue/contents > /dev/null
curl -s -u app:admin123 -X DELETE http://localhost:15672/api/queues/%2F/llm.queue/contents > /dev/null

echo "=== Creating document ==="
DOC_ID=$(curl -s -X POST $API/documents \
  -F "file=@/tmp/test.pdf;type=application/pdf" | jq -r '.id')
echo "DOC_ID: $DOC_ID"

echo "=== Waiting for processing (max 120s) ==="
for i in $(seq 1 60); do
    STATUS=$(curl -s $API/documents/$DOC_ID | jq -r '.status')
    echo "  [$i/60] status: $STATUS"
    if [ "$STATUS" = "completed" ] || [ "$STATUS" = "failed" ]; then
        break
    fi
    sleep 2
done

if [ "$STATUS" != "completed" ]; then
    echo "FAILED: status=$STATUS"
    curl -s $API/documents/$DOC_ID/result | jq .
    exit 1
fi

echo "=== Result ==="
curl -s $API/documents/$DOC_ID/result | jq '.result | {document_type, summary, confidence}'

echo "=== Files in S3 ==="
rclone ls local:documents/originals/ local:documents/extracted/ local:documents/results/

echo "=== SUCCESS ==="