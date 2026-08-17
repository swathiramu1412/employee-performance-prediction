WORKMATRIX - Employee Performance Prediction
=============================================

PROJECT URL
-----------
http://127.0.0.1:5000/employee-performance-prediction/

Run
---
1. Stop any older Flask/Python process using port 5000.
2. Open Terminal in this project folder.
3. Install packages:
       pip install flask pandas scikit-learn xgboost
4. Start:
       python app.py
5. Open only:
       http://127.0.0.1:5000/employee-performance-prediction/

Pages
-----
/employee-performance-prediction/                    Welcome
/employee-performance-prediction/signup              Sign Up
/employee-performance-prediction/login               Login
/employee-performance-prediction/company             Company Profile
/employee-performance-prediction/dashboard           Role Dashboard
/employee-performance-prediction/hr                  HR Dashboard
/employee-performance-prediction/admin               Admin Dashboard
/employee-performance-prediction/admin/report        Admin Report

Important
---------
- The web application routes are under /employee-performance-prediction/.
- Old root/login/signup/dashboard bookmarks redirect into /employee-performance-prediction/.
- Authenticated pages send no-cache headers, so browser Back should not restore
  an old authenticated page after logout.
- The application uses a separate WorkMatrix session cookie scoped to /employee-performance-prediction.
- Company data remains isolated by company_id.
- One Admin is allowed per company; a company can have multiple HR accounts.
- Existing model .pkl files are kept under their original filenames.
- Existing performance.db is preserved.

Database lock protection
------------------------
- SQLite busy timeout: 60 seconds.
- SQLite WAL mode is enabled during startup when possible.
- Writes use a retry loop for temporary "database is locked" errors.
- Flask debug auto-reloader is disabled to avoid a second process opening SQLite.

Demo accounts
-------------
HR:    hr / hr123
ADMIN: admin / admin123
