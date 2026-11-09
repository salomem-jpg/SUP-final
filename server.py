"""Supplier Capability Hub — HTML + Python backend, synthetic demonstration data.

Backend is authoritative for persisted state, intervention matching and feasibility.
No Siemens service, LLM, or Snowflake connection is implied.
"""
from __future__ import annotations

import base64
import copy
import hmac
import json
import math
import os
import secrets
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware

ROOT = Path(__file__).resolve().parent
CATALOG = json.loads((ROOT / "data" / "demo_catalog.json").read_text(encoding="utf-8"))
CODES = {x["code"] for x in CATALOG["criteria"]}
SOURCES = {c["id"]: c for c in CATALOG["cases"]}
INTERVENTIONS = {i["id"]: i for i in CATALOG["interventions"]}
DB_PATH = Path(os.getenv("DATABASE_PATH", str(ROOT / "storage" / "sessions.sqlite3")))
REQUIRE_AUTH = os.getenv("REQUIRE_AUTH", "0").lower() in ("1", "true", "yes")
APP_USERNAME = os.getenv("APP_USERNAME", "demo")
APP_PASSWORD = os.getenv("APP_PASSWORD", "")
if REQUIRE_AUTH and not APP_PASSWORD:
    raise RuntimeError("Set APP_PASSWORD when REQUIRE_AUTH=1; refusing to start unprotected.")

LOCK = threading.RLock()
app = FastAPI(
    title="Supplier Capability Hub API",
    version="1.0.0",
    description="Synthetic supplier case data. Verified rules are deterministic; Copilot/Snowflake are not connected.",
    docs_url="/api/docs", redoc_url=None,
)


def initial() -> dict:
    return {
        "cases": copy.deepcopy(CATALOG["cases"]),
        "activeId": CATALOG["cases"][0]["id"],
        "compare": [x["id"] for x in CATALOG["cases"][:3]],
        "chat": [], "ui": {}, "version": 2,
    }


def finite_number(v: Any, lo: float = 0, hi: float = 1e13, default: float = 0) -> float:
    if isinstance(v, bool):
        return default
    try:
        x = float(v)
    except (ValueError, TypeError):
        return default
    return x if math.isfinite(x) and lo <= x <= hi else default


def sanitize_case(candidate: Any, base: dict) -> dict:
    """Never trust the browser for immutable case context or catalogue data."""
    result = copy.deepcopy(base)
    if not isinstance(candidate, dict):
        return result
    rating_input = candidate.get("ratings", {})
    if isinstance(rating_input, dict):
        for code in CODES:
            if code not in rating_input:
                continue
            v = rating_input[code]
            result["ratings"][code] = None if v is None or v == "" else (
                finite_number(v, 1, 5, default=-1) if finite_number(v, 1, 5, default=-1) != -1 else result["ratings"].get(code)
            )
    new_finance = candidate.get("finance", {})
    if isinstance(new_finance, dict):
        for key, default in base["finance"].items():
            if key not in new_finance:
                continue
            v = new_finance[key]
            if isinstance(default, bool):
                if isinstance(v, bool): result["finance"][key] = v
            elif isinstance(default, (float, int)):
                result["finance"][key] = finite_number(v, 0, 1 if key.startswith("p_") and key not in ("p_low", "p_high") else (1 if key in ("p_low", "p_high") else 1e12), default)
            elif isinstance(default, str) and isinstance(v, str):
                result["finance"][key] = v[:200]
    selected = candidate.get("selected")
    if isinstance(selected, list):
        result["selected"] = list(dict.fromkeys(i for i in selected if isinstance(i, str) and i in INTERVENTIONS))[:21]
    qa = candidate.get("questionnaire")
    if isinstance(qa, dict):
        result["questionnaire"] = {
            k: (None if v is None else finite_number(v, 1, 5, default=-1))
            for k, v in qa.items() if k in CODES and (v is None or finite_number(v, 1, 5, default=-1) != -1)
        }
    notes = candidate.get("workflowNotes")
    if isinstance(notes, dict):
        result["workflowNotes"] = {str(k): v[:20000] for k, v in notes.items()
                                   if str(k) in {str(x) for x in range(1, 9)} and isinstance(v, str)}
    stage = candidate.get("completed_stage")
    if isinstance(stage, int) and 0 <= stage <= 8:
        result["completed_stage"] = stage
    for key in ("diagnosis_approved", "solution_approved"):
        if isinstance(candidate.get(key), bool):
            result[key] = candidate[key]
    if candidate.get("reviewDecision") in ("Pending", "Approved", "Rejected", "Rework", "Defer"):
        result["reviewDecision"] = candidate["reviewDecision"]
    if isinstance(candidate.get("reviewNote"), str):
        result["reviewNote"] = candidate["reviewNote"][:5000]
    return result


