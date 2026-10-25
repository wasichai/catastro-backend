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
ROLE = re.compile(r"^/api/roles/([A-Z0-9_]+)$")
ROLE_PERMISSIONS = re.compile(r"^/api/roles/([A-Z0-9_]+)/permissions$")
SERVICE_ACCOUNT = re.compile(r"^/api/service-accounts/([0-9a-f-]+)$")
MAP_VIEWS = re.compile(r"^/api/gis/objects/([a-z0-9_]+)/map-views$")
MAP_VIEW = re.compile(r"^/api/gis/objects/([a-z0-9_]+)/map-views/([a-z0-9_-]+)$")
LAYER = re.compile(r"^/api/gis/layers/([a-z0-9_]+)/([a-z0-9_]+)$")


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
            server.reasons.append((method, self.path, self.headers.get("X-Change-Reason")))
            status, payload = server.script(method, self.path, body)
        self.send_response(status)
        # bytes go as they are: GeoServer's WFS answers XML
        self.send_header("Content-Type", "application/xml" if isinstance(payload, bytes) else "application/json")
        self.end_headers()
        if isinstance(payload, bytes):
            self.wfile.write(payload)
        elif payload is not None:
            self.wfile.write(json.dumps(payload).encode("utf-8"))

    def do_GET(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")

    def do_PUT(self):
        self._handle("PUT")

    def do_PATCH(self):
        self._handle("PATCH")

    def do_DELETE(self):
        self._handle("DELETE")


class FakeCore:
    """existing_objects/existing_relationships mark names that 409 on create; records live in memory."""

    def __init__(self, existing_objects=(), existing_relationships=(), fail_on_post_object=None,
                 fail_put=False, fail_put_status=500, login_response=None, fail_on_record=None, existing_fields=None,
                 fail_on_update=None, fail_on_delete=None, object_rules=None, fail_object_put=None, object_meta=None, fail_record_after=None,
                 fail_on_role=None, fail_on_service_account=None, fail_on_record_body=None, fail_on_layer=None):
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
        self.fail_on_record_body = fail_on_record_body  # overrides the 400 body of fail_on_record (default boom-record)
        self.fail_on_update = fail_on_update  # object name -> its record PUTs and PATCHes answer 400
        self.fail_on_delete = fail_on_delete  # object name -> its record DELETEs answer 409
        self.records = {}  # object name -> list of {"id", "attributes"}
        self.fail_on_role = fail_on_role  # role name -> its POST /api/roles answers 500
        self.roles = {}  # role name -> {"name", "label", "permissions": [{"objectName", "action", "allowed"}]}
        self.fail_on_service_account = fail_on_service_account  # POST /api/service-accounts -> this status
        self.service_accounts = {}  # id -> ServiceAccountResponse without the secret
        self.map_views = {}  # (object, name) -> MapViewResponse, as wasichai-gis answers it
        self.layers = []  # (object, geometry, style) of every publish, in order
        self.unpublished = []  # (object, geometry) of every DELETE /api/gis/layers/..., in order
        # (object, geometry) -> the attribute columns GeoServer's feature type has, as DescribeFeatureType answers;
        # a pair in here is a published layer (GET /api/gis/layers says so). wfs_reachable False: the WFS is down
        self.layer_attributes = {}
        self.wfs_reachable = True
        self.bbox_queries = []  # (object, bbox, geometry) of every list with a bbox
        self.columns = {}  # object -> its attribute columns, for a feature type published from now on
        self.fail_on_layer = fail_on_layer  # POST /api/gis/layers/... -> this status (GeoServer down, say)
        self.requests = []
        self.reasons = []  # (method, path, X-Change-Reason header or None), one per request, parallel to requests
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), FakeCoreHandler)
        self.server.requests = self.requests
        self.server.reasons = self.reasons
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
                return 400, self.fail_on_record_body or {"detail": "Invalid option",
                                                         "errors": [{"field": "uso", "message": "boom-record"}]}
            if name in self.fail_record_after and len(self.records.get(name, [])) >= self.fail_record_after[name]:
                return 400, {"detail": "Invalid option", "errors": [{"field": "piso", "message": "boom-after"}]}
            return 201, self.add_record(name, body["attributes"], body.get("geometries"))
        params = {k: v[0] for k, v in urllib.parse.parse_qs(query).items()}
        page = int(params.pop("page", 0))
        size = int(params.pop("size", 25))
        params.pop("sort", None)
        params.pop("dir", None)
        # wasichai-gis's bbox (EPSG:4326) on the geometry it names: a vertex inside is enough here
        caja, geometria = params.pop("bbox", None), params.pop("geometry", None)
        rows = [r for r in self.records.get(name, []) if all(str(r["attributes"].get(k)) == v for k, v in params.items())]
        if caja is not None:
            x0, y0, x1, y1 = (float(v) for v in caja.split(","))
            self.bbox_queries.append((name, caja, geometria))
            rows = [r for r in rows if any(x0 <= x <= x1 and y0 <= y <= y1
                                           for anillo in ((r.get("geometries") or {}).get(geometria) or {}).get("coordinates", [])
                                           for x, y, *_ in anillo)]
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

    def _patch(self, path, body):
        """A record's PATCH: JSON-merge `attributes` (a null clears the key) and merge `geometries`."""
        name, record_id = RECORD.match(path).groups()
        if self.fail_on_update == name:
            return 400, {"detail": "Invalid option", "errors": [{"field": "tipo_via", "message": "boom-update"}]}
        record = next((r for r in self.records.get(name, []) if r["id"] == record_id), None)
        if record is None:
            return 404, {"detail": "not found"}
        for key, value in (body.get("attributes") or {}).items():
            if value is None:
                record["attributes"].pop(key, None)
            else:
                record["attributes"][key] = value
        if "geometries" in body:
            record.setdefault("geometries", {}).update(body["geometries"])
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
        obj = {"name": name, **self.object_meta.get(name, _meta(name)), "appendOnly": bool(rules.get("appendOnly")),
               "apiOnly": bool(rules.get("apiOnly"))}
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
        for key in ("indexes", "appendOnly", "apiOnly"):
            if body.get(key) is not None:
                self.object_rules[name][key] = body[key]
        return 200, self._object(name)

    def _roles(self, method, path, body):
        """Core's role routes, addressed by name: list, create, relabel and replace the permissions."""
        if path == "/api/roles" and method == "GET":
            return 200, list(self.roles.values())
        if path == "/api/roles" and method == "POST":
            name = body["name"]
            if name == self.fail_on_role:
                return 500, {"message": "boom-role"}
            if name in self.roles:
                return 409, {"detail": f"Role '{name}' already exists"}
            self.roles[name] = {"name": name, "label": body["label"], "permissions": []}
            return 201, self.roles[name]
        match = ROLE_PERMISSIONS.match(path) or ROLE.match(path)
        role = self.roles.get(match.group(1)) if match and method == "PUT" else None
        if role is None:
            return 404, {"detail": "no such role"}
        if ROLE_PERMISSIONS.match(path):
            role["permissions"] = [{**p, "allowed": p.get("allowed", True)} for p in body["permissions"]]
        else:
            role["label"] = body.get("label", role["label"])
        return 200, role

    def add_service_account(self, name, roles=(), enabled=True):
        account = {"id": str(uuid.uuid4()), "clientId": str(uuid.uuid4()), "name": name, "enabled": enabled,
                   "roles": list(roles)}
        self.service_accounts[account["id"]] = account
        return account

    def _service_accounts(self, method, path, body):
        """ServiceAccountController: list, create (the secret only in that answer), update roles. A name core already
        has is a 409, an unknown role a 400."""
        if path == "/api/service-accounts" and method == "GET":
            return 200, list(self.service_accounts.values())
        if path == "/api/service-accounts" and method == "POST":
            if self.fail_on_service_account:
                return self.fail_on_service_account, {"detail": "boom-service-account"}
            name = body["name"].strip().lower()
            if any(a["name"] == name for a in self.service_accounts.values()):
                return 409, {"detail": f"Service account '{name}' already exists"}
            unknown = [r for r in body.get("roles", []) if r not in self.roles]
            if unknown:
                return 400, {"detail": f"Unknown role {unknown[0]}"}
            return 201, {**self.add_service_account(name, body.get("roles", [])), "clientSecret": "secreto-" + name}
        match = SERVICE_ACCOUNT.match(path)
        account = self.service_accounts.get(match.group(1)) if match and method == "PUT" else None
        if account is None:
            return 404, {"detail": "no such service account"}
        if body.get("roles") is not None:
            account["roles"] = list(body["roles"])
        if body.get("enabled") is not None:
            account["enabled"] = body["enabled"]
        return 200, account

    def _gis(self, method, path, body):
        """wasichai-gis's map views (MapViewController) and layer publish (LayerController)."""
        match = MAP_VIEWS.match(path)
        if match and method == "POST":
            key = (match.group(1), body["name"])
            if key in self.map_views:
                return 409, {"detail": f"Map view '{body['name']}' already exists"}
            self.map_views[key] = {"id": str(uuid.uuid4()), "name": body["name"], "label": body.get("label") or key[0],
                                   "objectName": key[0], "geometryName": body.get("geometryName") or "geom",
                                   "style": body.get("style")}
            return 201, self.map_views[key]
        if match and method == "GET":
            return 200, [v for (o, _), v in self.map_views.items() if o == match.group(1)]
        if path == "/api/gis/layers" and method == "GET":
            return 200, [{"objectName": o, "geometryName": g, "layerName": f"{o}__{g}", "published": True,
                          "wfs": f"{self.base_url}/geoserver/wfs?service=WFS&version=2.0.0&request=GetFeature"
                                 f"&typeNames=ws:{o}__{g}"}
                         for (o, g) in self.layer_attributes]
        match = MAP_VIEW.match(path)
        if match:
            view = self.map_views.get(match.groups())
            if view is None:
                return 404, {"detail": "no such map view"}
            if method == "DELETE":
                del self.map_views[match.groups()]
                return 204, None
            if method == "PUT":
                view.update({"label": body.get("label") or view["label"],
                             "geometryName": body.get("geometryName") or view["geometryName"],
                             "style": body.get("style")})
            return 200, view
        match = LAYER.match(path)
        if match and method == "DELETE":
            self.unpublished.append(match.groups())
            self.layer_attributes.pop(match.groups(), None)
            return 204, None
        if match and method == "POST":
            if self.fail_on_layer:
                return self.fail_on_layer, {"detail": "boom-layer"}
            self.layers.append((*match.groups(), (body or {}).get("style")))
            # a new feature type takes every column; a republish keeps the one it had (wasichai 1.5.0)
            self.layer_attributes.setdefault(match.groups(), list(self.columns.get(match.group(1), [])))
            return 200, {"objectName": match.group(1), "geometryName": match.group(2), "published": True}
        return 500, {"message": "boom"}

    def _describe(self, query):
        """GeoServer's WFS DescribeFeatureType of one layer: an XSD with an element per attribute column."""
        params = {k: v[0] for k, v in urllib.parse.parse_qs(query).items()}
        if not self.wfs_reachable or params.get("request") != "DescribeFeatureType":
            return 503, {"detail": "wfs down"}
        nombre = params.get("typeNames", "").split(":", 1)[-1]
        pareja = next((k for k in self.layer_attributes if f"{k[0]}__{k[1]}" == nombre), None)
        if pareja is None:
            return 400, {"detail": "unknown layer"}
        elementos = "".join(f'<xsd:element name="{c}" type="xsd:string"/>' for c in ["id", *self.layer_attributes[pareja], pareja[1]])
        return 200, ('<?xml version="1.0"?><xsd:schema xmlns:xsd="http://www.w3.org/2001/XMLSchema">'
                     f'<xsd:complexType name="t"><xsd:sequence>{elementos}</xsd:sequence></xsd:complexType>'
                     '</xsd:schema>').encode("utf-8")

    def _script(self, method, full_path, body):
        path, _, query = full_path.partition("?")
        if path.startswith("/api/gis/"):
            return self._gis(method, path, body)
        if path == "/geoserver/wfs" and method == "GET":
            return self._describe(query)
        if path == "/api/roles" or path.startswith("/api/roles/"):
            return self._roles(method, path, body)
        if path == "/api/service-accounts" or path.startswith("/api/service-accounts/"):
            return self._service_accounts(method, path, body)
        if path == "/api/auth/login" and method == "POST":
            if self.login_response is not None:
                return 200, self.login_response
            return 200, {"token": "t"}
        if RECORDS.match(path) and method in ("GET", "POST"):
            return self._records(method, path, query, body)
        if RECORD.match(path) and method == "PUT":
            return self._update(path, body)
        if RECORD.match(path) and method == "PATCH":
            return self._patch(path, body)
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
            self.object_rules[name] = {k: body[k] for k in ("indexes", "appendOnly", "apiOnly") if k in body}
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
