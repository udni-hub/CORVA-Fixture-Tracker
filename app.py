import os, io, math, requests
from functools import wraps
from flask import Flask, render_template, request, jsonify, session, redirect, url_for, send_file
from dotenv import load_dotenv
from openpyxl import load_workbook

load_dotenv()
app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET", "change-me")

SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "change-me")
USER_USERNAME = os.getenv("USER_USERNAME", "user")
USER_PASSWORD = os.getenv("USER_PASSWORD", "change-me")
TABLE = "fixtures"

def headers():
    return {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
    }

def sb_get(params=None):
    r = requests.get(f"{SUPABASE_URL}/rest/v1/{TABLE}", headers=headers(), params=params or {}, timeout=20)
    r.raise_for_status()
    return r.json()

def sb_patch(row_id, patch):
    r = requests.patch(
        f"{SUPABASE_URL}/rest/v1/{TABLE}",
        headers={**headers(), "Prefer": "return=representation"},
        params={"id": f"eq.{row_id}"},
        json=patch, timeout=20)
    r.raise_for_status()
    return r.json()

def sb_insert(row):
    r = requests.post(
        f"{SUPABASE_URL}/rest/v1/{TABLE}",
        headers={**headers(), "Prefer": "return=representation"},
        json=row, timeout=20)
    r.raise_for_status()
    return r.json()

def sb_delete(row_id):
    r = requests.delete(f"{SUPABASE_URL}/rest/v1/{TABLE}",
                        headers=headers(), params={"id": f"eq.{row_id}"}, timeout=20)
    r.raise_for_status()

def calc(row):
    total = float(row.get("total_qty") or 0)
    received = float(row.get("received") or 0)
    bom = float(row.get("bom_qty") or 0)
    return total - received, (math.floor(received / bom) if bom > 0 else 0)

def require_login(fn):
    @wraps(fn)
    def w(*a, **kw):
        if not session.get("user"):
            return jsonify({"error":"Login required"}), 401
        return fn(*a, **kw)
    return w

def require_admin(fn):
    @wraps(fn)
    def w(*a, **kw):
        if not session.get("user"):
            return jsonify({"error":"Login required"}), 401
        if session.get("role") != "admin":
            return jsonify({"error":"Admin access required"}), 403
        return fn(*a, **kw)
    return w

@app.get("/")
def home():
    if not session.get("user"): return redirect(url_for("login"))
    return render_template("index.html", role=session["role"], username=session["user"])

@app.get("/login")
def login():
    return render_template("login.html")

@app.post("/api/login")
def api_login():
    d = request.get_json() or {}
    u, p = str(d.get("username","")).strip(), str(d.get("password",""))
    if u == ADMIN_USERNAME and p == ADMIN_PASSWORD:
        session.update(user=u, role="admin")
        return jsonify(ok=True, role="admin")
    if u == USER_USERNAME and p == USER_PASSWORD:
        session.update(user=u, role="user")
        return jsonify(ok=True, role="user")
    return jsonify(ok=False, error="Invalid username or password"), 401

@app.post("/api/logout")
def api_logout():
    session.clear()
    return jsonify(ok=True)

@app.get("/api/fixtures")
@require_login
def api_fixtures():
    sheet = request.args.get("sheet","").strip()
    fixture = request.args.get("fixture","").strip()
    if sheet not in ("AFS","TOP HAT","UNISHELL") or not fixture:
        return jsonify(items=[])
    rows = sb_get({"select":"*", "sheet":f"eq.{sheet}", "fixture_no":f"eq.{fixture}", "order":"id.asc"})
    for x in rows:
        x["balance"], x["buildable"] = calc(x)
    return jsonify(items=rows)

@app.post("/api/receive")
@require_login
def api_receive():
    d = request.get_json() or {}
    row_id = d.get("id")
    qty = float(d.get("qty") or 0)
    action = d.get("action")
    if not row_id or qty <= 0 or action not in ("add","remove"):
        return jsonify(error="Enter a valid quantity"), 400
    rows = sb_get({"select":"*", "id":f"eq.{row_id}"})
    if not rows: return jsonify(error="Item not found"), 404
    row = rows[0]
    old = float(row.get("received") or 0)
    new = old + qty if action == "add" else max(0, old - qty)
    updated = sb_patch(row_id, {"received":new})[0]
    balance, buildable = calc(updated)
    return jsonify(ok=True, received=new, balance=balance, buildable=buildable)