def evaluate(s: dict) -> dict:
    f = s["finance"]
    p = finite_number(f.get("p_technical"), 0, 1) * finite_number(f.get("p_on_time"), 0, 1) * finite_number(f.get("p_sustain"), 0, 1)
    cost_keys = ("cost_experts", "cost_travel", "cost_testing", "cost_tooling", "cost_incentives")
    cost = sum(finite_number(f.get(k)) for k in cost_keys)
    gain = finite_number(f.get("gain"))
    net = gain * p - cost
    supplier_value = sum(finite_number(f.get(k)) for k in (
        "supplier_contribution", "retained_savings", "productivity_relief", "other_customer_upside"
    )) - sum(finite_number(f.get(k)) for k in ("supplier_capex", "supplier_opex"))
    domain = {}
    weakness = []
    unassessed = []
    for x in CATALOG["criteria"]:
        code = x["code"]
        value = s["ratings"].get(code)
        if value is None:
            unassessed.append(code)
        elif value < 3.1:
            weakness.append({"code": code, "name": x["name"], "rating": value})
    weakness.sort(key=lambda x: x["rating"])
    for d in "ABC":
        vals = [s["ratings"].get(x["code"]) for x in CATALOG["criteria"] if x["code"].startswith(d)]
        assessed = [v for v in vals if isinstance(v, (int, float))]
        domain[d] = {"assessed": len(assessed), "total": len(vals), "average": sum(assessed)/len(assessed) if assessed else None}
    gaps = {x["code"] for x in weakness} | set(s.get("criteria", []))
    recommendations = []
    for i in CATALOG["interventions"]:
        codes = [v.strip() for v in i["criteria"].split(";") if v.strip()]
        overlap = [code for code in codes if code in gaps]
        confirmed = [code for code in codes if s["ratings"].get(code) is not None and s["ratings"].get(code) < 3.1]
        score = len(confirmed) * 4 + len(overlap) * 2 + (1 if i["id"] in s.get("selected", []) else 0)
        recommendations.append({**i, "criteria_list": codes, "overlap": overlap, "points": score, "confirmed_gaps": confirmed})
    recommendations.sort(key=lambda x: x["points"], reverse=True)
    gates = {"technical": f.get("tech_ok") is True,
             "timing": f.get("timing_ok") is True,
             "siemens_economics": net > 0,
             "supplier_willingness": f.get("supplier_willing") == "Yes"}
    return {"p": p, "gain": gain, "cost": cost, "net": net, "sup": supplier_value, "econ": net > 0,
            "gates": gates, "all_gates_pass": all(gates.values()),
            "domain": domain, "missing": unassessed, "weak": weakness,
            "coverage": {"assessed": 16 - len(unassessed), "total": 16, "percentage": (16-len(unassessed))/16*100},
            "recommendations": recommendations}


