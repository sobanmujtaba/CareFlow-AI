import os
import uuid
import random
import json
from datetime import datetime
from enum import Enum
from typing import List, Optional
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from groq import Groq
from supabase import create_client, Client

# Load environment variables (only has effect locally - on Render these
# come from the dashboard's Environment tab, not from a .env file)
load_dotenv()
groq_api_key = os.environ.get("GROQ_API_KEY")
groq_client = Groq(api_key=groq_api_key)

# -----------------------------------------------------------------------------
# Supabase client - this is the ONLY thing that makes state shared across
# users. Supabase does not run this FastAPI app for you (it has no Python
# hosting). It just gives you a Postgres database that every instance of
# this backend can read from and write to, so all users see the same data.
# -----------------------------------------------------------------------------
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")  # use the service_role key, not anon
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Name of the single table we use as a shared JSON store (see supabase_schema.sql)
STATE_TABLE = "careflow_state"

# The verified working model on your Groq account
GROQ_MODEL = "openai/gpt-oss-20b"

app = FastAPI(title="CareFlow AI", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://sobanmujtaba.github.io",
        "http://localhost:8000",
        "http://localhost:5173",
        "*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -----------------------------------------------------------------------------
# Domain Schemas
# -----------------------------------------------------------------------------

class DepartmentTrack(str, Enum):
    OPD = "OPD"
    ER_WALKIN = "ER_WALKIN"

class OPDLane(str, Enum):
    EXPRESS = "EXPRESS"          # 2–5 mins (Refills, lab reviews, suture removals)
    COMPREHENSIVE = "COMPREHENSIVE"  # 15–30 mins (Full clinical exams)

class MobilityStatus(str, Enum):
    AMBULATORY = "AMBULATORY"
    ASSISTED = "ASSISTED"
    CANNOT_STAND = "CANNOT_STAND"

class IntakeRequest(BaseModel):
    name: str
    age: int
    track: DepartmentTrack
    chief_complaint: str
    mobility: MobilityStatus = MobilityStatus.AMBULATORY
    is_severe_bleeding: bool = False
    is_severe_trauma: bool = False

class Patient(BaseModel):
    id: str
    name: str
    age: int
    track: DepartmentTrack
    opd_lane: Optional[OPDLane] = None
    mobility: MobilityStatus
    chief_complaint: str
    estimated_duration_min: int
    arrival_time: datetime
    priority_score: float
    wait_time_minutes: int = 0
    estimated_wait_min: int = 0
    clinical_reasoning: Optional[str] = "Classified by AI"
    assigned_bed_id: Optional[str] = None
    status: str = "WAITING"

class HospitalBed(BaseModel):
    id: str
    name: str
    department: DepartmentTrack
    assigned_clinician: str
    current_patient: Optional[Patient] = None
    time_remaining_min: int = 0
    pending_discharge: bool = False

class CareFlowMetrics(BaseModel):
    opd_express_waiting: int
    opd_comprehensive_waiting: int
    er_walkin_waiting: int
    er_beds_occupied: int
    er_beds_total: int
    er_bed_occupancy_pct: float
    avg_opd_wait_min: float
    interleaved_slots_created: int

# -----------------------------------------------------------------------------
# In-Memory State
# -----------------------------------------------------------------------------

def get_initial_beds() -> List[HospitalBed]:
    return [
        HospitalBed(id="er-bed-1", name="ER Trauma Bay 1", department=DepartmentTrack.ER_WALKIN, assigned_clinician="Dr. Evans (Trauma)", current_patient=None),
        HospitalBed(id="er-bed-2", name="ER Resus Bay 2", department=DepartmentTrack.ER_WALKIN, assigned_clinician="Dr. Patel (ER)", current_patient=None),
        HospitalBed(id="er-bed-3", name="ER Rapid Bay 3", department=DepartmentTrack.ER_WALKIN, assigned_clinician="Dr. Mitchell (ER)", current_patient=None),
        HospitalBed(id="opd-room-1", name="OPD Clinic Desk 1", department=DepartmentTrack.OPD, assigned_clinician="Dr. Thorne (Consultant)", current_patient=None),
        HospitalBed(id="opd-room-2", name="OPD Clinic Desk 2", department=DepartmentTrack.OPD, assigned_clinician="Dr. Vance (Consultant)", current_patient=None),
    ]

waiting_patients: List[Patient] = []
beds: List[HospitalBed] = get_initial_beds()
interleaved_counter: int = 0

# -----------------------------------------------------------------------------
# Shared-state helpers (Supabase-backed)
# -----------------------------------------------------------------------------
# The three globals above (waiting_patients, beds, interleaved_counter) still
# hold the data that every function below reads and mutates - none of that
# business logic changes. The only new rule is:
#   - call load_state() at the START of any endpoint that reads them
#   - call save_state() at the END of any endpoint that changes them
# load_state() overwrites the globals with whatever the last request (from
# ANY user, on ANY server instance) saved. save_state() pushes the current
# globals back so the next request - from this user or anyone else - sees
# the update. This is what makes "one user changes a patient, everyone
# sees it" work, and it's also what survives Render's free tier putting
# the whole process to sleep after 15 minutes of inactivity (in-memory
# Python lists do not survive that; a row in Postgres does).
def load_state():
    global waiting_patients, beds, interleaved_counter
    result = supabase.table(STATE_TABLE).select("data").eq("key", "state").execute()
    if result.data:
        payload = result.data[0]["data"]
        waiting_patients = [Patient(**p) for p in payload.get("waiting_patients", [])]
        beds = [HospitalBed(**b) for b in payload.get("beds", [])]
        interleaved_counter = payload.get("interleaved_counter", 0)
    else:
        # Nothing saved yet (first ever run) - seed with defaults and persist them
        waiting_patients = []
        beds = get_initial_beds()
        interleaved_counter = 0
        save_state()

def save_state():
    global waiting_patients, beds, interleaved_counter
    # model_dump(mode="json") turns datetimes/enums into plain JSON-safe values
    payload = {
        "waiting_patients": [p.model_dump(mode="json") for p in waiting_patients],
        "beds": [b.model_dump(mode="json") for b in beds],
        "interleaved_counter": interleaved_counter,
    }
    # upsert = insert the row if key="state" doesn't exist yet, otherwise overwrite it.
    # Note: this is "last write wins" - if two users click a button in the same
    # split second, one write can overwrite the other. Fine for a demo/small
    # team tool; a real hospital system would need row-level updates instead
    # of one big JSON blob, to avoid that.
    supabase.table(STATE_TABLE).upsert({"key": "state", "data": payload}).execute()

# -----------------------------------------------------------------------------
# AI Clinical Intent & Triage Engine (Groq)
# -----------------------------------------------------------------------------

def classify_patient_with_groq(data: IntakeRequest) -> tuple[Optional[OPDLane], int, float, str]:
    if not groq_api_key:
        return None, 15, 100.0, "Heuristic fallback (No API key provided)"

    prompt = f"""
    You are CareFlow AI, an intelligent clinical triage engine for hospitals.
    Evaluate this incoming patient:
    - Department Track: {data.track.value}
    - Chief Complaint: "{data.chief_complaint}"
    - Mobility Status: {data.mobility.value}
    - Severe Bleeding: {data.is_severe_bleeding}
    - Severe Trauma: {data.is_severe_trauma}

    Instructions:
    1. For OPD:
       - If complaint is a quick task (lab report review, prescription refill, follow-up clearance, suture removal):
         set "opd_lane": "EXPRESS", "estimated_duration_min": 2-5, "priority_score": 150.
       - If complex symptoms requiring full exam:
         set "opd_lane": "COMPREHENSIVE", "estimated_duration_min": 15-30, "priority_score": 100.
    2. For ER_WALKIN:
       - "opd_lane": null.
       - If CANNOT_STAND or severe bleeding/trauma:
         set "priority_score": 750-850, "estimated_duration_min": 35-45.
       - If stable walk-in:
         set "priority_score": 250-400, "estimated_duration_min": 15-20.

    Return strictly valid JSON matching this schema:
    {{
      "opd_lane": "EXPRESS" | "COMPREHENSIVE" | null,
      "estimated_duration_min": <integer>,
      "priority_score": <float>,
      "clinical_reasoning": "<concise 1-sentence rationale for the clinical staff>"
    }}
    """

    try:
        completion = groq_client.chat.completions.create(
            messages=[
                {"role": "system", "content": "You are a clinical decision support API that outputs strict JSON."},
                {"role": "user", "content": prompt}
            ],
            model=GROQ_MODEL,
            response_format={"type": "json_object"},
            temperature=0.1,
        )
        res = json.loads(completion.choices[0].message.content)
        lane = OPDLane(res["opd_lane"]) if res.get("opd_lane") else None
        duration = int(res.get("estimated_duration_min", 15))
        priority = float(res.get("priority_score", 100.0))
        reasoning = str(res.get("clinical_reasoning", "Classified by Groq AI"))
        return lane, duration, priority, reasoning
    except Exception as e:
        print(f"Groq API error: {e}")
        return None, 15, 120.0, f"AI fallback: {str(e)[:60]}"

# -----------------------------------------------------------------------------
# Interleaved Scheduling Engine
# -----------------------------------------------------------------------------
def calculate_interleaved_queue():
    global interleaved_counter
    now = datetime.now()

    # 1. Separate patients by track and lane
    er_patients = [p for p in waiting_patients if p.track == DepartmentTrack.ER_WALKIN]
    opd_express = [p for p in waiting_patients if p.track == DepartmentTrack.OPD and p.opd_lane == OPDLane.EXPRESS]
    opd_comp = [p for p in waiting_patients if p.track == DepartmentTrack.OPD and p.opd_lane == OPDLane.COMPREHENSIVE]

    # 2. Critical ER Trauma always sorted to the top by medical priority
    er_patients.sort(key=lambda p: p.priority_score, reverse=True)

    # 3. Interleave OPD: 1 Comprehensive -> 1 Express -> 1 Comprehensive -> 1 Express
    interleaved_opd = []
    idx_e, idx_c = 0, 0
    while idx_e < len(opd_express) or idx_c < len(opd_comp):
        if idx_c < len(opd_comp):
            interleaved_opd.append(opd_comp[idx_c])
            idx_c += 1
        if idx_e < len(opd_express):
            interleaved_opd.append(opd_express[idx_e])
            idx_e += 1

    # Exact current interleaved slots (avoids infinite counter inflation)
    interleaved_counter = min(len(opd_express), len(opd_comp))

    # 4. Reconstruct Queue: ER Emergencies FIRST, then Interleaved OPD
    waiting_patients.clear()
    waiting_patients.extend(er_patients)
    waiting_patients.extend(interleaved_opd)

    # 5. Compute Realistic Discrete Server ETAs
    # Track when each bed will become free (in minutes from now)
    er_bed_free_times = [
        b.time_remaining_min if b.current_patient is not None else 0
        for b in beds if b.department == DepartmentTrack.ER_WALKIN
    ]
    opd_bed_free_times = [
        b.time_remaining_min if b.current_patient is not None else 0
        for b in beds if b.department == DepartmentTrack.OPD
    ]

    for p in waiting_patients:
        p.wait_time_minutes = max(0, int((now - p.arrival_time).total_seconds() // 60))

        if p.track == DepartmentTrack.ER_WALKIN:
            # Patient gets the earliest bed that opens up
            er_bed_free_times.sort()
            earliest_available = er_bed_free_times[0]
            p.estimated_wait_min = earliest_available
            # That bed is now reserved by this patient for their estimated duration
            er_bed_free_times[0] += p.estimated_duration_min
        else:
            # OPD patient gets the earliest consulting desk
            opd_bed_free_times.sort()
            earliest_available = opd_bed_free_times[0]
            p.estimated_wait_min = earliest_available
            opd_bed_free_times[0] += p.estimated_duration_min
# -----------------------------------------------------------------------------
# Endpoints
# -----------------------------------------------------------------------------

@app.get("/api/stats", response_model=CareFlowMetrics)
def get_metrics():
    load_state()
    calculate_interleaved_queue()
    save_state()
    er_beds = [b for b in beds if b.department == DepartmentTrack.ER_WALKIN]
    er_occ = sum(1 for b in er_beds if b.current_patient is not None)
    opd_p = [p for p in waiting_patients if p.track == DepartmentTrack.OPD]
    avg_opd = round(sum(p.wait_time_minutes for p in opd_p) / max(1, len(opd_p)), 1)

    return CareFlowMetrics(
        opd_express_waiting=sum(1 for p in waiting_patients if p.opd_lane == OPDLane.EXPRESS),
        opd_comprehensive_waiting=sum(1 for p in waiting_patients if p.opd_lane == OPDLane.COMPREHENSIVE),
        er_walkin_waiting=sum(1 for p in waiting_patients if p.track == DepartmentTrack.ER_WALKIN),
        er_beds_occupied=er_occ,
        er_beds_total=len(er_beds),
        er_bed_occupancy_pct=round((er_occ / len(er_beds)) * 100, 1),
        avg_opd_wait_min=avg_opd,
        interleaved_slots_created=interleaved_counter
    )

@app.post("/api/triage", response_model=Patient)
def admit_patient(data: IntakeRequest):
    load_state()
    lane, duration, priority, reasoning = classify_patient_with_groq(data)
    patient = Patient(
        id=str(uuid.uuid4())[:8],
        name=data.name,
        age=data.age,
        track=data.track,
        opd_lane=lane,
        mobility=data.mobility,
        chief_complaint=data.chief_complaint,
        estimated_duration_min=duration,
        arrival_time=datetime.now(),
        priority_score=priority,
        clinical_reasoning=reasoning,
        status="WAITING"
    )
    waiting_patients.append(patient)
    calculate_interleaved_queue()
    save_state()
    return patient

@app.get("/api/queue", response_model=List[Patient])
def get_queue():
    load_state()
    calculate_interleaved_queue()
    save_state()
    return waiting_patients

@app.get("/api/beds", response_model=List[HospitalBed])
def get_beds():
    load_state()
    return beds

@app.post("/api/dispatch/assign")
def auto_assign():
    load_state()
    calculate_interleaved_queue()
    if not waiting_patients:
        return {"message": "Queue is empty."}

    for bed in beds:
        if bed.current_patient is None:
            for idx, p in enumerate(waiting_patients):
                if p.track == bed.department:
                    assigned = waiting_patients.pop(idx)
                    assigned.status = "IN_TREATMENT"
                    assigned.assigned_bed_id = bed.id
                    bed.current_patient = assigned
                    bed.time_remaining_min = assigned.estimated_duration_min
                    calculate_interleaved_queue()
                    save_state()
                    return {"status": "assigned", "bed": bed.name, "patient": assigned.name, "track": p.track}

    save_state()
    return {"message": "No compatible beds available."}

@app.post("/api/beds/{bed_id}/discharge")
def discharge_bed(bed_id: str):
    load_state()
    for b in beds:
        if b.id == bed_id:
            if not b.current_patient:
                raise HTTPException(status_code=400, detail="Bed already empty.")
            name = b.current_patient.name
            b.current_patient = None
            b.time_remaining_min = 0
            b.pending_discharge = False
            calculate_interleaved_queue()
            save_state()
            return {"status": "discharged", "patient": name, "bed": b.name}
    raise HTTPException(status_code=404, detail="Bed not found.")

@app.post("/api/beds/{bed_id}/flag-discharge")
def flag_pending_discharge(bed_id: str):
    load_state()
    for b in beds:
        if b.id == bed_id and b.current_patient:
            b.pending_discharge = True
            save_state()
            return {"status": "flagged", "bed": b.name}
    raise HTTPException(status_code=404, detail="Bed not found or empty.")

@app.post("/api/simulate/er-blindspot-surge")
def trigger_er_blindspot():
    severe_case = IntakeRequest(
        name="Walk-In Trauma Victim",
        age=38,
        track=DepartmentTrack.ER_WALKIN,
        chief_complaint="Severe arterial laceration from industrial machinery, collapsing",
        mobility=MobilityStatus.CANNOT_STAND,
        is_severe_bleeding=True,
        is_severe_trauma=True
    )
    p = admit_patient(severe_case)
    return {"alert": "CRITICAL_ER_WALKIN_DETECTED", "patient": p.name}

@app.post("/api/simulate/random-patient", response_model=Patient)
def generate_random_patient():
    """
    Hackathon Demo Feature:
    Injects a random clinical case (ranging from critical trauma to 3-minute refills)
    to demonstrate live queue prioritization and interleaved scheduling.
    """
    clinical_scenarios = [
        # Scenario A: Critical Cardiac Emergency (Highest priority, jumps to top)
        {
            "name": f"Patient-{random.randint(100, 999)}",
            "age": random.randint(45, 75),
            "track": DepartmentTrack.ER_WALKIN,
            "chief_complaint": "Acute substernal crushing chest pain radiating to jaw, cold sweats, dyspnea",
            "mobility": MobilityStatus.CANNOT_STAND,
            "is_severe_bleeding": False,
            "is_severe_trauma": True
        },
        # Scenario B: Severe Industrial Trauma (Highest priority, immediate ER bed)
        {
            "name": f"Patient-{random.randint(100, 999)}",
            "age": random.randint(22, 55),
            "track": DepartmentTrack.ER_WALKIN,
            "chief_complaint": "Deep arterial forearm laceration from angle grinder with pulsing hemorrhage",
            "mobility": MobilityStatus.CANNOT_STAND,
            "is_severe_bleeding": True,
            "is_severe_trauma": True
        },
        # Scenario C: Stable ER Injury (Moderate priority, 15m consult)
        {
            "name": f"Patient-{random.randint(100, 999)}",
            "age": random.randint(16, 40),
            "track": DepartmentTrack.ER_WALKIN,
            "chief_complaint": "Twisted right ankle during basketball, moderate swelling, able to hop on left leg",
            "mobility": MobilityStatus.ASSISTED,
            "is_severe_bleeding": False,
            "is_severe_trauma": False
        },
        # Scenario D: OPD Comprehensive (15-25m full exam)
        {
            "name": f"Patient-{random.randint(100, 999)}",
            "age": random.randint(28, 65),
            "track": DepartmentTrack.OPD,
            "chief_complaint": "Persistent lower quadrant abdominal tenderness with low-grade fever for 3 days",
            "mobility": MobilityStatus.AMBULATORY,
            "is_severe_bleeding": False,
            "is_severe_trauma": False
        },
        # Scenario E: OPD Express - Prescription Refill (2-3m micro-visit, interleaved)
        {
            "name": f"Patient-{random.randint(100, 999)}",
            "age": random.randint(50, 72),
            "track": DepartmentTrack.OPD,
            "chief_complaint": "Routine monthly medication refill for hypertension (Amlodipine), vitals stable",
            "mobility": MobilityStatus.AMBULATORY,
            "is_severe_bleeding": False,
            "is_severe_trauma": False
        },
        # Scenario F: OPD Express - Lab Report Clearance (2-4m micro-visit, interleaved)
        {
            "name": f"Patient-{random.randint(100, 999)}",
            "age": random.randint(25, 50),
            "track": DepartmentTrack.OPD,
            "chief_complaint": "Showing physician normal post-op blood test report for surgical clearance sign-off",
            "mobility": MobilityStatus.AMBULATORY,
            "is_severe_bleeding": False,
            "is_severe_trauma": False
        }
    ]

    case_data = random.choice(clinical_scenarios)
    patient = admit_patient(IntakeRequest(**case_data))
    return patient

@app.post("/api/demo/reset")
def reset_demo():
    global waiting_patients, beds, interleaved_counter
    waiting_patients = []
    beds = get_initial_beds()
    interleaved_counter = 0
    # Push the clean slate to Supabase FIRST. If we called admit_patient()
    # below before this, it would call load_state() and overwrite our
    # reset with whatever was still saved from before - this ordering
    # avoids that.
    save_state()

    admit_patient(IntakeRequest(name="James Wilson", age=52, track=DepartmentTrack.OPD, chief_complaint="Comprehensive workup: Chronic joint swelling and persistent fatigue", mobility=MobilityStatus.AMBULATORY))
    admit_patient(IntakeRequest(name="Amina Khan", age=30, track=DepartmentTrack.OPD, chief_complaint="Routine blood report review and prescription refill", mobility=MobilityStatus.AMBULATORY))
    admit_patient(IntakeRequest(name="Carlos Cruz", age=24, track=DepartmentTrack.ER_WALKIN, chief_complaint="Suspected wrist fracture from soccer fall", mobility=MobilityStatus.ASSISTED))

    return {"status": "reset_complete"}

# NOTE: the old "/dashboard" route that read dashboard.html off disk has been
# removed. The frontend is now deployed separately on GitHub Pages (see
# deployment steps), so this backend only needs to serve the /api/* routes.
