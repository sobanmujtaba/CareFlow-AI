import React, { useState, useEffect } from "react";
import { Activity, AlertTriangle, UserPlus, Bed, RefreshCw, Send, Dices } from "lucide-react";

const API = "http://localhost:8000";

export default function App() {
  const [queue, setQueue] = useState([]);
  const [beds, setBeds] = useState([]);
  const [stats, setStats] = useState(null);
  const [form, setForm] = useState({
    name: "",
    age: "",
    track: "OPD",
    mobility: "AMBULATORY",
    chief_complaint: "",
    is_severe_bleeding: false,
    is_severe_trauma: false,
  });

  const fetchData = async () => {
    try {
      const [sRes, qRes, bRes] = await Promise.all([
        fetch(`${API}/api/stats`),
        fetch(`${API}/api/queue`),
        fetch(`${API}/api/beds`),
      ]);
      if (sRes.ok) setStats(await sRes.json());
      if (qRes.ok) setQueue(await qRes.json());
      if (bRes.ok) setBeds(await bRes.json());
    } catch (e) {
      console.error("Fetch error:", e);
    }
  };

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 2000);
    return () => clearInterval(interval);
  }, []);

  const handleIntake = async (e) => {
    e.preventDefault();
    try {
      const res = await fetch(`${API}/api/triage`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ...form,
          age: parseInt(form.age) || 30,
        }),
      });
      if (res.ok) {
        setForm({
          name: "",
          age: "",
          track: "OPD",
          mobility: "AMBULATORY",
          chief_complaint: "",
          is_severe_bleeding: false,
          is_severe_trauma: false,
        });
        fetchData();
      }
    } catch (err) {
      console.error("Intake failed:", err);
    }
  };

  const getBadge = (p) => {
    if (p.track === "ER_WALKIN") {
      return (
        <span className="px-2 py-0.5 rounded bg-rose-500/20 text-rose-400 font-bold border border-rose-500/40 text-xs">
          🚨 ER Walk-In
        </span>
      );
    }
    if (p.opd_lane === "EXPRESS") {
      return (
        <span className="px-2 py-0.5 rounded bg-emerald-500/20 text-emerald-400 font-semibold border border-emerald-500/40 text-xs">
          ⚡ Express
        </span>
      );
    }
    return (
      <span className="px-2 py-0.5 rounded bg-amber-500/10 text-amber-400 border border-amber-500/30 text-xs">
        🩺 Comprehensive
      </span>
    );
  };

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 p-6 space-y-6">
      {/* Top Header */}
      <header className="flex justify-between items-center border-b border-slate-800 pb-4">
        <div className="flex items-center space-x-3">
          <Activity className="w-5 h-5 text-emerald-400 animate-pulse" />
          <div>
            <h1 className="text-lg font-bold tracking-wider uppercase font-mono">CareFlow AI</h1>
            <p className="text-xs text-slate-400 font-mono">OPD Express Interleaving & ER Walk-In Bed System</p>
          </div>
        </div>
        <div className="flex space-x-2.5 text-xs font-mono">
          <button
            onClick={() => fetch(`${API}/api/demo/reset`, { method: "POST" }).then(fetchData)}
            className="px-3 py-1.5 bg-slate-900 border border-slate-700 rounded hover:bg-slate-800 flex items-center space-x-1 transition"
          >
            <RefreshCw className="w-3.5 h-3.5" /> <span>Reset Demo</span>
          </button>
          <button
            onClick={() => fetch(`${API}/api/simulate/random-patient`, { method: "POST" }).then(fetchData)}
            className="px-3 py-1.5 bg-indigo-600 hover:bg-indigo-500 rounded font-medium flex items-center space-x-1.5 shadow-md shadow-indigo-950 transition"
          >
            <Dices className="w-3.5 h-3.5" /> <span>Add Random Patient</span>
          </button>
          <button
            onClick={() => fetch(`${API}/api/dispatch/assign`, { method: "POST" }).then(fetchData)}
            className="px-3 py-1.5 bg-emerald-600 rounded hover:bg-emerald-500 font-semibold flex items-center space-x-1.5 transition"
          >
            <Send className="w-3.5 h-3.5" /> <span>Auto-Dispatch Bed</span>
          </button>
          <button
            onClick={() => fetch(`${API}/api/simulate/er-blindspot-surge`, { method: "POST" }).then(fetchData)}
            className="px-3 py-1.5 bg-rose-600 rounded hover:bg-rose-500 font-bold flex items-center space-x-1.5 shadow-lg shadow-rose-950 transition"
          >
            <AlertTriangle className="w-3.5 h-3.5" /> <span>🚨 ER Blind Spot Alert</span>
          </button>
        </div>
      </header>

      {/* KPI Cards */}
      {stats && (
        <section className="grid grid-cols-4 gap-4 font-mono">
          <div className="bg-slate-900 border border-slate-800 p-4 rounded-lg">
            <span className="text-xs text-slate-400">OPD EXPRESS WAITING</span>
            <p className="text-2xl font-bold mt-1 text-emerald-400">{stats.opd_express_waiting}</p>
            <span className="text-[10px] text-slate-500">2–5 min micro visits</span>
          </div>
          <div className="bg-slate-900 border border-slate-800 p-4 rounded-lg">
            <span className="text-xs text-slate-400">OPD COMPREHENSIVE</span>
            <p className="text-2xl font-bold mt-1 text-amber-400">{stats.opd_comprehensive_waiting}</p>
            <span className="text-[10px] text-slate-500">15–30 min full exams</span>
          </div>
          <div className="bg-slate-900 border border-slate-800 p-4 rounded-lg">
            <span className="text-xs text-slate-400">ER BED OCCUPANCY</span>
            <p className="text-2xl font-bold mt-1">{stats.er_bed_occupancy_pct}%</p>
            <span className="text-[10px] text-slate-500">
              {stats.er_beds_occupied}/{stats.er_beds_total} beds
            </span>
          </div>
          <div className="bg-slate-900 border border-slate-800 p-4 rounded-lg">
            <span className="text-xs text-slate-400 text-cyan-400">INTERLEAVED SLOTS</span>
            <p className="text-2xl font-bold mt-1 text-cyan-400">{stats.interleaved_slots_created}</p>
            <span className="text-[10px] text-slate-500">Fast-tracked micro-gaps</span>
          </div>
        </section>
      )}

      {/* Main Workspace */}
      <main className="grid grid-cols-12 gap-6">
        {/* Live Queue */}
        <div className="col-span-7 bg-slate-900 border border-slate-800 rounded-lg p-5">
          <div className="flex justify-between items-center mb-4">
            <h2 className="text-xs uppercase font-mono text-slate-400 tracking-wider">
              Intelligent Interleaved Queue
            </h2>
            <span className="text-xs font-mono text-slate-500">Auto-refresh: 2s</span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs font-mono">
              <thead className="text-slate-500 border-b border-slate-800 pb-2">
                <tr>
                  <th className="py-2">Track</th>
                  <th className="py-2">Patient</th>
                  <th className="py-2">Complaint & AI Analysis</th>
                  <th className="py-2">Est.</th>
                  <th className="py-2">ETA</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/60">
                {queue.length === 0 ? (
                  <tr>
                    <td colSpan="5" className="text-center py-6 text-slate-600">
                      Queue is empty.
                    </td>
                  </tr>
                ) : (
                  queue.map((p) => (
                    <tr key={p.id} className="hover:bg-slate-800/30 transition">
                      <td className="py-2.5">{getBadge(p)}</td>
                      <td className="font-sans font-medium">
                        {p.name} <span className="text-slate-500 text-[10px]">({p.age}y)</span>
                      </td>
                      <td className="text-slate-400 max-w-[240px]">
                        <div className="truncate font-sans">
                          {p.chief_complaint} <span className="text-slate-500 text-[10px]">({p.mobility})</span>
                        </div>
                        <div className="text-[10px] text-cyan-400 font-mono mt-0.5">
                          🧠 AI: {p.clinical_reasoning || "Triage validated"}
                        </div>
                      </td>
                      <td className="text-slate-300 font-bold">{p.estimated_duration_min}m</td>
                      <td className="text-amber-400 font-bold">~{p.estimated_wait_min}m</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>

        {/* Right Column: Beds & Intake */}
        <div className="col-span-5 space-y-6">
          {/* Beds Panel */}
          <div className="bg-slate-900 border border-slate-800 rounded-lg p-5">
            <h2 className="text-xs uppercase font-mono text-slate-400 mb-3 tracking-wider">
              Beds & Clinical Desks
            </h2>
            <div className="space-y-3">
              {beds.map((b) => (
                <div
                  key={b.id}
                  className={`p-3 rounded border flex justify-between items-center text-xs ${
                    b.current_patient
                      ? b.pending_discharge
                        ? "border-cyan-500/40 bg-cyan-950/20"
                        : "border-amber-500/30 bg-slate-950/80"
                      : "border-slate-800 bg-slate-950/40"
                  }`}
                >
                  <div>
                    <div className="flex items-center space-x-2">
                      <Bed className="w-3.5 h-3.5 text-slate-400" />
                      <span className="font-semibold">{b.name}</span>
                      <span className="text-[10px] text-slate-500 font-mono">({b.department})</span>
                    </div>
                    <p className="text-slate-500 text-[11px] mt-0.5">{b.assigned_clinician}</p>
                    {b.current_patient ? (
                      <p className="text-emerald-400 font-mono mt-1 text-[11px]">
                        Occupied: {b.current_patient.name}{" "}
                        {b.pending_discharge && (
                          <span className="text-cyan-400 font-bold">[Pending Discharge]</span>
                        )}
                      </p>
                    ) : (
                      <p className="text-slate-600 font-mono text-[11px]">Available</p>
                    )}
                  </div>
                  <div className="flex space-x-1">
                    {b.current_patient && !b.pending_discharge && (
                      <button
                        onClick={() =>
                          fetch(`${API}/api/beds/${b.id}/flag-discharge`, { method: "POST" }).then(fetchData)
                        }
                        className="px-2 py-1 bg-slate-800 hover:bg-cyan-900/40 text-cyan-300 rounded border border-slate-700 text-[10px] font-mono transition"
                      >
                        Flag Discharge
                      </button>
                    )}
                    {b.current_patient && (
                      <button
                        onClick={() =>
                          fetch(`${API}/api/beds/${b.id}/discharge`, { method: "POST" }).then(fetchData)
                        }
                        className="px-2 py-1 bg-slate-800 hover:bg-rose-900/40 text-rose-300 rounded border border-slate-700 text-[10px] font-mono transition"
                      >
                        Discharge
                      </button>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Rapid Intake Desk */}
          <div className="bg-slate-900 border border-slate-800 rounded-lg p-5">
            <h2 className="text-xs uppercase font-mono text-slate-400 mb-3 tracking-wider">
              Rapid Intake Desk (&lt;20s)
            </h2>
            <form onSubmit={handleIntake} className="space-y-3 text-xs">
              <div className="grid grid-cols-2 gap-2">
                <input
                  type="text"
                  placeholder="Patient Name"
                  required
                  value={form.name}
                  onChange={(e) => setForm({ ...form, name: e.target.value })}
                  className="bg-slate-950 border border-slate-800 rounded p-2 text-slate-200 outline-none focus:border-slate-700"
                />
                <input
                  type="number"
                  placeholder="Age"
                  required
                  value={form.age}
                  onChange={(e) => setForm({ ...form, age: e.target.value })}
                  className="bg-slate-950 border border-slate-800 rounded p-2 text-slate-200 outline-none focus:border-slate-700"
                />
              </div>

              <div className="grid grid-cols-2 gap-2">
                <select
                  value={form.track}
                  onChange={(e) => setForm({ ...form, track: e.target.value })}
                  className="bg-slate-950 border border-slate-800 rounded p-2 text-slate-200 outline-none"
                >
                  <option value="OPD">OPD (Outpatient)</option>
                  <option value="ER_WALKIN">ER (Severe Walk-In)</option>
                </select>
                <select
                  value={form.mobility}
                  onChange={(e) => setForm({ ...form, mobility: e.target.value })}
                  className="bg-slate-950 border border-slate-800 rounded p-2 text-slate-200 outline-none"
                >
                  <option value="AMBULATORY">Ambulatory (Walking)</option>
                  <option value="ASSISTED">Assisted (Wheelchair)</option>
                  <option value="CANNOT_STAND">⚠️ Cannot Stand / Collapsed</option>
                </select>
              </div>

              <input
                type="text"
                placeholder="Complaint: e.g. Report review / refill OR Chest pain / bleeding"
                required
                value={form.chief_complaint}
                onChange={(e) => setForm({ ...form, chief_complaint: e.target.value })}
                className="w-full bg-slate-950 border border-slate-800 rounded p-2 text-slate-200 outline-none focus:border-slate-700"
              />

              <div className="flex items-center space-x-4 pt-1">
                <label className="flex items-center space-x-1.5 text-slate-400 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={form.is_severe_bleeding}
                    onChange={(e) => setForm({ ...form, is_severe_bleeding: e.target.checked })}
                    className="rounded bg-slate-950 border-slate-800"
                  />
                  <span>Severe Bleeding</span>
                </label>
                <label className="flex items-center space-x-1.5 text-slate-400 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={form.is_severe_trauma}
                    onChange={(e) => setForm({ ...form, is_severe_trauma: e.target.checked })}
                    className="rounded bg-slate-950 border-slate-800"
                  />
                  <span>Severe Trauma</span>
                </label>
              </div>

              <button
                type="submit"
                className="w-full py-2 bg-slate-800 hover:bg-slate-700 font-mono font-medium rounded flex items-center justify-center space-x-1 transition"
              >
                <UserPlus className="w-3.5 h-3.5" /> <span>Submit Intake</span>
              </button>
            </form>
          </div>
        </div>
      </main>
    </div>
  );
}