def normalize_state(incoming: Any, previous: dict) -> dict:
    if not isinstance(incoming, dict):
        raise HTTPException(422, "Invalid state format")
    updated = copy.deepcopy(previous)
    if isinstance(incoming.get("cases"), list):
        by_id = {x.get("id"): x for x in incoming["cases"] if isinstance(x, dict)}
        for idx, old in enumerate(previous["cases"]):
            new = sanitize_case(by_id.get(old["id"]), SOURCES[old["id"]])
            sensitive = ("ratings", "finance", "selected", "questionnaire")
            has_changed = any(new[key] != old.get(key) for key in sensitive)
            if has_changed:
                # A revised assumption/assessment cannot inherit an old financial approval.
                new["reviewDecision"] = "Pending"
                new["reviewNote"] = ""
            elif new.get("reviewDecision") == "Approved" and old.get("reviewDecision") != "Approved":
                evaluation = evaluate(new)
                if not (evaluation["all_gates_pass"] and new.get("diagnosis_approved") and new.get("solution_approved")):
                    raise HTTPException(422, f"Cannot approve {old['id']}: unresolved feasibility or stage approvals")
                if not new.get("reviewNote", "").strip():
                    raise HTTPException(422, "Approval requires a written decision reason")
            updated["cases"][idx] = new
    if incoming.get("activeId") in SOURCES:
        updated["activeId"] = incoming["activeId"]
    if isinstance(incoming.get("compare"), list):
        updated["compare"] = list(dict.fromkeys(x for x in incoming["compare"] if x in SOURCES))[:3]
    chat = incoming.get("chat")
    if isinstance(chat, list):
        updated["chat"] = [{"role": x["role"], "sid": x["sid"], "text": x["text"][:2000]}
                           for x in chat[-50:] if isinstance(x, dict) and x.get("role") in ("bot", "user")
                           and x.get("sid") in SOURCES and isinstance(x.get("text"), str)]
    ui = incoming.get("ui")
    if isinstance(ui, dict):
        updated["ui"] = {"interventionDomain": ui.get("interventionDomain") if ui.get("interventionDomain") in ("A", "B", "C", "ALL") else "ALL"}
    return updated


def summary(state: dict) -> dict:
    return {s["id"]: evaluate(s) for s in state["cases"]}


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH, timeout=10) as con:
        con.execute("CREATE TABLE IF NOT EXISTS sessions (sid TEXT PRIMARY KEY, state TEXT NOT NULL, updated REAL NOT NULL)")


init_db()

def get_db_state(sid: str) -> dict:
    with LOCK:
        with sqlite3.connect(DB_PATH, timeout=10) as con:
            row = con.execute("SELECT state FROM sessions WHERE sid=?", (sid,)).fetchone()
            if row:
                return json.loads(row[0])
            fresh = initial()
            con.execute("INSERT INTO sessions (sid,state,updated) VALUES (?,?,?)", (sid,json.dumps(fresh),time.time()))
            con.commit()
            return fresh


def put_db_state(sid: str, state: dict) -> None:
    with LOCK:
        with sqlite3.connect(DB_PATH, timeout=10) as con:
            con.execute("INSERT INTO sessions (sid,state,updated) VALUES (?,?,?) ON CONFLICT(sid) DO UPDATE SET state=excluded.state, updated=excluded.updated",
                        (sid, json.dumps(state, ensure_ascii=False, allow_nan=False), time.time()))
            con.commit()


def session(request: Request) -> tuple[str, bool]:
    sid = request.cookies.get("sch_sid")
    if sid and len(sid) == 48 and all(c in "0123456789abcdef" for c in sid):
        return sid, False
    return secrets.token_hex(24), True


def attach_cookie(response: JSONResponse, sid: str, is_new: bool, request: Request) -> JSONResponse:
    if is_new:
        secure = request.headers.get("x-forwarded-proto", request.url.scheme) == "https"
        response.set_cookie("sch_sid", sid, httponly=True, secure=secure, samesite="lax", max_age=2592000, path="/")
    response.headers["Cache-Control"] = "no-store"
    return response


