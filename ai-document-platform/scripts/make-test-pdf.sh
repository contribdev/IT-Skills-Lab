#!/bin/bash
# Generate a test PDF for uploads.

set -e

cd "$(dirname "$0")/.."

uv run --project apps/api python << 'EOF'
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4

output = "/tmp/test.pdf"
c = canvas.Canvas(output, pagesize=A4)
c.drawString(100, 750, "Test Document for OCR")
c.drawString(100, 730, "Invoice #12345")
c.drawString(100, 710, "Amount: 1234.56 RUB")
c.drawString(100, 690, "Date: 2026-10-03")
c.showPage()
c.save()
print(f"Created: {output}")
EOF

ls -la /tmp/test.pdf