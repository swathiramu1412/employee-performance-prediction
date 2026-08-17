from flask import Flask, render_template, request, redirect, url_for, session, flash, make_response
import sqlite3, pickle, os, time
import pandas as pd
from functools import wraps
from datetime import datetime

BASE_PATH = "/employee-performance-prediction"
app = Flask(__name__, static_url_path=BASE_PATH + "/static")
app.secret_key = os.environ.get("SECRET_KEY", "employee-performance-secret-key-change-me")
app.config["SESSION_COOKIE_NAME"] = "workmatrix_session"
app.config["SESSION_COOKIE_PATH"] = BASE_PATH
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
DB = "performance.db"
MODEL_FILE = "employee_performance_model.pkl"
FEATURE_FILE = "selected_features.pkl"
CATEGORY = {0:"Average", 1:"Excellent", 2:"Good", 3:"Poor", 4:"Very Good"}

def db():
    # SQLite connection tuned for Flask so simultaneous requests do not
    # immediately fail with "database is locked".
    c = sqlite3.connect(DB, timeout=60, check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA busy_timeout=60000")
    c.execute("PRAGMA synchronous=NORMAL")
    return c

def commit_with_retry(c, attempts=8):
    for i in range(attempts):
        try:
            c.commit()
            return
        except sqlite3.OperationalError as e:
            if "locked" not in str(e).lower() or i == attempts - 1:
                raise
            time.sleep(0.25 * (i + 1))

def ensure_column(c, table, column, definition):
    cols = [r["name"] for r in c.execute(f"PRAGMA table_info({table})").fetchall()]
    if column not in cols:
        c.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

def init_db():
    c = db()
    try:
        c.execute("PRAGMA journal_mode=WAL")
    except sqlite3.OperationalError:
        pass
    c.execute("""CREATE TABLE IF NOT EXISTS companies(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL,
        created_at TEXT NOT NULL)""")
    c.execute("""CREATE TABLE IF NOT EXISTS users(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE, password TEXT, role TEXT, company_id INTEGER)""")
    c.execute("""CREATE TABLE IF NOT EXISTS employees(
        id INTEGER PRIMARY KEY AUTOINCREMENT, employee_id TEXT,
        name TEXT, age REAL, years_experience REAL, department TEXT,
        job_role TEXT, created_by TEXT, created_at TEXT, company_id INTEGER)""")
    c.execute("""CREATE TABLE IF NOT EXISTS predictions(
        id INTEGER PRIMARY KEY AUTOINCREMENT, employee_id TEXT,
        attendance_rate REAL, training_hours REAL, overtime_hours REAL,
        projects_completed REAL, satisfaction_score REAL, work_life_balance REAL,
        salary REAL, experience_per_age REAL, attendance_training REAL,
        salary_per_experience REAL, prediction TEXT, created_by TEXT,
        created_at TEXT, company_id INTEGER)""")

    # Upgrade the original database without deleting existing data.
    for table, col, definition in [
        ("users","company_id","INTEGER"),
        ("employees","company_id","INTEGER"),
        ("predictions","company_id","INTEGER")
    ]:
        ensure_column(c, table, col, definition)

    company = c.execute("SELECT * FROM companies ORDER BY id LIMIT 1").fetchone()
    if not company:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        c.execute("INSERT INTO companies(name,created_at) VALUES(?,?)", ("Nila Company", now))
        company = c.execute("SELECT * FROM companies WHERE name=?", ("Nila Company",)).fetchone()
    cid = company["id"]

    # Preserve the old demo accounts, assigning them to the first company.
    c.execute("UPDATE users SET company_id=? WHERE company_id IS NULL", (cid,))
    c.execute("UPDATE employees SET company_id=? WHERE company_id IS NULL", (cid,))
    c.execute("UPDATE predictions SET company_id=? WHERE company_id IS NULL", (cid,))

    # Keep exactly one starter admin for the default company.
    admin = c.execute("SELECT * FROM users WHERE username='admin'").fetchone()
    if not admin:
        c.execute("INSERT INTO users(username,password,role,company_id) VALUES(?,?,?,?)",
                  ("admin","admin123","admin",cid))
    else:
        c.execute("UPDATE users SET role='admin', company_id=? WHERE username='admin'", (cid,))
    hr = c.execute("SELECT * FROM users WHERE username='hr'").fetchone()
    if not hr:
        c.execute("INSERT INTO users(username,password,role,company_id) VALUES(?,?,?,?)",
                  ("hr","hr123","hr",cid))
    else:
        c.execute("UPDATE users SET role='hr', company_id=? WHERE username='hr'", (cid,))
    commit_with_retry(c); c.close()

def load_model():
    try:
        with open(MODEL_FILE,"rb") as f: m = pickle.load(f)
        with open(FEATURE_FILE,"rb") as f: sf = list(pickle.load(f))
        return m, sf
    except Exception:
        return None, None
model, selected_features = load_model()

def required(role=None):
    def deco(fn):
        @wraps(fn)
        def wrapper(*a, **kw):
            if "user_id" not in session:
                return redirect(url_for("login"))
            if role and session.get("role") != role:
                flash("Access denied.", "error")
                return redirect(url_for("dashboard"))
            return fn(*a, **kw)
        return wrapper
    return deco

def current_user():
    c=db()
    u=c.execute("""SELECT u.*,c.name company_name FROM users u
                   JOIN companies c ON c.id=u.company_id WHERE u.id=?""",
                (session["user_id"],)).fetchone()
    c.close()
    return u

@app.after_request
def security_headers(response):
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

@app.context_processor
def inject_global():
    return {"current_user_obj": current_user() if "user_id" in session else None}

@app.route("/")
def legacy_root():
    response = redirect(BASE_PATH + "/")
    response.delete_cookie("session", path="/")
    return response

@app.route("/employee-performance-prediction/")
def home():
    return redirect(url_for("dashboard")) if "user_id" in session else render_template("welcome.html")

@app.route("/dashboard")
@app.route("/login")
@app.route("/signup")
def legacy_main_redirect():
    target = request.path
    response = redirect(BASE_PATH + ("" if target == "/" else target))
    response.delete_cookie("session", path="/")
    return response

@app.route("/employee-performance-prediction/signup", methods=["GET","POST"])
def signup():
    if request.method == "POST":
        u=request.form["username"].strip(); p=request.form["password"]
        role=request.form.get("role","").lower(); company_name=request.form["company_name"].strip()
        if not u or not p or role not in ("hr","admin") or not company_name:
            flash("Please enter User ID, Password, Company and Role.", "error")
            return render_template("signup.html")
        if len(p)<4:
            flash("Password must contain at least 4 characters.", "error")
            return render_template("signup.html")
        c=db()
        try:
            company=c.execute("SELECT * FROM companies WHERE lower(name)=lower(?)",(company_name,)).fetchone()
            if not company:
                now=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                c.execute("INSERT INTO companies(name,created_at) VALUES(?,?)",(company_name,now))
                company=c.execute("SELECT * FROM companies WHERE lower(name)=lower(?)",(company_name,)).fetchone()
            if role=="admin":
                exists=c.execute("SELECT 1 FROM users WHERE company_id=? AND role='admin'",(company["id"],)).fetchone()
                if exists:
                    flash("This company already has an Admin. Ask the existing Admin to create/manage HR accounts.", "error")
                    c.close(); return render_template("signup.html")
            c.execute("INSERT INTO users(username,password,role,company_id) VALUES(?,?,?,?)",
                      (u,p,role,company["id"]))
            commit_with_retry(c)
            flash("Account created successfully. Please login.", "success")
            return redirect(url_for("login"))
        except sqlite3.IntegrityError:
            flash("User ID already exists. Please choose another.", "error")
        finally:
            c.close()
    return render_template("signup.html")

@app.route("/employee-performance-prediction/login", methods=["GET","POST"])
def login():
    if request.method=="POST":
        u=request.form["username"].strip(); p=request.form["password"]; role=request.form.get("role","").lower()
        c=db(); user=c.execute("""SELECT * FROM users
            WHERE username=? AND password=? AND role=?""",(u,p,role)).fetchone(); c.close()
        if user:
            session.clear()
            session["user_id"]=user["id"]; session["user"]=user["username"]
            session["role"]=user["role"]; session["company_id"]=user["company_id"]
            return redirect(url_for("dashboard"))
        flash("Invalid User ID, password or role.", "error")
    return render_template("login.html")

@app.route("/employee-performance-prediction/logout")
def logout():
    session.clear()
    response = redirect(url_for("home"))
    response.headers["Clear-Site-Data"] = '"cache", "cookies", "storage"'
    response.delete_cookie("workmatrix_session", path=BASE_PATH)
    response.delete_cookie("session", path="/")
    return response

@app.route("/employee-performance-prediction/dashboard")
@required()
def dashboard():
    return redirect(url_for("hr_dashboard" if session["role"]=="hr" else "admin_dashboard"))

@app.route("/employee-performance-prediction/company")
@required()
def company_profile():
    c=db(); cid=session["company_id"]
    company=c.execute("SELECT * FROM companies WHERE id=?",(cid,)).fetchone()
    admin=c.execute("SELECT username FROM users WHERE company_id=? AND role='admin'",(cid,)).fetchone()
    hrs=c.execute("SELECT username FROM users WHERE company_id=? AND role='hr' ORDER BY username",(cid,)).fetchall()
    emp_count=c.execute("SELECT COUNT(*) n FROM employees WHERE company_id=?",(cid,)).fetchone()["n"]
    pred_count=c.execute("SELECT COUNT(*) n FROM predictions WHERE company_id=?",(cid,)).fetchone()["n"]
    c.close()
    return render_template("company_profile.html", company=company, admin=admin, hrs=hrs,
                           emp_count=emp_count, pred_count=pred_count)

@app.route("/employee-performance-prediction/hr")
@required("hr")
def hr_dashboard():
    c=db(); cid=session["company_id"]; uid=session["user"]
    employees=c.execute("""SELECT * FROM employees WHERE company_id=? AND created_by=?
                           ORDER BY id DESC""",(cid,uid)).fetchall()
    predictions=c.execute("""SELECT p.*,e.name FROM predictions p LEFT JOIN employees e
                             ON e.employee_id=p.employee_id AND e.company_id=p.company_id
                             WHERE p.company_id=? AND p.created_by=? ORDER BY p.id DESC LIMIT 10""",(cid,uid)).fetchall()
    hr_count=c.execute("SELECT COUNT(*) n FROM users WHERE company_id=? AND role='hr'",(cid,)).fetchone()["n"]
    c.close()
    return render_template("hr_dashboard.html", employees=employees, predictions=predictions,
                           model_ready=(model is not None and selected_features is not None),
                           hr_count=hr_count)

@app.route("/employee-performance-prediction/employee/add", methods=["GET","POST"])
@required("hr")
def add_employee():
    if request.method=="POST":
        try:
            c=db(); cid=session["company_id"]
            c.execute("""INSERT INTO employees
                (employee_id,name,age,years_experience,department,job_role,created_by,created_at,company_id)
                VALUES(?,?,?,?,?,?,?,?,?)""",(
                request.form["employee_id"].strip(),request.form["name"].strip(),
                float(request.form["age"]),float(request.form["years_experience"]),
                request.form["department"].strip(),request.form["job_role"].strip(),
                session["user"],datetime.now().strftime("%Y-%m-%d %H:%M:%S"),cid))
            commit_with_retry(c); c.close(); flash("Employee saved successfully.","success")
            return redirect(url_for("hr_dashboard"))
        except Exception as e: flash(f"Error: {e}","error")
    return render_template("add_employee.html")

def get_employee_for_access(employee_id):
    c=db()
    if session["role"]=="admin":
        emp=c.execute("SELECT * FROM employees WHERE employee_id=? AND company_id=?",
                      (employee_id,session["company_id"])).fetchone()
    else:
        emp=c.execute("""SELECT * FROM employees WHERE employee_id=? AND company_id=?
                         AND created_by=?""",(employee_id,session["company_id"],session["user"])).fetchone()
    c.close(); return emp

@app.route("/employee-performance-prediction/predict/<employee_id>", methods=["GET","POST"])
@required("hr")
def predict(employee_id):
    emp=get_employee_for_access(employee_id)
    if not emp: flash("Employee not found or access denied.","error"); return redirect(url_for("hr_dashboard"))
    if request.method=="POST":
        if model is None:
            flash("Model files are missing.","error"); return redirect(url_for("predict",employee_id=employee_id))
        try:
            attendance=float(request.form["attendance_rate"]); training=float(request.form["training_hours"])
            overtime=float(request.form["overtime_hours"]); projects=float(request.form["projects_completed"])
            satisfaction=float(request.form["satisfaction_score"]); balance=float(request.form["work_life_balance"])
            salary=float(request.form["salary"])
            exp_age=emp["years_experience"]/(emp["age"]+1); train_project=training/(projects+1)
            att_train=attendance*training; sal_exp=salary/(emp["years_experience"]+1)
            row={"attendance_rate":attendance,"training_hours":training,"overtime_hours":overtime,
                 "projects_completed":projects,"satisfaction_score":satisfaction,"work_life_balance":balance,
                 "salary":salary,"experience_per_age":exp_age,"training_per_project":train_project,
                 "attendance_training":att_train,"salary_per_experience":sal_exp}
            x=pd.DataFrame([row])[selected_features]; result=CATEGORY.get(int(model.predict(x)[0]),"Unknown")
            c=db(); c.execute("""INSERT INTO predictions(
                employee_id,attendance_rate,training_hours,overtime_hours,projects_completed,
                satisfaction_score,work_life_balance,salary,experience_per_age,attendance_training,
                salary_per_experience,prediction,created_by,created_at,company_id)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",(
                employee_id,attendance,training,overtime,projects,satisfaction,balance,salary,exp_age,
                att_train,sal_exp,result,session["user"],datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                session["company_id"]))
            commit_with_retry(c); c.close()
            return render_template("prediction_result.html",employee=emp,prediction=result)
        except Exception as e: flash(f"Prediction error: {e}","error")
    return render_template("predict.html",employee=emp)

@app.route("/employee-performance-prediction/history/<employee_id>")
@required()
def history(employee_id):
    emp=get_employee_for_access(employee_id)
    if not emp: flash("Employee not found or access denied.","error"); return redirect(url_for("dashboard"))
    c=db()
    rows=c.execute("""SELECT * FROM predictions WHERE employee_id=? AND company_id=?
                      AND (?='admin' OR created_by=?) ORDER BY id DESC""",
                   (employee_id,session["company_id"],session["role"],session["user"])).fetchall()
    c.close()
    return render_template("history.html",employee=emp,predictions=rows)

@app.route("/employee-performance-prediction/admin")
@required("admin")
def admin_dashboard():
    c=db(); cid=session["company_id"]
    total_e=c.execute("SELECT COUNT(*) n FROM employees WHERE company_id=?",(cid,)).fetchone()["n"]
    total_p=c.execute("SELECT COUNT(*) n FROM predictions WHERE company_id=?",(cid,)).fetchone()["n"]
    total_hr=c.execute("SELECT COUNT(*) n FROM users WHERE company_id=? AND role='hr'",(cid,)).fetchone()["n"]
    admin_name=c.execute("SELECT username FROM users WHERE company_id=? AND role='admin'",(cid,)).fetchone()
    rows=c.execute("""SELECT p.*,e.name,e.department,e.job_role FROM predictions p
                      LEFT JOIN employees e ON e.employee_id=p.employee_id AND e.company_id=p.company_id
                      WHERE p.company_id=? ORDER BY p.id DESC""",(cid,)).fetchall()
    hrs=c.execute("SELECT username FROM users WHERE company_id=? AND role='hr' ORDER BY username",(cid,)).fetchall()
    summary=c.execute("SELECT prediction,COUNT(*) count FROM predictions WHERE company_id=? GROUP BY prediction",(cid,)).fetchall()
    c.close()
    return render_template("admin_dashboard.html",total_employees=total_e,total_predictions=total_p,
                           total_hr=total_hr,predictions=rows,summary=summary,hrs=hrs,
                           admin_name=admin_name["username"] if admin_name else "-")

@app.route("/employee-performance-prediction/admin/report")
@required("admin")
def report():
    c=db(); rows=c.execute("""SELECT p.*,e.name,e.department,e.job_role FROM predictions p
                              LEFT JOIN employees e ON e.employee_id=p.employee_id AND e.company_id=p.company_id
                              WHERE p.company_id=? ORDER BY p.id DESC""",(session["company_id"],)).fetchall(); c.close()
    return render_template("report.html",rows=rows)

@app.route("/employee-performance-prediction/admin/report/download")
@required("admin")
def download():
    c=db(); rows=c.execute("""SELECT p.*,e.name,e.department,e.job_role FROM predictions p
                              LEFT JOIN employees e ON e.employee_id=p.employee_id AND e.company_id=p.company_id
                              WHERE p.company_id=? ORDER BY p.id DESC""",(session["company_id"],)).fetchall(); c.close()
    cols=["employee_id","name","department","job_role","attendance_rate","training_hours","overtime_hours",
          "projects_completed","satisfaction_score","work_life_balance","salary","prediction","created_by","created_at"]
    out=[",".join(cols)]
    for r in rows: out.append(",".join('"'+str(r[k] if r[k] is not None else "").replace('"','""')+'"' for k in cols))
    res=make_response("\n".join(out)); res.headers["Content-Disposition"]="attachment; filename=company_performance_report.csv"
    res.headers["Content-Type"]="text/csv"; return res

init_db()
if __name__=="__main__":
    # Disable the debug reloader because it starts a second process and can
    # compete for the SQLite database during startup.
    app.run(debug=False, use_reloader=False, threaded=True)