def state_response(request: Request, state: dict, status_code: int=200) -> JSONResponse:
    sid, new = session(request)
    return attach_cookie(JSONResponse({"state": state, "evaluations": summary(state), "mode": "synthetic-demo",
                                       "integrations": {"copilot": "not-connected", "snowflake": "mock-data"}}, status_code=status_code), sid, new, request)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    if request.url.path != "/healthz" and REQUIRE_AUTH:
        auth = request.headers.get("authorization", "")
        try:
            schema, token = auth.split(" ", 1)
            creds = base64.b64decode(token, validate=True).decode("utf-8")
            username, password = creds.split(":", 1)
            valid = schema.lower() == "basic" and hmac.compare_digest(username, APP_USERNAME) and hmac.compare_digest(password, APP_PASSWORD)
        except Exception:
            valid = False
        if not valid:
            return JSONResponse({"detail": "Authentication required"}, status_code=401, headers={"WWW-Authenticate": 'Basic realm="Supplier Capability Hub demo"', "Cache-Control":"no-store"})
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        origin = request.headers.get("origin")
        if origin and origin.rstrip("/") != str(request.base_url).rstrip("/"):
            # Account for Render's HTTPS reverse proxy. Origin must match the browser-facing Host.
            forwarded_host = request.headers.get("x-forwarded-host") or request.headers.get("host")
            allowed = {f"https://{forwarded_host}", f"http://{forwarded_host}"}
            if origin not in allowed:
                return JSONResponse({"detail": "Cross-origin writes are disabled"}, status_code=403)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/healthz")
def healthz():
    return {"status":"ok"}


@app.get("/", include_in_schema=False)
def website():
    # One catalogue source for Python and HTML. Escape tag delimiters before embedding JSON.
    template = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    payload = json.dumps(CATALOG, ensure_ascii=True, separators=(",", ":")).replace("<", "\\u003c")
    return HTMLResponse(template.replace("__HUB_CATALOG_JSON__", payload), headers={"Cache-Control":"no-store"})


@app.get("/api/catalog")
def catalog():
    return {"criteria": CATALOG["criteria"], "interventions": CATALOG["interventions"],
            "mock": CATALOG["mock"], "synthetic": True, "copilot_connected": False, "snowflake_connected": False}


@app.get("/api/bootstrap")
def bootstrap(request: Request):
    sid, new = session(request)
    state = get_db_state(sid)
    return attach_cookie(JSONResponse({"state": state, "evaluations": summary(state), "mode": "synthetic-demo",
                                       "integrations": {"copilot": "not-connected", "snowflake": "mock-data"}}), sid, new, request)


@app.post("/api/state")
async def save_state(request: Request):
    payload = await request.body()
    if len(payload) > 400000:
        raise HTTPException(413, "State too large")
    try:
        incoming = json.loads(payload)
    except Exception:
        raise HTTPException(400, "Expected valid JSON")
    sid, new = session(request)
    previous = get_db_state(sid)
    result = normalize_state(incoming, previous)
    put_db_state(sid, result)
    return attach_cookie(JSONResponse({"ok": True, "evaluations": summary(result), "state": result}), sid, new, request)


@app.get("/api/suppliers")
def suppliers(request: Request):
    sid, new = session(request)
    state = get_db_state(sid)
    res = [{"id":x["id"], "name":x["name"], "type":x["type"], "country":x["country"],
            "evaluation":evaluate(x)} for x in state["cases"]]
    return attach_cookie(JSONResponse({"suppliers":res}),sid,new,request)


@app.get("/api/suppliers/{supplier_id}")
def get_supplier(supplier_id: str, request: Request):
    sid, new = session(request)
    state = get_db_state(sid)
    supplier = next((x for x in state["cases"] if x["id"] == supplier_id),None)
    if not supplier: raise HTTPException(404, "Supplier not found")
    return attach_cookie(JSONResponse({"supplier":supplier,"evaluation":evaluate(supplier)}),sid,new,request)


@app.patch("/api/suppliers/{supplier_id}/assessment")
async def set_assessment(supplier_id: str, request: Request):
    return await update_supplier_fields(supplier_id, request, "ratings")


@app.patch("/api/suppliers/{supplier_id}/business-case")
async def set_business_case(supplier_id: str, request: Request):
    return await update_supplier_fields(supplier_id, request, "finance")


@app.patch("/api/suppliers/{supplier_id}/questionnaire")
async def set_questionnaire(supplier_id: str, request: Request):
    return await update_supplier_fields(supplier_id, request, "questionnaire")


