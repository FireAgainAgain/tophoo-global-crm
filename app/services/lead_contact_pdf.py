"""Short-lived subprocess for text extraction from a bounded public PDF."""
import json
import sys
from app.services.lead_contact_scan import pdf_contacts

if __name__ == '__main__':
    content = sys.stdin.buffer.read(2_000_001)
    if len(content) > 2_000_000:
        raise ValueError('PDF too large')
    rows = pdf_contacts(content, sys.argv[1])
    sys.stdout.buffer.write(json.dumps(rows, ensure_ascii=False).encode('utf-8'))
