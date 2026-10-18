"""A scripted fake wasichai Core for the tests: metadata routes plus in-memory records.

Adapted from wasichai's examples/gis-sample/perene/test_apply.py. Test helper only.
"""
import json
import re
import threading
import urllib.parse
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

RECORDS = re.compile(r"^/api/objects/([a-z0-9_]+)/records$")
RECORD = re.compile(r"^/api/objects/([a-z0-9_]+)/records/([0-9a-f-]+)$")
FIELDS = re.compile(r"^/api/metadata/objects/([a-z0-9_]+)/fields$")
OBJECT = re.compile(r"^/api/objects/([a-z0-9_]+)$")


def _meta(label, plural_label=None, description=None, enabled=True):
    """An object's own metadata as Core stores it: a blank plural is the label."""
    return {"label": label, "pluralLabel": (plural_label or "").strip() or label, "description": description,
            "enabled": enabled}


class FakeCoreHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # keep test output quiet

    def _body(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b""
        return json.loads(raw) if raw else None

    def _handle(self, method):
        server = self.server
        body = self._body()
        with server.lock:
            server.requests.append((method, self.path, self.headers.get("Authorization"), body))
            status, payload = server.script(method, self.path, body)
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        if payload is not None:
            self.wfile.write(json.dumps(payload).encode("utf-8"))

    def do_GET(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")

    def do_PUT(self):
        self._handle("PUT")

    def do_DELETE(self):
        self._handle("DELETE")


class FakeCore:
    """existing_objects/existing_relationships mark names that 409 on create; records live in memory."""

    def __init__(self, existing_objects=(), existing_relationships=(), fail_on_post_object=None,
                 fail_put=False, fail_put_status=500, login_response=None, fail_on_record=None, existing_fields=None,
                 fail_on_update=None, fail_on_delete=None, object_rules=None, fail_object_put=None, object_meta=None, fail_record_after=None):
        self.existing_objects = set(existing_objects)
        # object name -> its object-level rules ({"indexes", "appendOnly"}), as Core stores them; none by default
        self.object_rules = {n: dict((object_rules or {}).get(n, {})) for n in self.existing_objects}
        # object name -> {"label", "pluralLabel", "description", "enabled"}; the name as label by default
        self.object_meta = {n: {**_meta(n, n), **(object_meta or {}).get(n, {})} for n in self.existing_objects}
        self.fail_object_put = fail_object_put  # PUT /api/objects/{name} -> this status
        self.existing_fields = existing_fields or {}  # object name -> list of {"name", "enumOptions"?}
        self.existing_relationships = set(existing_relationships)
        self.fail_on_post_object = fail_on_post_object  # object name -> triggers 500
        self.fail_put = fail_put  # PUT .../fields/... -> fail_put_status
        self.fail_put_status = fail_put_status
        self.login_response = login_response  # override the default {"token": "t"}
        self.fail_record_after = fail_record_after or {}  # object name -> record POSTs that succeed before the rest 400
        self.fail_on_record = fail_on_record  # object name -> its record POSTs answer 400
        self.fail_on_update = fail_on_update  # object name -> its record PUTs answer 400
        self.fail_on_delete = fail_on_delete  # object name -> its record DELETEs answer 409
        self.records = {}  # object name -> list of {"id", "attributes"}
        self.requests = []
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), FakeCoreHandler)
        self.server.requests = self.requests
        self.server.script = self._script
        self.server.lock = threading.Lock()
        self.port = self.server.server_address[1]
        self.base_url = f"http://127.0.0.1:{self.port}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def stop(self):
        self.server.shutdown()
        self.server.server_close()

    def add_record(self, object_name, attributes, geometries=None):
        record = {"id": str(uuid.uuid4()), "attributes": dict(attributes)}
        if geometries is not None:
            record["geometries"] = dict(geometries)
        self.records.setdefault(object_name, []).append(record)
        return record

    def _records(self, method, path, query, body):
        name = RECORDS.match(path).group(1)
        if method == "POST":
            if self.fail_on_record == name:
                return 400, {"detail": "Invalid option", "errors": [{"field": "uso", "message": "boom-record"}]}
            if name in self.fail_record_after and len(self.records.get(name, [])) >= self.fail_record_after[name]:
                return 400, {"detail": "Invalid option", "errors": [{"field": "piso", "message": "boom-after"}]}
            return 201, self.add_record(name, body["attributes"], body.get("geometries"))
        params = {k: v[0] for k, v in urllib.parse.parse_qs(query).items()}
        page = int(params.pop("page", 0))
        size = int(params.pop("size", 25))
        params.pop("sort", None)
        params.pop("dir", None)
        rows = [r for r in self.records.get(name, []) if all(str(r["attributes"].get(k)) == v for k, v in params.items())]
        total_pages = (len(rows) + size - 1) // size
        return 200, {
            "content": rows[page * size:(page + 1) * size],
            "page": page,
            "size": size,
            "totalElements": len(rows),
            "totalPages": total_pages,
        }

    def _update(self, path, body):
        """A record's PUT: Core replaces every field with what is sent."""
        name, record_id = RECORD.match(path).groups()
        if self.fail_on_update == name:
            return 400, {"detail": "Invalid option", "errors": [{"field": "tipo_via", "message": "boom-update"}]}
        record = next((r for r in self.records.get(name, []) if r["id"] == record_id), None)
        if record is None:
            return 404, {"detail": "not found"}
        record["attributes"] = dict(body["attributes"])
        if "geometries" in body:
            record["geometries"] = dict(body["geometries"])
        return 200, record

    def _delete(self, path):
        """A record's DELETE: it leaves the records."""
        name, record_id = RECORD.match(path).groups()
        if self.fail_on_delete == name:
            return 409, {"detail": "In use", "errors": [{"field": "id", "message": "boom-delete"}]}
        records = self.records.get(name, [])
        if not any(r["id"] == record_id for r in records):
            return 404, {"detail": "not found"}
        self.records[name] = [r for r in records if r["id"] != record_id]
        return 204, None

    def _object(self, name):
        """An object as GET /api/objects lists it: indexes only when some are declared, appendOnly always."""
        rules = self.object_rules.get(name, {})
        obj = {"name": name, **self.object_meta.get(name, _meta(name)), "appendOnly": bool(rules.get("appendOnly"))}
        if rules.get("indexes"):
            obj["indexes"] = rules["indexes"]
        return obj

    def _update_object(self, path, body):
        """An object's PUT, as MetadataService.updateObject: label required and overwritten; pluralLabel left out or
        blank becomes the label, description left out goes null, enabled left out is true; a rule left out (or null)
        stays as it is."""
        name = OBJECT.match(path).group(1)
        if self.fail_object_put:
            return self.fail_object_put, {"message": "boom-object-put"}
        if name not in self.existing_objects:
            return 404, {"detail": "not found"}
        if not (body or {}).get("label"):
            return 400, {"detail": "label is required"}
        enabled = body.get("enabled")
        self.object_meta[name] = _meta(body["label"], body.get("pluralLabel"), body.get("description"),
                                       True if enabled is None else enabled)
        for key in ("indexes", "appendOnly"):
            if body.get(key) is not None:
                self.object_rules[name][key] = body[key]
        return 200, self._object(name)

    def _script(self, method, full_path, body):
        path, _, query = full_path.partition("?")
        if path == "/api/auth/login" and method == "POST":
            if self.login_response is not None:
                return 200, self.login_response
            return 200, {"token": "t"}
        if RECORDS.match(path) and method in ("GET", "POST"):
            return self._records(method, path, query, body)
        if RECORD.match(path) and method == "PUT":
            return self._update(path, body)
        if RECORD.match(path) and method == "DELETE":
            return self._delete(path)
        if path == "/api/objects" and method == "GET":
            return 200, [self._object(n) for n in self.existing_objects]
        if path == "/api/objects" and method == "POST":
            name = body["name"]
            if self.fail_on_post_object and name == self.fail_on_post_object:
                return 500, {"message": "boom"}
            if name in self.existing_objects:
                return 409, {"message": "exists"}
            self.existing_objects.add(name)
            self.object_rules[name] = {k: body[k] for k in ("indexes", "appendOnly") if k in body}
            self.object_meta[name] = _meta(body["label"], body.get("pluralLabel"), body.get("description"))
            return 201, {"name": name}
        if OBJECT.match(path) and method == "PUT":
            return self._update_object(path, body)
        if path == "/api/relationships" and method == "GET":
            return 200, [{"name": n} for n in sorted(self.existing_relationships)]
        if path == "/api/relationships" and method == "POST":
            name = body["name"]
            if name in self.existing_relationships:
                return 409, {"message": "exists"}
            return 201, {"name": name}
        fields = FIELDS.match(path)
        if fields and method == "GET":
            return 200, self.existing_fields.get(fields.group(1), [])
        if fields and method == "POST":
            return 201, {"name": body["name"]}
        if path.startswith("/api/metadata/objects/") and method == "PUT":
            if self.fail_put:
                return self.fail_put_status, {"message": "boom-put"}
            return 200, {"required": True}
        if path.startswith("/api/metadata/objects/") and "/fields/" in path and method == "DELETE":
            return 204, None
        if path.startswith("/api/relationships/") and method == "DELETE":
            return 204, None
        if path.startswith("/api/objects/") and method == "DELETE":
            # Core keeps an append-only object's table until its rule is switched off (ADR-040)
            if self.object_rules.get(path.rsplit("/", 1)[1], {}).get("appendOnly"):
                return 409, {"detail": "append-only: switch appendOnly off before deleting it"}
            return 204, None
        return 500, {"message": "boom"}