@app.patch("/api/suppliers/{supplier_id}/interventions")
async def set_interventions(supplier_id: str, request: Request):
    return await update_supplier_fields(supplier_id, request, "selected")


async def update_supplier_fields(supplier_id: str, request: Request, field: str):
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON")
    if not isinstance(body, dict) or field not in body:
        raise HTTPException(422, f"Required: {field}")
    sid, new = session(request)
    state = get_db_state(sid)
    if supplier_id not in SOURCES: raise HTTPException(404, "Supplier not found")
    incoming = copy.deepcopy(state)
    item = next(x for x in incoming["cases"] if x["id"]==supplier_id)
    if field == "finance":
        if not isinstance(body[field], dict): raise HTTPException(422, "Finance object required")
        item[field] = {**item[field], **body[field]}
    elif field == "ratings":
        if not isinstance(body[field], dict): raise HTTPException(422, "Ratings object required")
        item[field] = {**item[field], **body[field]}
    else:
        item[field] = body[field]
    updated = normalize_state(incoming, state)
    put_db_state(sid, updated)
    target = next(x for x in updated["cases"] if x["id"]==supplier_id)
    return attach_cookie(JSONResponse({"supplier":target,"evaluation":evaluate(target)}),sid,new,request)


@app.post("/api/suppliers/{supplier_id}/decision")
async def record_decision(supplier_id: str, request: Request):
    try: body = await request.json()
    except Exception: raise HTTPException(400, "Expected JSON")
    if not isinstance(body, dict) or body.get("decision") not in ("Pending", "Approved", "Rejected", "Rework", "Defer"):
        raise HTTPException(422, "Decision must be Pending, Approved, Rejected, Rework or Defer")
    sid, new = session(request)
    state = get_db_state(sid)
    record = next((x for x in state["cases"] if x["id"]==supplier_id),None)
    if record is None: raise HTTPException(404, "Supplier not found")
    note = body.get("note", "")
    if not isinstance(note, str) or (body["decision"]!="Pending" and not note.strip()):
        raise HTTPException(422, "A decision reason is required")
    if body["decision"] == "Approved" and not (evaluate(record)["all_gates_pass"] and record.get("diagnosis_approved") and record.get("solution_approved")):
        raise HTTPException(422, "Cannot approve: feasibility or stage approvals outstanding")
    record["reviewDecision"],record["reviewNote"] = body["decision"],note[:5000]
    put_db_state(sid, state)
    return attach_cookie(JSONResponse({"supplier": record,"evaluation": evaluate(record)}),sid,new,request)


@app.get("/api/compare")
def compare(request: Request, ids: str = Query("")):
    keys = list(dict.fromkeys(i.strip() for i in ids.split(",") if i.strip()))
    if not 1 <= len(keys) <= 3: raise HTTPException(422,"Compare 1-3 suppliers")
    if any(k not in SOURCES for k in keys): raise HTTPException(404, "Unknown supplier")
    sid, new = session(request)
    state = get_db_state(sid)
    records = [next(x for x in state["cases"] if x["id"]==k) for k in keys]
    return attach_cookie(JSONResponse({"suppliers":[{"id":s["id"],"name":s["name"],"ratings":s["ratings"],"evaluation":evaluate(s)} for s in records]}), sid,new,request)


