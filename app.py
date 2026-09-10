import os
import io
import math
import requests
from functools import wraps
from flask import Flask, render_template, request, jsonify, session, redirect, url_for, send_file
from dotenv import load_dotenv
from openpyxl import load_workbook
from werkzeug.middleware.proxy_fix import ProxyFix

load_dotenv()
app = Flask(__name__)
app.config.update(SECRET_KEY=os.getenv("FLASK_SECRET") or "change-this-secret", SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SECURE=True, SESSION_COOKIE_SAMESITE="Lax", SESSION_COOKIE_PATH="/")
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)
SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "change-me")
ADMIN_RECOVERY_CODE = os.getenv("ADMIN_RECOVERY_CODE", "")
TABLE = "fixtures"

def headers(): return {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}", "Content-Type": "application/json"}
def sb_get(params=None):
    r=requests.get(f"{SUPABASE_URL}/rest/v1/{TABLE}",headers=headers(),params=params or {},timeout=20); r.raise_for_status(); return r.json()
def sb_patch(row_id,patch):
    r=requests.patch(f"{SUPABASE_URL}/rest/v1/{TABLE}",headers={**headers(),"Prefer":"return=representation"},params={"id":f"eq.{row_id}"},json=patch,timeout=20); r.raise_for_status(); return r.json()
def sb_insert(row):
    r=requests.post(f"{SUPABASE_URL}/rest/v1/{TABLE}",headers={**headers(),"Prefer":"return=representation"},json=row,timeout=20); r.raise_for_status(); return r.json()
def sb_delete(row_id):
    r=requests.delete(f"{SUPABASE_URL}/rest/v1/{TABLE}",headers=headers(),params={"id":f"eq.{row_id}"},timeout=20); r.raise_for_status()
def calc_balance(row): return float(row.get("total_qty") or 0)-float(row.get("received") or 0)
def calc_fixture_buildable(rows):
    values=[]
    for row in rows:
        received=float(row.get("received") or 0); bom=float(row.get("bom_qty") or 0)
        if bom>0: values.append(math.floor(received/bom))
    return min(values) if values else 0

def require_admin(fn):
    @wraps(fn)
    def wrapper(*args,**kwargs):
        if session.get("role")!="admin": return jsonify({"error":"Admin access required"}),403
        return fn(*args,**kwargs)
    return wrapper

@app.get("/")
def home(): return render_template("index.html", role=session.get("role","user"), username=session.get("user","User"))
@app.get("/login")
def login(): return redirect(url_for("home"))
@app.post("/api/login")
def api_login():
    data=request.get_json(silent=True) or {}; username=str(data.get("username","")).strip(); password=str(data.get("password",""))
    if username==ADMIN_USERNAME and password==ADMIN_PASSWORD:
        session.clear(); session["user"]=username; session["role"]="admin"; return jsonify(ok=True,role="admin")
    return jsonify(ok=False,error="Invalid admin credentials"),401
@app.post("/api/forgot-password")
def api_forgot_password():
    data=request.get_json(silent=True) or {}
    username=str(data.get("username","")).strip(); code=str(data.get("recovery_code","")).strip(); new_password=str(data.get("new_password", ""))
    if not ADMIN_RECOVERY_CODE: return jsonify(error="Recovery is not configured yet. Set ADMIN_RECOVERY_CODE in Render Environment."),503
    if username!=ADMIN_USERNAME or code!=ADMIN_RECOVERY_CODE: return jsonify(error="Invalid recovery details"),401
    if len(new_password)<8: return jsonify(error="New password must be at least 8 characters"),400
    os.environ["ADMIN_PASSWORD"]=new_password
    return jsonify(ok=True,message="Password changed for this running service. Add the same value to ADMIN_PASSWORD in Render Environment to keep it after redeploys.")
@app.post("/api/logout")
def api_logout(): session.clear(); return jsonify(ok=True)
@app.get("/api/session")
def api_session(): return jsonify(logged_in=session.get("role")=="admin", user=session.get("user","User"), role=session.get("role","user"))

@app.get("/api/fixtures")
def api_fixtures():
    sheet=request.args.get("sheet","").strip(); fixture=request.args.get("fixture","").strip()
    if sheet not in ("AFS","TOP HAT","UNISHELL") or not fixture: return jsonify(items=[])
    rows=sb_get({"select":"*","sheet":f"eq.{sheet}","fixture_no":f"eq.{fixture}","order":"id.asc"}); fb=calc_fixture_buildable(rows)
    for row in rows: row["balance"]=calc_balance(row); row["buildable"]=fb
    return jsonify(items=rows)

