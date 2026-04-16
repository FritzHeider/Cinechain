import { useState, useEffect, useRef, useCallback } from "react";

const API = "http://localhost:8000";

const ASPECT_RATIOS = ["auto", "16:9", "9:16", "1:1", "4:3", "3:4", "21:9"];
const RESOLUTIONS = ["720p", "480p"];
const DURATIONS = ["auto", "4", "5", "6", "7", "8", "9", "10", "11", "12", "13", "14", "15"];

const STATUS_COLOR = {
  pending: "#888780",
  queued: "#378ADD",
  generating: "#BA7517",
  complete: "#3B6D11",
  error: "#A32D2D",
  draft: "#888780",
  rendering: "#BA7517",
};

const STATUS_BG = {
  pending: "#F1EFE8",
  queued: "#E6F1FB",
  generating: "#FAEEDA",
  complete: "#EAF3DE",
  error: "#FCEBEB",
  draft: "#F1EFE8",
  rendering: "#FAEEDA",
};

function Badge({ status, label }) {
  return (
    <span style={{
      fontSize: 11,
      fontWeight: 500,
      padding: "2px 8px",
      borderRadius: 20,
      background: STATUS_BG[status] || "#F1EFE8",
      color: STATUS_COLOR[status] || "#444",
      textTransform: "uppercase",
      letterSpacing: "0.05em",
    }}>{label || status}</span>
  );
}

function Spinner() {
  return (
    <span style={{
      display: "inline-block",
      width: 14, height: 14,
      border: "2px solid #D3D1C7",
      borderTopColor: "#378ADD",
      borderRadius: "50%",
      animation: "spin 0.7s linear infinite",
    }} />
  );
}

const spinKeyframes = `@keyframes spin { to { transform: rotate(360deg); } }`;