def answer_question(message: str, supplier: dict) -> str:
    t=message.lower()
    f=evaluate(supplier)
    name=supplier["name"]
    if any(k in t for k in ("snowflake", "data", "risk source")):
        return f"The record for {name} uses four synthetic data areas: risk, performance, evaluation and supplier relationship. Snowflake is not connected."
    if any(k in t for k in ("business", "finance", "cost", "return", "roi", "value", "investment")):
        return f"Illustrative Siemens expected net value for {name}: €{f['net']:,.0f}. Formula: €{f['gain']:,.0f} potential gain × {f['p']:.1%} success probability − €{f['cost']:,.0f} intervention cost. Supplier-side net estimate: €{f['sup']:,.0f}. These assumptions require validation."
    if any(k in t for k in ("copilot", "agent", "ai")):
        return "The demonstrator uses deterministic matching and calculation. A future Copilot Studio agent can call the protected API. There is no active Microsoft Copilot connection."
    if "compar" in t:
        return "Open Compare suppliers to review up to three cases across 16 criteria. Missing scores are shown as unassessed, not zero."
    if any(k in t for k in ("risk","weak", "gap", "problem")):
        text = "; ".join(f"{x['code']} {x['name']} ({x['rating']:.1f}/5)" for x in f["weak"][:5]) or "no low-scoring criteria"
        return f"{name} has {len(f['weak'])} assessed criteria below the 3.1 reference: {text}. {len(f['missing'])} criteria are unassessed. These ratings do not constitute a suitability decision."
    if any(k in t for k in ("recommend","intervention", "solution","support","improve")):
        i=f["recommendations"][0]
        return f"First research-linked candidate: {i['name']}. Rationale: {i['mechanism']}. Matched criteria: {', '.join(i['overlap']) or 'none'}. Validate fit and source limitations before approval."
    return f"{name}: current engagement trigger is {supplier['trigger']}. You can ask about capability gaps, recommended interventions, economics, supplier comparison, or data sources."


@app.post("/api/assistant")
async def assistant(request: Request):
    try: body=await request.json()
    except Exception: raise HTTPException(400,"Expected JSON")
    if not isinstance(body,dict) or body.get("supplier_id") not in SOURCES:
        raise HTTPException(422,"A known supplier_id is required")
    msg=body.get("message")
    if not isinstance(msg,str) or not 1<=len(msg.strip())<=1500:
        raise HTTPException(422,"Message must be 1-1500 characters")
    sid, new = session(request)
    state = get_db_state(sid)
    c=next(x for x in state["cases"] if x["id"]==body["supplier_id"])
    return attach_cookie(JSONResponse({"answer":answer_question(msg,c),"kind":"deterministic-preview","copilot_connected":False}),sid,new,request)


@app.get("/api/export")
def export(request: Request):
    sid, new = session(request)
    state=get_db_state(sid)
    return attach_cookie(JSONResponse({"format":"supplier-capability-hub-demo-v1","synthetic":True,"state":state},
                         headers={"Content-Disposition":"attachment; filename=supplier-capability-session.json"}),sid,new,request)


@app.post("/api/reset")
def reset(request: Request):
    sid, new = session(request)
    state=initial()
    put_db_state(sid,state)
    return attach_cookie(JSONResponse({"state":state,"evaluations":summary(state),"reset":True}),sid,new,request)

@app.post("/api/import")
async def import_backup(request: Request):
    """Restore a demo session. Uploaded approval decisions are reset for human review."""
    payload = await request.body()
    if len(payload) > 400000:
        raise HTTPException(413, "Backup too large")
    try:
        doc = json.loads(payload)
    except Exception:
        raise HTTPException(400, "Invalid JSON")
    if not isinstance(doc, dict) or doc.get("format") != "supplier-capability-hub-demo-v1" or not isinstance(doc.get("state"),dict):
        raise HTTPException(422, "Not a Supplier Capability Hub backup")
    sid, new = session(request)
    restored = normalize_state(doc["state"], initial())
    for supplier in restored["cases"]:
        supplier["reviewDecision"] = "Pending"
        supplier["reviewNote"] = ""
    put_db_state(sid, restored)
    return attach_cookie(JSONResponse({"state": restored, "evaluations": summary(restored), "review_reset": True}), sid, new, request)

# Describe demo authentication in the generated OpenAPI contract. Production replaces
# HTTP Basic with Siemens-approved identity and role policies.
_original_openapi = app.openapi
def _document_openapi():
    schema = _original_openapi()
    schema.setdefault("components", {}).setdefault("securitySchemes", {})["DemoBasicAuth"] = {"type":"http", "scheme":"basic"}
    for path, methods in schema.get("paths", {}).items():
        if path == "/healthz":
            continue
        for method, operation in methods.items():
            if method.lower() in ("get", "post", "put", "delete", "patch"):
                operation["security"] = [{"DemoBasicAuth": []}]
    return schema
app.openapi = _document_openapi
