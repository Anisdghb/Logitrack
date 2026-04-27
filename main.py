from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from typing import Optional, List
from datetime import date, datetime
import sqlite3
import hashlib
import json
import os

app = FastAPI(title="LogiTrack API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_PATH = "logistics.db"

# ─── DB SETUP ────────────────────────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()

    c.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        role TEXT NOT NULL,  -- direction, manager, livreur, prestataire, rh, flotte
        phone TEXT,
        active INTEGER DEFAULT 1,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS vehicles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        plate TEXT UNIQUE NOT NULL,
        brand TEXT,
        model TEXT,
        type TEXT,  -- camionnette, fourgon, poids_lourd
        status TEXT DEFAULT 'disponible',  -- disponible, en_mission, maintenance, indisponible
        insurance_expiry TEXT,
        ct_expiry TEXT,
        mileage INTEGER DEFAULT 0,
        notes TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS tours (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        client TEXT,
        zone TEXT,
        stops INTEGER DEFAULT 0,
        description TEXT,
        active INTEGER DEFAULT 1,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS plannings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT NOT NULL,
        driver_id INTEGER,
        tour_id INTEGER,
        vehicle_id INTEGER,
        status TEXT DEFAULT 'planifie',  -- planifie, en_cours, termine, valide
        start_time TEXT,
        end_time TEXT,
        notes TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (driver_id) REFERENCES users(id),
        FOREIGN KEY (tour_id) REFERENCES tours(id),
        FOREIGN KEY (vehicle_id) REFERENCES vehicles(id)
    );

    CREATE TABLE IF NOT EXISTS incidents (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        planning_id INTEGER,
        driver_id INTEGER,
        type TEXT,
        description TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (planning_id) REFERENCES plannings(id),
        FOREIGN KEY (driver_id) REFERENCES users(id)
    );

    CREATE TABLE IF NOT EXISTS tokens (
        token TEXT PRIMARY KEY,
        user_id INTEGER,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id)
    );
    """)

    # Seed demo data
    pw = hashlib.sha256("demo123".encode()).hexdigest()
    users = [
        ("Jean Dupont", "direction@demo.com", pw, "direction", "0600000001"),
        ("Marie Martin", "manager@demo.com", pw, "manager", "0600000002"),
        ("Ali Benali", "livreur1@demo.com", pw, "livreur", "0600000003"),
        ("Lucas Petit", "livreur2@demo.com", pw, "livreur", "0600000004"),
        ("Sophie Rh", "rh@demo.com", pw, "rh", "0600000005"),
        ("Paul Flotte", "flotte@demo.com", pw, "flotte", "0600000006"),
    ]
    for u in users:
        try:
            c.execute("INSERT INTO users (name,email,password,role,phone) VALUES (?,?,?,?,?)", u)
        except: pass

    vehicles_data = [
        ("AB-123-CD", "Renault", "Master", "fourgon", "disponible", "2025-12-01", "2025-06-15", 45000),
        ("EF-456-GH", "Peugeot", "Partner", "camionnette", "disponible", "2025-09-30", "2026-01-20", 32000),
        ("IJ-789-KL", "Mercedes", "Sprinter", "fourgon", "maintenance", "2026-03-15", "2025-11-10", 78000),
        ("MN-012-OP", "Citroën", "Jumpy", "camionnette", "disponible", "2025-08-20", "2025-12-30", 21000),
    ]
    for v in vehicles_data:
        try:
            c.execute("INSERT INTO vehicles (plate,brand,model,type,status,insurance_expiry,ct_expiry,mileage) VALUES (?,?,?,?,?,?,?,?)", v)
        except: pass

    tours_data = [
        ("Tournée Nord", "ClientA", "Zone Nord", 12, "Paris 9e, 10e, 18e, 19e"),
        ("Tournée Est", "ClientB", "Zone Est", 8, "Paris 11e, 12e, 20e"),
        ("Tournée Sud", "ClientA", "Zone Sud", 15, "Paris 13e, 14e, 15e"),
        ("Tournée Ouest", "ClientC", "Zone Ouest", 10, "Paris 16e, 17e, Neuilly"),
    ]
    for t in tours_data:
        try:
            c.execute("INSERT INTO tours (name,client,zone,stops,description) VALUES (?,?,?,?,?)", t)
        except: pass

    today = date.today().isoformat()
    plannings_seed = [
        (today, 3, 1, 1, "en_cours", "07:30", None, None),
        (today, 4, 2, 2, "planifie", None, None, None),
        (today, 3, 3, 4, "termine", "06:45", "15:30", None),
    ]
    for p in plannings_seed:
        try:
            c.execute("INSERT INTO plannings (date,driver_id,tour_id,vehicle_id,status,start_time,end_time,notes) VALUES (?,?,?,?,?,?,?,?)", p)
        except: pass

    conn.commit()
    conn.close()

init_db()

# ─── MODELS ──────────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    email: str
    password: str

class UserCreate(BaseModel):
    name: str
    email: str
    password: str
    role: str
    phone: Optional[str] = None

class VehicleCreate(BaseModel):
    plate: str
    brand: Optional[str] = None
    model: Optional[str] = None
    type: Optional[str] = None
    status: str = "disponible"
    insurance_expiry: Optional[str] = None
    ct_expiry: Optional[str] = None
    mileage: int = 0
    notes: Optional[str] = None

class VehicleUpdate(BaseModel):
    status: Optional[str] = None
    mileage: Optional[int] = None
    notes: Optional[str] = None
    insurance_expiry: Optional[str] = None
    ct_expiry: Optional[str] = None

class PlanningCreate(BaseModel):
    date: str
    driver_id: int
    tour_id: int
    vehicle_id: int
    notes: Optional[str] = None

class PlanningUpdate(BaseModel):
    status: Optional[str] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    notes: Optional[str] = None

class IncidentCreate(BaseModel):
    planning_id: int
    type: str
    description: str

class TourCreate(BaseModel):
    name: str
    client: Optional[str] = None
    zone: Optional[str] = None
    stops: int = 0
    description: Optional[str] = None

# ─── AUTH ────────────────────────────────────────────────────────────────────

security = HTTPBearer(auto_error=False)

def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    if not credentials:
        raise HTTPException(status_code=401, detail="Non authentifié")
    token = credentials.credentials
    conn = get_db()
    row = conn.execute("SELECT u.* FROM tokens t JOIN users u ON t.user_id=u.id WHERE t.token=?", (token,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=401, detail="Token invalide")
    return dict(row)

@app.post("/auth/login")
def login(req: LoginRequest):
    pw = hashlib.sha256(req.password.encode()).hexdigest()
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE email=? AND password=? AND active=1", (req.email, pw)).fetchone()
    if not user:
        conn.close()
        raise HTTPException(status_code=401, detail="Identifiants incorrects")
    import secrets
    token = secrets.token_hex(32)
    conn.execute("INSERT INTO tokens (token, user_id) VALUES (?,?)", (token, user["id"]))
    conn.commit()
    conn.close()
    return {"token": token, "user": {"id": user["id"], "name": user["name"], "role": user["role"], "email": user["email"]}}

@app.post("/auth/logout")
def logout(current_user=Depends(get_current_user), credentials: HTTPAuthorizationCredentials = Depends(security)):
    conn = get_db()
    conn.execute("DELETE FROM tokens WHERE token=?", (credentials.credentials,))
    conn.commit()
    conn.close()
    return {"ok": True}

# ─── USERS ───────────────────────────────────────────────────────────────────

@app.get("/users")
def list_users(role: Optional[str] = None, current_user=Depends(get_current_user)):
    conn = get_db()
    if role:
        rows = conn.execute("SELECT id,name,email,role,phone,active,created_at FROM users WHERE role=? ORDER BY name", (role,)).fetchall()
    else:
        rows = conn.execute("SELECT id,name,email,role,phone,active,created_at FROM users ORDER BY name").fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.post("/users")
def create_user(user: UserCreate, current_user=Depends(get_current_user)):
    if current_user["role"] not in ["direction", "manager", "rh"]:
        raise HTTPException(status_code=403, detail="Accès refusé")
    pw = hashlib.sha256(user.password.encode()).hexdigest()
    conn = get_db()
    try:
        conn.execute("INSERT INTO users (name,email,password,role,phone) VALUES (?,?,?,?,?)",
                     (user.name, user.email, pw, user.role, user.phone))
        conn.commit()
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=400, detail="Email déjà utilisé")
    conn.close()
    return {"ok": True}

@app.patch("/users/{user_id}/toggle")
def toggle_user(user_id: int, current_user=Depends(get_current_user)):
    conn = get_db()
    conn.execute("UPDATE users SET active = CASE WHEN active=1 THEN 0 ELSE 1 END WHERE id=?", (user_id,))
    conn.commit()
    conn.close()
    return {"ok": True}

# ─── VEHICLES ────────────────────────────────────────────────────────────────

@app.get("/vehicles")
def list_vehicles(current_user=Depends(get_current_user)):
    conn = get_db()
    rows = conn.execute("SELECT * FROM vehicles ORDER BY plate").fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.post("/vehicles")
def create_vehicle(v: VehicleCreate, current_user=Depends(get_current_user)):
    conn = get_db()
    try:
        conn.execute("""INSERT INTO vehicles (plate,brand,model,type,status,insurance_expiry,ct_expiry,mileage,notes)
                        VALUES (?,?,?,?,?,?,?,?,?)""",
                     (v.plate, v.brand, v.model, v.type, v.status, v.insurance_expiry, v.ct_expiry, v.mileage, v.notes))
        conn.commit()
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=400, detail="Immatriculation déjà existante")
    conn.close()
    return {"ok": True}

@app.patch("/vehicles/{vehicle_id}")
def update_vehicle(vehicle_id: int, update: VehicleUpdate, current_user=Depends(get_current_user)):
    conn = get_db()
    fields = {k: v for k, v in update.dict().items() if v is not None}
    if not fields:
        return {"ok": True}
    set_clause = ", ".join(f"{k}=?" for k in fields)
    conn.execute(f"UPDATE vehicles SET {set_clause} WHERE id=?", (*fields.values(), vehicle_id))
    conn.commit()
    conn.close()
    return {"ok": True}

# ─── TOURS ───────────────────────────────────────────────────────────────────

@app.get("/tours")
def list_tours(current_user=Depends(get_current_user)):
    conn = get_db()
    rows = conn.execute("SELECT * FROM tours WHERE active=1 ORDER BY name").fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.post("/tours")
def create_tour(t: TourCreate, current_user=Depends(get_current_user)):
    conn = get_db()
    conn.execute("INSERT INTO tours (name,client,zone,stops,description) VALUES (?,?,?,?,?)",
                 (t.name, t.client, t.zone, t.stops, t.description))
    conn.commit()
    conn.close()
    return {"ok": True}

# ─── PLANNING ────────────────────────────────────────────────────────────────

@app.get("/plannings")
def list_plannings(date_filter: Optional[str] = None, driver_id: Optional[int] = None, current_user=Depends(get_current_user)):
    conn = get_db()
    query = """
        SELECT p.*, u.name as driver_name, u.phone as driver_phone,
               t.name as tour_name, t.client, t.zone, t.stops,
               v.plate, v.brand, v.model
        FROM plannings p
        LEFT JOIN users u ON p.driver_id = u.id
        LEFT JOIN tours t ON p.tour_id = t.id
        LEFT JOIN vehicles v ON p.vehicle_id = v.id
        WHERE 1=1
    """
    params = []
    if date_filter:
        query += " AND p.date=?"
        params.append(date_filter)
    if driver_id:
        query += " AND p.driver_id=?"
        params.append(driver_id)
    if current_user["role"] == "livreur":
        query += " AND p.driver_id=?"
        params.append(current_user["id"])
    query += " ORDER BY p.date DESC, u.name"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.post("/plannings")
def create_planning(p: PlanningCreate, current_user=Depends(get_current_user)):
    if current_user["role"] not in ["direction", "manager"]:
        raise HTTPException(status_code=403, detail="Accès refusé")
    conn = get_db()
    conn.execute("""INSERT INTO plannings (date,driver_id,tour_id,vehicle_id,notes)
                    VALUES (?,?,?,?,?)""",
                 (p.date, p.driver_id, p.tour_id, p.vehicle_id, p.notes))
    conn.commit()
    conn.close()
    return {"ok": True}

@app.patch("/plannings/{planning_id}")
def update_planning(planning_id: int, update: PlanningUpdate, current_user=Depends(get_current_user)):
    conn = get_db()
    planning = conn.execute("SELECT * FROM plannings WHERE id=?", (planning_id,)).fetchone()
    if not planning:
        raise HTTPException(status_code=404, detail="Planning introuvable")

    # Livreur can only update their own and only start/end time
    if current_user["role"] == "livreur":
        if planning["driver_id"] != current_user["id"]:
            raise HTTPException(status_code=403, detail="Accès refusé")

    fields = {k: v for k, v in update.dict().items() if v is not None}
    if not fields:
        return {"ok": True}
    set_clause = ", ".join(f"{k}=?" for k in fields)
    conn.execute(f"UPDATE plannings SET {set_clause} WHERE id=?", (*fields.values(), planning_id))
    conn.commit()
    conn.close()
    return {"ok": True}

@app.delete("/plannings/{planning_id}")
def delete_planning(planning_id: int, current_user=Depends(get_current_user)):
    if current_user["role"] not in ["direction", "manager"]:
        raise HTTPException(status_code=403, detail="Accès refusé")
    conn = get_db()
    conn.execute("DELETE FROM plannings WHERE id=?", (planning_id,))
    conn.commit()
    conn.close()
    return {"ok": True}

# ─── INCIDENTS ───────────────────────────────────────────────────────────────

@app.get("/incidents")
def list_incidents(current_user=Depends(get_current_user)):
    conn = get_db()
    rows = conn.execute("""
        SELECT i.*, u.name as driver_name, p.date as planning_date
        FROM incidents i
        LEFT JOIN users u ON i.driver_id = u.id
        LEFT JOIN plannings p ON i.planning_id = p.id
        ORDER BY i.created_at DESC
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.post("/incidents")
def create_incident(inc: IncidentCreate, current_user=Depends(get_current_user)):
    conn = get_db()
    conn.execute("INSERT INTO incidents (planning_id,driver_id,type,description) VALUES (?,?,?,?)",
                 (inc.planning_id, current_user["id"], inc.type, inc.description))
    conn.commit()
    conn.close()
    return {"ok": True}