@app.post("/api/admin/update")
@require_admin
def api_admin_update():
    d = request.get_json() or {}
    row_id = d.get("id")
    keys = ["fixture_no","item_no","description","bom_qty","no_of_sets","total_qty","received","status"]
    patch = {k:d[k] for k in keys if k in d}
    if not row_id or not patch: return jsonify(error="Nothing to update"), 400
    for k in ("bom_qty","no_of_sets","total_qty","received"):
        if k in patch: patch[k] = float(patch[k] or 0)
    patch["received"] = max(0, patch.get("received", 0)) if "received" in patch else patch.get("received")
    sb_patch(row_id, patch)
    return jsonify(ok=True)

@app.post("/api/admin/add")
@require_admin
def api_admin_add():
    d = request.get_json() or {}
    for k in ("sheet","fixture_no","item_no"):
        if not str(d.get(k,"")).strip(): return jsonify(error=f"{k} is required"), 400
    row = {
        "sheet":d["sheet"], "fixture_no":str(d["fixture_no"]).strip(),
        "item_no":str(d["item_no"]).strip(), "description":d.get("description",""),
        "bom_qty":float(d.get("bom_qty") or 0), "no_of_sets":float(d.get("no_of_sets") or 0),
        "total_qty":float(d.get("total_qty") or 0), "received":max(0,float(d.get("received") or 0)),
        "status":d.get("status","")
    }
    sb_insert(row)
    return jsonify(ok=True)

@app.delete("/api/admin/delete/<int:row_id>")
@require_admin
def api_admin_delete(row_id):
    sb_delete(row_id)
    return jsonify(ok=True)

@app.get("/api/export")
@require_login
def export_excel():
    # Uses the supplied tracker workbook as the visual/structural template.
    template = os.path.join(os.path.dirname(__file__), "CORVA_TRACKER_TEMPLATE.xlsx")
    wb = load_workbook(template)
    all_rows = sb_get({"select":"*", "order":"id.asc"})
    by_key = {(str(x["sheet"]), str(x["fixture_no"]).strip(), str(x["item_no"]).strip()): x for x in all_rows}

    for ws in wb.worksheets:
        if ws.title not in ("AFS","TOP HAT","UNISHELL"): continue
        last_ft = None
        # column positions from the original tracker
        total_col = 8 if ws.title == "AFS" else 7
        rec_col = 9 if ws.title == "AFS" else 8
        bal_col = 10 if ws.title == "AFS" else 9
        build_col = 11 if ws.title == "AFS" else 10
        status_col = 12 if ws.title == "AFS" else 11
        for r in range(4, ws.max_row + 1):
            ft = ws.cell(r,2).value
            if ft not in (None,""):
                last_ft = str(ft).strip()
            item = ws.cell(r,3).value
            if item in (None,"") or last_ft is None: continue
            key = (ws.title, last_ft, str(item).strip())
            row = by_key.get(key)
            if not row: continue
            # Master values
            ws.cell(r,2).value = row.get("fixture_no")
            ws.cell(r,3).value = row.get("item_no")
            ws.cell(r,4).value = row.get("description")
            ws.cell(r,5).value = row.get("bom_qty")
            ws.cell(r,6).value = row.get("no_of_sets")
            ws.cell(r,total_col).value = row.get("total_qty")
            ws.cell(r,rec_col).value = row.get("received")
            bal, build = calc(row)
            ws.cell(r,bal_col).value = bal
            ws.cell(r,build_col).value = build
            ws.cell(r,status_col).value = row.get("status") or ""
        # Force formulas to recalculate if opened in Excel.
        ws.sheet_view.showGridLines = False

    wb.calculation.fullCalcOnLoad = True
    wb.calculation.forceFullCalc = True
    out = io.BytesIO()
    wb.save(out); out.seek(0)
    return send_file(out, as_attachment=True, download_name="CORVA_FIXTURE_TRACKER_UPDATED.xlsx",
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

@app.get("/health")
def health(): return "OK"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT",5000)))