@app.post("/api/receive")
def api_receive():
    data=request.get_json(silent=True) or {}; row_id=data.get("id"); action=data.get("action")
    try: qty=float(data.get("qty") or 0)
    except: qty=0
    if not row_id or qty<=0 or action not in ("add","remove"): return jsonify(error="Enter a valid quantity"),400
    rows=sb_get({"select":"*","id":f"eq.{row_id}"})
    if not rows: return jsonify(error="Item not found"),404
    row=rows[0]; old=float(row.get("received") or 0); new=old+qty if action=="add" else max(0,old-qty)
    updated=sb_patch(row_id,{"received":new})[0]
    fixture_rows=sb_get({"select":"*","sheet":f"eq.{updated['sheet']}","fixture_no":f"eq.{updated['fixture_no']}"})
    return jsonify(ok=True,received=new,balance=calc_balance(updated),buildable=calc_fixture_buildable(fixture_rows))

@app.post("/api/admin/update")
@require_admin
def api_admin_update():
    data=request.get_json(silent=True) or {}; row_id=data.get("id")
    keys=["fixture_no","item_no","description","bom_qty","no_of_sets","total_qty","received","status"]
    patch={k:data[k] for k in keys if k in data}
    if not row_id or not patch: return jsonify(error="Nothing to update"),400
    for k in ("bom_qty","no_of_sets","total_qty","received"):
        if k in patch:
            try: patch[k]=float(patch[k] or 0)
            except: patch[k]=0
    if "received" in patch: patch["received"]=max(0,patch["received"])
    sb_patch(row_id,patch); return jsonify(ok=True)

@app.post("/api/admin/add")
@require_admin
def api_admin_add():
    data=request.get_json(silent=True) or {}
    for k in ("sheet","fixture_no","item_no"):
        if not str(data.get(k,"")).strip(): return jsonify(error=f"{k} is required"),400
    row={"sheet":data["sheet"],"fixture_no":str(data["fixture_no"]).strip(),"item_no":str(data["item_no"]).strip(),"description":data.get("description",""),"bom_qty":float(data.get("bom_qty") or 0),"no_of_sets":float(data.get("no_of_sets") or 0),"total_qty":float(data.get("total_qty") or 0),"received":max(0,float(data.get("received") or 0)),"status":data.get("status","")}
    sb_insert(row); return jsonify(ok=True)
@app.delete("/api/admin/delete/<int:row_id>")
@require_admin
def api_admin_delete(row_id): sb_delete(row_id); return jsonify(ok=True)

@app.get("/api/export")
def export_excel():
    template=os.path.join(os.path.dirname(__file__),"CORVA_TRACKER_TEMPLATE.xlsx"); wb=load_workbook(template); all_rows=sb_get({"select":"*","order":"id.asc"})
    by_key={(str(r["sheet"]),str(r["fixture_no"]).strip(),str(r["item_no"]).strip()):r for r in all_rows}; groups={}
    for r in all_rows: groups.setdefault((str(r["sheet"]),str(r["fixture_no"]).strip()),[]).append(r)
    fb={k:calc_fixture_buildable(v) for k,v in groups.items()}
    for ws in wb.worksheets:
        if ws.title not in ("AFS","TOP HAT","UNISHELL"): continue
        last=None; total_col=8 if ws.title=="AFS" else 7; received_col=9 if ws.title=="AFS" else 8; balance_col=10 if ws.title=="AFS" else 9; buildable_col=11 if ws.title=="AFS" else 10; status_col=12 if ws.title=="AFS" else 11
        for r in range(4,ws.max_row+1):
            fv=ws.cell(r,2).value
            if fv not in (None,""): last=str(fv).strip()
            iv=ws.cell(r,3).value
            if iv in (None,"") or last is None: continue
            row=by_key.get((ws.title,last,str(iv).strip()))
            if not row: continue
            ws.cell(r,2).value=row.get("fixture_no"); ws.cell(r,3).value=row.get("item_no"); ws.cell(r,4).value=row.get("description"); ws.cell(r,5).value=row.get("bom_qty"); ws.cell(r,6).value=row.get("no_of_sets"); ws.cell(r,total_col).value=row.get("total_qty"); ws.cell(r,received_col).value=row.get("received"); ws.cell(r,balance_col).value=calc_balance(row); ws.cell(r,buildable_col).value=fb.get((ws.title,last),0); ws.cell(r,status_col).value=row.get("status") or ""
        ws.sheet_view.showGridLines=False
    wb.calculation.fullCalcOnLoad=True; wb.calculation.forceFullCalc=True
    output=io.BytesIO(); wb.save(output); output.seek(0)
    return send_file(output,as_attachment=True,download_name="CORVA_FIXTURE_TRACKER_UPDATED.xlsx",mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
@app.get("/health")
def health(): return "OK"
if __name__=="__main__": app.run(host="0.0.0.0",port=int(os.getenv("PORT",5000)))