# ─── DASHBOARD ───────────────────────────────────────────────────────────────

@app.get("/dashboard")
def get_dashboard(current_user=Depends(get_current_user)):
    conn = get_db()
    today = date.today().isoformat()

    total_drivers = conn.execute("SELECT COUNT(*) FROM users WHERE role='livreur' AND active=1").fetchone()[0]
    today_plannings = conn.execute("SELECT COUNT(*) FROM plannings WHERE date=?", (today,)).fetchone()[0]
    in_progress = conn.execute("SELECT COUNT(*) FROM plannings WHERE date=? AND status='en_cours'", (today,)).fetchone()[0]
    pending_validation = conn.execute("SELECT COUNT(*) FROM plannings WHERE date=? AND status='termine'", (today,)).fetchone()[0]
    validated_today = conn.execute("SELECT COUNT(*) FROM plannings WHERE date=? AND status='valide'", (today,)).fetchone()[0]
    available_vehicles = conn.execute("SELECT COUNT(*) FROM vehicles WHERE status='disponible'").fetchone()[0]
    maintenance_vehicles = conn.execute("SELECT COUNT(*) FROM vehicles WHERE status='maintenance'").fetchone()[0]
    total_incidents = conn.execute("SELECT COUNT(*) FROM incidents").fetchone()[0]

    # Recent plannings
    recent = conn.execute("""
        SELECT p.id, p.date, p.status, u.name as driver_name, t.name as tour_name,
               v.plate, p.start_time, p.end_time
        FROM plannings p
        LEFT JOIN users u ON p.driver_id=u.id
        LEFT JOIN tours t ON p.tour_id=t.id
        LEFT JOIN vehicles v ON p.vehicle_id=v.id
        WHERE p.date=?
        ORDER BY u.name
    """, (today,)).fetchall()

    conn.close()
    return {
        "stats": {
            "total_drivers": total_drivers,
            "today_plannings": today_plannings,
            "in_progress": in_progress,
            "pending_validation": pending_validation,
            "validated_today": validated_today,
            "available_vehicles": available_vehicles,
            "maintenance_vehicles": maintenance_vehicles,
            "total_incidents": total_incidents,
        },
        "today_plannings": [dict(r) for r in recent]
    }
