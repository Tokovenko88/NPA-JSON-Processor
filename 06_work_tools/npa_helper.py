#!/usr/bin/env python3
"""
NPA JSON Processor - Helper Tools
"""

import json
import os
from datetime import datetime, timedelta

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def load_json(path):
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)

def save_json(path, data):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def date_add_days(date_str, days):
    d = datetime.strptime(date_str, '%d.%m.%Y')
    d += timedelta(days=days)
    return d.strftime('%d.%m.%Y')

def get_active_revision(item):
    for rev in item.get('revisions', []):
        if rev.get('valid_to') is None:
            return rev
    return item['revisions'][-1] if item['revisions'] else None

def close_revision_and_create_new(item, new_date, mod_type, modified_by_id, body=None, highlights=None):
    active = get_active_revision(item)
    if active:
        active['valid_to'] = date_add_days(new_date, -1)
    
    new_rev = {
        'valid_from': new_date,
        'valid_to': None,
        'modified_by_id': modified_by_id,
        'mod_type': mod_type,
        'body': body if body is not None else active['body'] if active else [],
    }
    if highlights:
        new_rev['highlights'] = highlights
    item['revisions'].append(new_rev)
    return new_rev

if __name__ == '__main__':
    print("NPA JSON Processor - Helper Tools")
    print("Available functions:")
    print("  - load_json(path)")
    print("  - save_json(path, data)")
    print("  - date_add_days(date_str, days)")
    print("  - get_active_revision(item)")
    print("  - close_revision_and_create_new(item, new_date, mod_type, modified_by_id, body=None, highlights=None)")