function ClipCard({ clip, index, total, onUpdate, onDelete, onMoveUp, onMoveDown, onGenerate, onPoll, projectStatus }) {
  const [expanded, setExpanded] = useState(false);
  const [form, setForm] = useState({
    name: clip.name || "",
    prompt: clip.prompt || "",
    image_url: clip.image_url || "",
    end_image_url: clip.end_image_url || "",
    resolution: clip.resolution || "720p",
    duration: clip.duration || "auto",
    aspect_ratio: clip.aspect_ratio || "auto",
    generate_audio: clip.generate_audio !== false,
  });
  const [dirty, setDirty] = useState(false);
  const [uploading, setUploading] = useState(false);
  const fileRef = useRef();
  const endFileRef = useRef();

  const set = (k, v) => { setForm(f => ({ ...f, [k]: v })); setDirty(true); };

  const handleUpload = async (file, field) => {
    setUploading(true);
    const fd = new FormData();
    fd.append("file", file);
    try {
      const r = await fetch(`${API}/upload/image`, { method: "POST", body: fd });
      const data = await r.json();
      set(field, data.url);
    } catch (e) { alert("Upload failed: " + e.message); }
    setUploading(false);
  };

  const handleSave = async () => {
    await onUpdate(clip.id, {
      ...form,
      end_image_url: form.end_image_url || null,
    });
    setDirty(false);
  };

  const isGenerating = clip.status === "queued" || clip.status === "generating";

  return (
    <div style={{
      background: "var(--color-background-primary)",
      border: `0.5px solid ${clip.status === "error" ? "#F09595" : "var(--color-border-tertiary)"}`,
      borderRadius: 12,
      marginBottom: 10,
      overflow: "hidden",
      transition: "border-color 0.2s",
    }}>
      {/* Card header */}
      <div style={{
        display: "flex", alignItems: "center", gap: 10, padding: "10px 14px",
        cursor: "pointer", userSelect: "none",
      }} onClick={() => setExpanded(e => !e)}>
        <span style={{
          width: 26, height: 26, borderRadius: "50%",
          background: "var(--color-background-secondary)",
          display: "flex", alignItems: "center", justifyContent: "center",
          fontSize: 12, fontWeight: 500, color: "var(--color-text-secondary)",
          flexShrink: 0,
        }}>{index + 1}</span>

        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 13, fontWeight: 500, color: "var(--color-text-primary)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {form.name || `Clip ${index + 1}`}
          </div>
          <div style={{ fontSize: 12, color: "var(--color-text-secondary)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", marginTop: 1 }}>
            {form.prompt || "No prompt yet"}
          </div>
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: 6, flexShrink: 0 }}>
          <Badge status={clip.status} />
          {isGenerating && <Spinner />}
          {clip.video_url && (
            <a href={clip.video_url} target="_blank" rel="noreferrer"
              style={{ fontSize: 11, color: "#185FA5", textDecoration: "none" }}
              onClick={e => e.stopPropagation()}>▶ preview</a>
          )}
          <span style={{ fontSize: 16, color: "var(--color-text-tertiary)", marginLeft: 4 }}>{expanded ? "▲" : "▼"}</span>
        </div>
      </div>

      {/* Expanded editor */}
      {expanded && (
        <div style={{ borderTop: "0.5px solid var(--color-border-tertiary)", padding: "14px 14px 12px" }}>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10, marginBottom: 10 }}>
            <div>
              <label style={labelStyle}>Clip name</label>
              <input value={form.name} onChange={e => set("name", e.target.value)} placeholder="Scene title..." style={inputStyle} />
            </div>
            <div>
              <label style={labelStyle}>Aspect ratio</label>
              <select value={form.aspect_ratio} onChange={e => set("aspect_ratio", e.target.value)} style={inputStyle}>
                {ASPECT_RATIOS.map(r => <option key={r}>{r}</option>)}
              </select>
            </div>
          </div>

          <div style={{ marginBottom: 10 }}>
            <label style={labelStyle}>Motion prompt <span style={{ color: "#A32D2D" }}>*</span></label>
            <textarea
              value={form.prompt}
              onChange={e => set("prompt", e.target.value)}
              placeholder="Describe the motion, action, and mood of this clip..."
              rows={3}
              style={{ ...inputStyle, resize: "vertical", lineHeight: 1.5 }}
            />
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10, marginBottom: 10 }}>
            <div>
              <label style={labelStyle}>Start frame image URL</label>
              <div style={{ display: "flex", gap: 6 }}>
                <input value={form.image_url} onChange={e => set("image_url", e.target.value)} placeholder="https://..." style={{ ...inputStyle, flex: 1 }} />
                <input ref={fileRef} type="file" accept="image/jpeg,image/png,image/webp" style={{ display: "none" }}
                  onChange={e => e.target.files[0] && handleUpload(e.target.files[0], "image_url")} />
                <button onClick={() => fileRef.current.click()} style={smallBtnStyle} title="Upload image">
                  {uploading ? <Spinner /> : "↑"}
                </button>
              </div>
              {form.image_url && <img src={form.image_url} alt="" style={{ width: "100%", height: 80, objectFit: "cover", borderRadius: 6, marginTop: 6 }} />}
            </div>
            <div>
              <label style={labelStyle}>End frame image URL <span style={{ color: "var(--color-text-tertiary)" }}>(optional)</span></label>
              <div style={{ display: "flex", gap: 6 }}>
                <input value={form.end_image_url} onChange={e => set("end_image_url", e.target.value)} placeholder="https://..." style={{ ...inputStyle, flex: 1 }} />
                <input ref={endFileRef} type="file" accept="image/jpeg,image/png,image/webp" style={{ display: "none" }}
                  onChange={e => e.target.files[0] && handleUpload(e.target.files[0], "end_image_url")} />
                <button onClick={() => endFileRef.current.click()} style={smallBtnStyle} title="Upload end frame">↑</button>
              </div>
              {form.end_image_url && <img src={form.end_image_url} alt="" style={{ width: "100%", height: 80, objectFit: "cover", borderRadius: 6, marginTop: 6 }} />}
            </div>
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr auto", gap: 10, alignItems: "end", marginBottom: 12 }}>
            <div>
              <label style={labelStyle}>Resolution</label>
              <select value={form.resolution} onChange={e => set("resolution", e.target.value)} style={inputStyle}>
                {RESOLUTIONS.map(r => <option key={r}>{r}</option>)}
              </select>
            </div>
            <div>
              <label style={labelStyle}>Duration (sec)</label>
              <select value={form.duration} onChange={e => set("duration", e.target.value)} style={inputStyle}>
                {DURATIONS.map(d => <option key={d}>{d}</option>)}
              </select>
            </div>
            <div>
              <label style={labelStyle}>Audio</label>
              <select value={form.generate_audio ? "yes" : "no"} onChange={e => set("generate_audio", e.target.value === "yes")} style={inputStyle}>
                <option value="yes">Generate audio</option>
                <option value="no">No audio</option>
              </select>
            </div>
          </div>

          {clip.error_message && (
            <div style={{ background: "#FCEBEB", border: "0.5px solid #F09595", borderRadius: 6, padding: "8px 12px", fontSize: 12, color: "#A32D2D", marginBottom: 10 }}>
              {clip.error_message}
            </div>
          )}

          {/* Action row */}
          <div style={{ display: "flex", gap: 8, justifyContent: "space-between", flexWrap: "wrap" }}>
            <div style={{ display: "flex", gap: 6 }}>
              <button style={smallBtnStyle} onClick={() => onMoveUp(index)} disabled={index === 0} title="Move up">↑</button>
              <button style={smallBtnStyle} onClick={() => onMoveDown(index)} disabled={index === total - 1} title="Move down">↓</button>
              <button style={{ ...smallBtnStyle, color: "#A32D2D", borderColor: "#F09595" }} onClick={() => onDelete(clip.id)} title="Delete clip">✕</button>
            </div>
            <div style={{ display: "flex", gap: 6 }}>
              {dirty && (
                <button onClick={handleSave} style={{ ...smallBtnStyle, background: "#E6F1FB", borderColor: "#B5D4F4", color: "#185FA5" }}>Save changes</button>
              )}
              {isGenerating ? (
                <button onClick={() => onPoll(clip.id)} style={smallBtnStyle}><Spinner /> Poll status</button>
              ) : (
                <button
                  onClick={() => onGenerate(clip.id)}
                  disabled={!form.image_url || !form.prompt || projectStatus === "rendering"}
                  style={{ ...smallBtnStyle, background: "#EAF3DE", borderColor: "#C0DD97", color: "#3B6D11" }}
                >
                  ▶ Generate clip
                </button>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function ProjectView({ project, onBack, onRefresh }) {
  const [clips, setClips] = useState(project.clips || []);
  const [proj, setProj] = useState(project);
  const [rendering, setRendering] = useState(false);
  const [addingClip, setAddingClip] = useState(false);
  const [pollInterval, setPollInterval] = useState(null);
  const [logs, setLogs] = useState([]);

  const log = msg => setLogs(l => [`${new Date().toLocaleTimeString()} ${msg}`, ...l.slice(0, 19)]);

  const loadProject = useCallback(async () => {
    const r = await fetch(`${API}/projects/${proj.id}`);
    const data = await r.json();
    setProj(data);
    setClips(data.clips || []);
  }, [proj.id]);

  useEffect(() => {
    loadProject();
  }, []);

  useEffect(() => {
    if (proj.status === "rendering") {
      const iv = setInterval(() => {
        loadProject();
        log("Polling render status...");
      }, 6000);
      setPollInterval(iv);
      return () => clearInterval(iv);
    } else if (pollInterval) {
      clearInterval(pollInterval);
      setPollInterval(null);
    }
  }, [proj.status]);

  const addClip = async () => {
    setAddingClip(true);
    const r = await fetch(`${API}/projects/${proj.id}/clips`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        prompt: "",
        image_url: "https://example.com/placeholder.jpg",
        name: `Scene ${clips.length + 1}`,
        order: clips.length,
      }),
    });
    const clip = await r.json();
    setClips(c => [...c, clip]);
    log(`Added clip: Scene ${clips.length + 1}`);
    setAddingClip(false);
  };

  const updateClip = async (clipId, updates) => {
    const r = await fetch(`${API}/projects/${proj.id}/clips/${clipId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(updates),
    });
    const updated = await r.json();
    setClips(c => c.map(x => x.id === clipId ? updated : x));
    log(`Saved clip ${clipId}`);
  };

  const deleteClip = async (clipId) => {
    if (!confirm("Delete this clip?")) return;
    await fetch(`${API}/projects/${proj.id}/clips/${clipId}`, { method: "DELETE" });
    setClips(c => c.filter(x => x.id !== clipId));
    log(`Deleted clip ${clipId}`);
  };

  const moveClip = async (index, direction) => {
    const newClips = [...clips];
    const target = index + direction;
    if (target < 0 || target >= newClips.length) return;
    [newClips[index], newClips[target]] = [newClips[target], newClips[index]];
    const ids = newClips.map(c => c.id);
    const r = await fetch(`${API}/projects/${proj.id}/clips/reorder`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(ids),
    });
    const updated = await r.json();
    setClips(updated);
  };

  const generateClip = async (clipId) => {
    const r = await fetch(`${API}/projects/${proj.id}/clips/${clipId}/generate`, { method: "POST" });
    const updated = await r.json();
    setClips(c => c.map(x => x.id === clipId ? updated : x));
    log(`Submitted clip ${clipId} → fal request: ${updated.fal_request_id}`);
  };

  const pollClip = async (clipId) => {
    const r = await fetch(`${API}/projects/${proj.id}/clips/${clipId}/poll`);
    const updated = await r.json();
    setClips(c => c.map(x => x.id === clipId ? updated : x));
    log(`Polled clip ${clipId}: ${updated.status}`);
  };

  const startRender = async (parallel = false) => {
    setRendering(true);
    const r = await fetch(`${API}/projects/${proj.id}/render`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ parallel, stitch: true }),
    });
    const data = await r.json();
    log(`Render started: ${data.message}`);
    await loadProject();
    setRendering(false);
  };

  const stitch = async () => {
    await fetch(`${API}/projects/${proj.id}/render/stitch?crossfade=true`, { method: "POST" });
    log("Stitching triggered...");
    await loadProject();
  };

  const completeClips = clips.filter(c => c.status === "complete");
  const allComplete = clips.length > 0 && clips.every(c => c.status === "complete");

  return (
    <div style={{ maxWidth: 800, margin: "0 auto", padding: "0 0 40px" }}>
      <style>{spinKeyframes}</style>

      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 20 }}>
        <button onClick={onBack} style={{ ...smallBtnStyle, fontSize: 13 }}>← Projects</button>
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 18, fontWeight: 500, color: "var(--color-text-primary)" }}>{proj.name}</div>
          {proj.description && <div style={{ fontSize: 13, color: "var(--color-text-secondary)", marginTop: 2 }}>{proj.description}</div>}
        </div>
        <Badge status={proj.status} />
        {(proj.status === "rendering") && <Spinner />}
      </div>

      {/* Final video */}
      {proj.final_video_url && (
        <div style={{ background: "#EAF3DE", border: "0.5px solid #C0DD97", borderRadius: 12, padding: "12px 16px", marginBottom: 16, display: "flex", alignItems: "center", gap: 12 }}>
          <span style={{ fontSize: 20 }}>🎬</span>
          <div style={{ flex: 1 }}>
            <div style={{ fontWeight: 500, color: "#3B6D11", fontSize: 14 }}>Final video ready</div>
            <div style={{ fontSize: 12, color: "#639922", marginTop: 2, fontFamily: "var(--font-mono)", wordBreak: "break-all" }}>{proj.final_video_url}</div>
          </div>
          <a href={`${API}/projects/${proj.id}/download`} style={{ ...smallBtnStyle, textDecoration: "none", background: "#C0DD97", borderColor: "#97C459", color: "#27500A" }}>⬇ Download</a>
        </div>
      )}

      {/* Render controls */}
      <div style={{ background: "var(--color-background-secondary)", borderRadius: 10, padding: "12px 14px", marginBottom: 16, display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
        <span style={{ fontSize: 13, color: "var(--color-text-secondary)", marginRight: 4 }}>Render:</span>
        <button
          onClick={() => startRender(false)}
          disabled={rendering || clips.length === 0 || proj.status === "rendering"}
          style={{ ...smallBtnStyle, background: "#E6F1FB", borderColor: "#B5D4F4", color: "#185FA5" }}
        >▶ Sequential (recommended)</button>
        <button
          onClick={() => startRender(true)}
          disabled={rendering || clips.length === 0 || proj.status === "rendering"}
          style={smallBtnStyle}
        >⚡ Parallel</button>
        {completeClips.length > 0 && !allComplete && (
          <button onClick={stitch} style={{ ...smallBtnStyle, background: "#FAEEDA", borderColor: "#FAC775", color: "#854F0B" }}>✂ Stitch ready clips</button>
        )}
        <span style={{ fontSize: 12, color: "var(--color-text-tertiary)", marginLeft: "auto" }}>
          {completeClips.length}/{clips.length} clips ready
        </span>
      </div>

      {/* Clip list */}
      {clips.length === 0 ? (
        <div style={{ textAlign: "center", padding: "40px 20px", color: "var(--color-text-tertiary)", fontSize: 14 }}>
          No clips yet. Add your first scene below.
        </div>
      ) : (
        clips.map((clip, i) => (
          <ClipCard
            key={clip.id}
            clip={clip}
            index={i}
            total={clips.length}
            onUpdate={updateClip}
            onDelete={deleteClip}
            onMoveUp={() => moveClip(i, -1)}
            onMoveDown={() => moveClip(i, 1)}
            onGenerate={generateClip}
            onPoll={pollClip}
            projectStatus={proj.status}
          />
        ))
      )}

      <button
        onClick={addClip}
        disabled={addingClip}
        style={{ width: "100%", padding: "10px", borderRadius: 10, border: "1px dashed var(--color-border-secondary)", background: "transparent", cursor: "pointer", fontSize: 14, color: "var(--color-text-secondary)", marginTop: 4 }}
      >
        {addingClip ? "Adding…" : "+ Add scene"}
      </button>

      {/* Logs */}
      {logs.length > 0 && (
        <div style={{ marginTop: 20, background: "var(--color-background-secondary)", borderRadius: 10, padding: "10px 12px" }}>
          <div style={{ fontSize: 11, fontWeight: 500, color: "var(--color-text-tertiary)", marginBottom: 6, textTransform: "uppercase", letterSpacing: "0.07em" }}>Activity log</div>
          {logs.map((l, i) => (
            <div key={i} style={{ fontSize: 12, color: "var(--color-text-secondary)", fontFamily: "var(--font-mono)", padding: "2px 0" }}>{l}</div>
          ))}
        </div>
      )}
    </div>
  );
}

function ProjectList({ onSelect }) {
  const [projects, setProjects] = useState([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState("");
  const [newDesc, setNewDesc] = useState("");
  const [error, setError] = useState(null);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const r = await fetch(`${API}/projects`);
      if (!r.ok) throw new Error(`API error: ${r.status}`);
      setProjects(await r.json());
    } catch (e) {
      setError(`Cannot connect to backend. Start with: cd backend && uvicorn main:app --reload\n\n${e.message}`);
    }
    setLoading(false);
  };

  useEffect(() => { load(); }, []);

  const createProject = async () => {
    if (!newName.trim()) return;
    const r = await fetch(`${API}/projects`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: newName, description: newDesc }),
    });
    const p = await r.json();
    setProjects(ps => [{ ...p, clip_count: 0 }, ...ps]);
    setNewName("");
    setNewDesc("");
    setCreating(false);
    onSelect(p);
  };

  const deleteProject = async (id, e) => {
    e.stopPropagation();
    if (!confirm("Delete this project and all its clips?")) return;
    await fetch(`${API}/projects/${id}`, { method: "DELETE" });
    setProjects(ps => ps.filter(p => p.id !== id));
  };

  return (
    <div style={{ maxWidth: 700, margin: "0 auto", padding: "0 0 40px" }}>
      <style>{spinKeyframes}</style>

      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 20 }}>
        <div>
          <div style={{ fontSize: 22, fontWeight: 500, color: "var(--color-text-primary)" }}>CineChain</div>
          <div style={{ fontSize: 13, color: "var(--color-text-secondary)", marginTop: 2 }}>Cinematic multi-clip video generator · Seedance 2.0</div>
        </div>
        <button onClick={() => setCreating(c => !c)} style={{ ...smallBtnStyle, background: creating ? "#FCEBEB" : "#EAF3DE", borderColor: creating ? "#F09595" : "#C0DD97", color: creating ? "#A32D2D" : "#3B6D11" }}>
          {creating ? "✕ Cancel" : "+ New project"}
        </button>
      </div>

      {creating && (
        <div style={{ background: "var(--color-background-secondary)", borderRadius: 12, padding: "14px", marginBottom: 16 }}>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 2fr", gap: 10, marginBottom: 10 }}>
            <div>
              <label style={labelStyle}>Project name</label>
              <input value={newName} onChange={e => setNewName(e.target.value)} placeholder="My feature film..." style={inputStyle} autoFocus
                onKeyDown={e => e.key === "Enter" && createProject()} />
            </div>
            <div>
              <label style={labelStyle}>Description</label>
              <input value={newDesc} onChange={e => setNewDesc(e.target.value)} placeholder="Brief synopsis or notes..." style={inputStyle} />
            </div>
          </div>
          <button onClick={createProject} disabled={!newName.trim()} style={{ ...smallBtnStyle, background: "#E6F1FB", borderColor: "#B5D4F4", color: "#185FA5" }}>Create project →</button>
        </div>
      )}

      {error && (
        <div style={{ background: "#FCEBEB", border: "0.5px solid #F09595", borderRadius: 10, padding: "12px 14px", marginBottom: 16, fontSize: 13, color: "#A32D2D", fontFamily: "var(--font-mono)", whiteSpace: "pre-wrap" }}>
          {error}
        </div>
      )}

      {loading ? (
        <div style={{ textAlign: "center", padding: 40 }}><Spinner /></div>
      ) : projects.length === 0 ? (
        <div style={{ textAlign: "center", padding: "50px 20px", color: "var(--color-text-tertiary)", fontSize: 14 }}>
          No projects yet. Create your first cinematic project above.
        </div>
      ) : (
        projects.map(p => (
          <div key={p.id}
            onClick={() => onSelect(p)}
            style={{
              background: "var(--color-background-primary)",
              border: "0.5px solid var(--color-border-tertiary)",
              borderRadius: 12,
              padding: "12px 16px",
              marginBottom: 8,
              cursor: "pointer",
              display: "flex",
              alignItems: "center",
              gap: 12,
              transition: "border-color 0.15s",
            }}
            onMouseEnter={e => e.currentTarget.style.borderColor = "var(--color-border-secondary)"}
            onMouseLeave={e => e.currentTarget.style.borderColor = "var(--color-border-tertiary)"}
          >
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontWeight: 500, fontSize: 14, color: "var(--color-text-primary)" }}>{p.name}</div>
              {p.description && <div style={{ fontSize: 12, color: "var(--color-text-secondary)", marginTop: 2 }}>{p.description}</div>}
              <div style={{ fontSize: 11, color: "var(--color-text-tertiary)", marginTop: 4 }}>
                {p.clip_count} clip{p.clip_count !== 1 ? "s" : ""} · {new Date(p.updated_at).toLocaleDateString()}
              </div>
            </div>
            <Badge status={p.status} />
            {p.final_video_url && <span style={{ fontSize: 11, color: "#3B6D11" }}>✓ video</span>}
            <button
              onClick={(e) => deleteProject(p.id, e)}
              style={{ ...smallBtnStyle, color: "#A32D2D", borderColor: "#F09595", fontSize: 11, padding: "3px 8px" }}
            >✕</button>
          </div>
        ))
      )}
    </div>
  );
}

// Shared styles
const labelStyle = {
  display: "block",
  fontSize: 11,
  fontWeight: 500,
  color: "var(--color-text-secondary)",
  textTransform: "uppercase",
  letterSpacing: "0.06em",
  marginBottom: 5,
};

const inputStyle = {
  width: "100%",
  boxSizing: "border-box",
  padding: "7px 10px",
  fontSize: 13,
  borderRadius: 7,
  border: "0.5px solid var(--color-border-secondary)",
  background: "var(--color-background-primary)",
  color: "var(--color-text-primary)",
  fontFamily: "var(--font-sans)",
};

const smallBtnStyle = {
  padding: "5px 12px",
  fontSize: 12,
  fontWeight: 500,
  borderRadius: 7,
  border: "0.5px solid var(--color-border-secondary)",
  background: "var(--color-background-primary)",
  color: "var(--color-text-primary)",
  cursor: "pointer",
  display: "inline-flex",
  alignItems: "center",
  gap: 5,
  whiteSpace: "nowrap",
};

export default function App() {
  const [selected, setSelected] = useState(null);

  if (selected) {
    return <ProjectView project={selected} onBack={() => setSelected(null)} onRefresh={() => {}} />;
  }
  return <ProjectList onSelect={setSelected} />;
}
