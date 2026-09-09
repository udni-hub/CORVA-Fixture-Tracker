CORVA FIXTURE TRACKER - CLOUD VERSION
=====================================

What is included:
- Mobile-first Flask interface
- User + Admin login
- AFS / TOP HAT / UNISHELL search
- ADD / REMOVE Received
- Admin-only master-data editing
- Balance and Buildable Fixtures calculations
- EXPORT EXCEL using CORVA_TRACKER_TEMPLATE.xlsx as the tracker template
- Supabase REST connection
- Render-ready Gunicorn start command

CLOUD SETUP
1. Supabase already has the `fixtures` table and 330 records.
2. In Supabase, keep the table protected with RLS. The Python server uses the service-role key server-side, which bypasses RLS.
3. Never put SUPABASE_SERVICE_KEY in HTML/JavaScript and never share it in chat.
4. Copy .env.example values into your cloud host's Environment Variables:
   SUPABASE_URL
   SUPABASE_SERVICE_KEY
   FLASK_SECRET
   ADMIN_USERNAME
   ADMIN_PASSWORD
   USER_USERNAME
   USER_PASSWORD

LOCAL TEST
python -m pip install -r requirements.txt
python app.py
Open http://127.0.0.1:5000

DEFAULT USER VALUES
The values are placeholders in .env.example. Change them before use.

EXPORT
The Export Excel button downloads CORVA_FIXTURE_TRACKER_UPDATED.xlsx.
It starts from the supplied tracker template and writes current cloud values back into the corresponding rows, including Received, Balance and Buildable Fixtures.

DEPLOYMENT
A Python Flask app can be deployed as a Render Web Service.
Build command:
pip install -r requirements.txt
Start command:
gunicorn app:app

Free Render web services can spin down after inactivity, so the first request after idle may take around a minute. The database remains in Supabase; the app does not rely on local server storage.
