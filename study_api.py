"""Account-owned revision workspace. No proprietary publisher content."""
import copy
import json
import datetime
import re


def validate_workspace(value):
    if not isinstance(value, dict):
        raise ValueError('Workspace must be an object.')
    if len(json.dumps(value)) > 900_000:
        raise ValueError('Workspace is too large. Export older notes first.')
    result = {}
    schemas = {
        'notes': {'id':80,'title':160,'subject':80,'board':80,'body':30000,'topic':160},
        'sessions': {'id':80,'title':160,'subject':80,'date':10,'time':5},
        'exams': {'id':80,'subject':80,'date':10,'board':80},
        'attempts': {'id':80,'question':80,'topic':160,'subject':80,'answer':8000,'date':40},
    }
    for key, schema in schemas.items():
        rows = value.get(key, [])
        if not isinstance(rows, list) or len(rows) > 1000:
            raise ValueError(f'{key} must be a list with at most 1,000 items.')
        cleaned = []
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError('Invalid workspace record.')
            item = {field:str(row.get(field,'')).strip()[:limit] for field,limit in schema.items()}
            if key in ('sessions','exams'):
                try: datetime.date.fromisoformat(item['date'])
                except ValueError: raise ValueError('Use a valid study or exam date.')
            if key == 'sessions' and item['time'] and not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d',item['time']):
                raise ValueError('Use a valid session time.')
            for field in ('marks','total','minutes'):
                if field in row:
                    try: item[field] = max(0,min(10000,int(row[field])))
                    except (ValueError,TypeError,OverflowError): raise ValueError('Invalid number.')
            for field in ('done','bookmarked'):
                if field in row: item[field] = bool(row[field])
            if item.get('marks',0) > item.get('total',10000):
                raise ValueError('Marks cannot exceed the total.')
            cleaned.append(item)
        result[key] = cleaned
    for key in ('bookmarks','completed'):
        rows = value.get(key,[])
        if not isinstance(rows,list) or len(rows)>1000: raise ValueError('Invalid saved topics.')
        result[key] = list(dict.fromkeys(str(x)[:80] for x in rows))
    return result


def register_study_routes(app, require_auth, current_username, student_record, save_student, lock):
    from flask import jsonify, request
    @app.route('/api/study/workspace', methods=['GET','PUT'])
    @require_auth
    def revision_workspace():
        with lock:
            username = current_username()
            _,_,record = student_record(username)
            if not record: return jsonify(error='Account not found.'),404
            if request.method == 'GET':
                return jsonify(workspace=record['student'].get('revision_workspace', {}))
            payload = request.get_json(silent=True)
            try: workspace = validate_workspace(payload)
            except ValueError as error: return jsonify(error=str(error)),400
            student = copy.deepcopy(record['student'])
            student['revision_workspace'] = workspace
            if not save_student(username, student):
                return jsonify(error='Could not save. Your changes are still on screen; retry.'),503
            return jsonify(ok=True, workspace=workspace)
