import { useState, useEffect, useRef, useCallback } from "react";

const API = "http://localhost:8000";

const ASPECT_RATIOS = ["auto", "16:9", "9:16", "1:1", "4:3", "3:4", "21:9"];
const RESOLUTIONS = ["720p", "480p"];
const DURATIONS = ["auto", "4", "5", "6", "7", "8", "9", "10", "11", "12", "13", "14", "15"];
const TRANSITION_TYPES = [
  "fade", "dissolve", "wipeleft", "wiperight", "wipeup", "wipedown",
  "slidedown", "slideup", "slideleft", "slideright",
  "smoothleft", "smoothright", "circleopen", "circleclose", "radial",
];

const PROMPT_PRESETS = [
  { label: "Slow dolly forward", value: "Slow dolly forward, subtle depth of field, cinematic" },
  { label: "Pan left", value: "Smooth pan left, steady camera movement, natural lighting" },
  { label: "Crane descending", value: "Aerial crane shot descending slowly, epic wide angle" },
  { label: "Handheld walk", value: "Handheld camera follows subject walking, slight natural shake" },
  { label: "Zoom out reveal", value: "Slow zoom out reveal, dramatic wide establishing shot" },
  { label: "360° orbit", value: "360 degree orbit around subject, smooth rotation" },
  { label: "Time-lapse sky", value: "Time-lapse clouds moving across sky, golden hour light" },
  { label: "Slow motion", value: "Slow motion capture, 120fps effect, fluid movement" },
  { label: "Tracking shot", value: "Lateral tracking shot following subject, shallow depth of field" },
  { label: "Dutch tilt push", value: "Dutch angle tilt with slow push forward, tension building" },
];

// $0.2419 per second at 720p; 480p is roughly 30% cheaper
const COST_PER_SEC = { "720p": 0.2419, "480p": 0.169 };

const STATUS_COLOR = {
  pending: "#888780", queued: "#378ADD", generating: "#BA7517",
  complete: "#3B6D11", error: "#A32D2D", draft: "#888780", rendering: "#BA7517",
};
const STATUS_BG = {
  pending: "#F1EFE8", queued: "#E6F1FB", generating: "#FAEEDA",
  complete: "#EAF3DE", error: "#FCEBEB", draft: "#F1EFE8", rendering: "#FAEEDA",
};

function Badge({ status, label }) {
  return (
    <span style={{
      fontSize: 11, fontWeight: 500, padding: "2px 8px", borderRadius: 20,
      background: STATUS_BG[status] || "#F1EFE8",
      color: STATUS_COLOR[status] || "#444",
      textTransform: "uppercase", letterSpacing: "0.05em",
    }}>{label || status}</span>
  );
}

function Spinner() {
  return (
    <span style={{
      display: "inline-block", width: 14, height: 14,
      border: "2px solid #D3D1C7", borderTopColor: "#378ADD",
      borderRadius: "50%", animation: "spin 0.7s linear infinite",
    }} />
  );
}

const spinKeyframes = `@keyframes spin { to { transform: rotate(360deg); } }`;

// ─── Filmstrip thumbnail strip ────────────────────────────────────────────────
function FilmStrip({ clips }) {
  if (clips.length === 0) return null;
  return (
    <div style={{
      display: "flex", gap: 6, overflowX: "auto", paddingBottom: 8,
      marginBottom: 16, scrollbarWidth: "thin",
    }}>
      {clips.map((clip, i) => (
        <div key={clip.id} style={{ flexShrink: 0, position: "relative" }}>
          <div style={{
            width: 96, height: 54, borderRadius: 6, overflow: "hidden",
            background: "var(--color-background-secondary)",
            border: `1.5px solid ${clip.status === "complete" ? "#C0DD97" : clip.status === "error" ? "#F09595" : "var(--color-border-tertiary)"}`,
          }}>
            {clip.thumbnail_url ? (
              <img src={clip.thumbnail_url} alt="" style={{ width: "100%", height: "100%", objectFit: "cover" }} />
            ) : clip.image_url && clip.image_url !== "https://example.com/placeholder.jpg" ? (
              <img src={clip.image_url} alt="" style={{ width: "100%", height: "100%", objectFit: "cover", opacity: 0.5 }} />
            ) : (
              <div style={{ width: "100%", height: "100%", display: "flex", alignItems: "center", justifyContent: "center" }}>
                <span style={{ fontSize: 18, color: "var(--color-text-tertiary)" }}>🎞</span>
              </div>
            )}
          </div>
          <div style={{
            position: "absolute", bottom: 3, left: 3,
            background: "rgba(0,0,0,0.55)", borderRadius: 3,
            fontSize: 9, color: "#fff", padding: "1px 4px",
          }}>{i + 1}</div>
          {clip.status === "generating" && (
            <div style={{
              position: "absolute", inset: 0, borderRadius: 6,
              background: "rgba(0,0,0,0.3)", display: "flex",
              alignItems: "center", justifyContent: "center",
            }}><Spinner /></div>
          )}
        </div>
      ))}
    </div>
  );
}

// ─── Cost estimate banner ─────────────────────────────────────────────────────
function CostEstimate({ clips, draft }) {
  const totalSec = clips.reduce((sum, c) => {
    const d = c.duration === "auto" ? 6 : parseInt(c.duration, 10);
    return sum + d;
  }, 0);
  const resolution = draft ? "480p" : (clips[0]?.resolution || "720p");
  const rate = COST_PER_SEC[resolution] || COST_PER_SEC["720p"];
  const cost = (totalSec * rate).toFixed(2);

  return (
    <div style={{
      background: "#FFF8E6", border: "0.5px solid #FAC775", borderRadius: 8,
      padding: "7px 12px", fontSize: 12, color: "#7A4A00", display: "flex",
      alignItems: "center", gap: 8,
    }}>
      <span>💰</span>
      <span>
        Estimated cost: <strong>${cost}</strong> &nbsp;·&nbsp;
        {totalSec}s total &nbsp;·&nbsp;
        {resolution} @ ${rate}/sec
        {draft && <span style={{ color: "#3B6D11", marginLeft: 6 }}>✓ Draft mode saves ~30%</span>}
      </span>
    </div>
  );
}

// ─── ClipCard ─────────────────────────────────────────────────────────────────
function ClipCard({ clip, index, total, onUpdate, onDelete, onMoveUp, onMoveDown, onGenerate, onPoll, onUseAsNext, projectStatus }) {
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
    transition_type: clip.transition_type || "fade",
  });
  const [dirty, setDirty] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [transferring, setTransferring] = useState(false);
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
    await onUpdate(clip.id, { ...form, end_image_url: form.end_image_url || null });
    setDirty(false);
  };

  const handleUseAsNext = async () => {
    setTransferring(true);
    await onUseAsNext(clip.id);
    setTransferring(false);
  };

  const isGenerating = clip.status === "queued" || clip.status === "generating";
  const isLast = index === total - 1;
  const isPassthrough = clip.is_passthrough;

  return (
    <div style={{
      background: "var(--color-background-primary)",
      border: `0.5px solid ${clip.status === "error" ? "#F09595" : isPassthrough ? "#D0AEFF" : "var(--color-border-tertiary)"}`,
      borderRadius: 12, marginBottom: 10, overflow: "hidden", transition: "border-color 0.2s",
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
          fontSize: 12, fontWeight: 500, color: "var(--color-text-secondary)", flexShrink: 0,
        }}>{index + 1}</span>

        {isPassthrough && (
          <span style={{
            fontSize: 10, fontWeight: 600, padding: "2px 7px", borderRadius: 20,
            background: "#F5EDFF", color: "#6B21A8", border: "0.5px solid #D0AEFF",
            textTransform: "uppercase", letterSpacing: "0.05em", flexShrink: 0,
          }}>Original</span>
        )}

        {/* Start frame thumb */}
        {(clip.thumbnail_url || (clip.image_url && clip.image_url !== "https://example.com/placeholder.jpg")) && (
          <div style={{ width: 40, height: 24, borderRadius: 4, overflow: "hidden", flexShrink: 0 }}>
            <img
              src={clip.thumbnail_url || clip.image_url}
              alt=""
              style={{ width: "100%", height: "100%", objectFit: "cover" }}
            />
          </div>
        )}

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
          {isPassthrough && (
            <div style={{ background: "#F5EDFF", border: "0.5px solid #D0AEFF", borderRadius: 6, padding: "8px 12px", fontSize: 12, color: "#6B21A8", marginBottom: 12 }}>
              This is the original uploaded video. It will be included as-is in the stitch — no generation needed.
            </div>
          )}
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10, marginBottom: 10 }}>
            <div>
              <label style={labelStyle}>Clip name</label>
              <input value={form.name} onChange={e => set("name", e.target.value)} placeholder="Scene title..." style={inputStyle} disabled={isPassthrough} />
            </div>
            <div>
              <label style={labelStyle}>Aspect ratio</label>
              <select value={form.aspect_ratio} onChange={e => set("aspect_ratio", e.target.value)} style={inputStyle}>
                {ASPECT_RATIOS.map(r => <option key={r}>{r}</option>)}
              </select>
            </div>
          </div>

          {/* Motion prompt with presets */}
          <div style={{ marginBottom: 10 }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 5 }}>
              <label style={{ ...labelStyle, marginBottom: 0 }}>Motion prompt <span style={{ color: "#A32D2D" }}>*</span></label>
              <select
                defaultValue=""
                onChange={e => { if (e.target.value) { set("prompt", e.target.value); e.target.value = ""; } }}
                style={{ fontSize: 11, padding: "2px 6px", borderRadius: 5, border: "0.5px solid var(--color-border-secondary)", background: "var(--color-background-secondary)", color: "var(--color-text-secondary)", cursor: "pointer" }}
              >
                <option value="">+ Preset</option>
                {PROMPT_PRESETS.map(p => <option key={p.label} value={p.value}>{p.label}</option>)}
              </select>
            </div>
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
              {form.image_url && form.image_url !== "https://example.com/placeholder.jpg" && (
                <img src={form.image_url} alt="" style={{ width: "100%", height: 80, objectFit: "cover", borderRadius: 6, marginTop: 6 }} />
              )}
            </div>
            <div>
              <label style={labelStyle}>End frame image URL <span style={{ color: "var(--color-text-tertiary)" }}>(optional)</span></label>
              <div style={{ display: "flex", gap: 6 }}>
                <input value={form.end_image_url} onChange={e => set("end_image_url", e.target.value)} placeholder="https://..." style={{ ...inputStyle, flex: 1 }} />
                <input ref={endFileRef} type="file" accept="image/jpeg,image/png,image/webp" style={{ display: "none" }}
                  onChange={e => e.target.files[0] && handleUpload(e.target.files[0], "end_image_url")} />
                <button onClick={() => endFileRef.current.click()} style={smallBtnStyle} title="Upload end frame">↑</button>
              </div>
              {form.end_image_url && (
                <img src={form.end_image_url} alt="" style={{ width: "100%", height: 80, objectFit: "cover", borderRadius: 6, marginTop: 6 }} />
              )}
            </div>
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr 1fr", gap: 10, marginBottom: 12 }}>
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
            <div>
              <label style={labelStyle}>Transition in</label>
              <select value={form.transition_type} onChange={e => set("transition_type", e.target.value)} style={inputStyle}>
                {TRANSITION_TYPES.map(t => <option key={t}>{t}</option>)}
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
              <button style={smallBtnStyle} onClick={() => onMoveDown(index)} disabled={isLast} title="Move down">↓</button>
              <button style={{ ...smallBtnStyle, color: "#A32D2D", borderColor: "#F09595" }} onClick={() => onDelete(clip.id)} title="Delete clip">✕</button>
            </div>
            <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
              {dirty && (
                <button onClick={handleSave} style={{ ...smallBtnStyle, background: "#E6F1FB", borderColor: "#B5D4F4", color: "#185FA5" }}>Save changes</button>
              )}
              {clip.status === "complete" && !isLast && (
                <button
                  onClick={handleUseAsNext}
                  disabled={transferring}
                  style={{ ...smallBtnStyle, background: "#F5EDFF", borderColor: "#D0AEFF", color: "#6B21A8" }}
                  title="Extract last frame and use as start of next clip"
                >
                  {transferring ? <Spinner /> : "→ Use as next start"}
                </button>
              )}
              {isPassthrough ? (
                clip.video_url && (
                  <a href={clip.video_url} target="_blank" rel="noreferrer"
                    style={{ ...smallBtnStyle, textDecoration: "none", background: "#F5EDFF", borderColor: "#D0AEFF", color: "#6B21A8" }}>
                    ▶ View original
                  </a>
                )
              ) : isGenerating ? (
                <button onClick={() => onPoll(clip.id)} style={smallBtnStyle}><Spinner /> Poll status</button>
              ) : (
                <button
                  onClick={() => onGenerate(clip.id)}
                  disabled={!form.image_url || form.image_url === "https://example.com/placeholder.jpg" || !form.prompt || projectStatus === "rendering"}
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

// ─── ExtendPanel ──────────────────────────────────────────────────────────────
function ExtendPanel({ project, onClipsAdded, onLog }) {
  const [open, setOpen] = useState(false);
  const [file, setFile] = useState(null);
  const [nScenes, setNScenes] = useState(4);
  const [resolution, setResolution] = useState("720p");
  const [aspectRatio, setAspectRatio] = useState("16:9");
  const [duration, setDuration] = useState("8");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const fileRef = useRef();

  const analyze = async () => {
    if (!file) return;
    setLoading(true);
    setError(null);
    setResult(null);
    onLog("Uploading video and analyzing with Claude Opus…");

    const fd = new FormData();
    fd.append("video", file);
    fd.append("n_scenes", nScenes);
    fd.append("resolution", resolution);
    fd.append("aspect_ratio", aspectRatio);
    fd.append("duration", duration);

    try {
      const r = await fetch(`${API}/projects/${project.id}/extend`, { method: "POST", body: fd });
      if (!r.ok) {
        const d = await r.json();
        throw new Error(d.detail || `Server error ${r.status}`);
      }
      const data = await r.json();
      setResult(data);
      onClipsAdded(data.clips);
      onLog(`✓ Generated ${data.clips.length} scenes (${data.clips.length - 1} new + original)`);
    } catch (e) {
      setError(e.message);
      onLog(`✗ Extend failed: ${e.message}`);
    }
    setLoading(false);
  };

  return (
    <div style={{ marginBottom: 10 }}>
      <button
        onClick={() => { setOpen(o => !o); setResult(null); setError(null); }}
        style={{
          ...smallBtnStyle,
          background: open ? "#F5EDFF" : "var(--color-background-secondary)",
          borderColor: open ? "#D0AEFF" : "var(--color-border-secondary)",
          color: open ? "#6B21A8" : "var(--color-text-secondary)",
          width: "100%", justifyContent: "center", padding: "8px 12px",
        }}
      >
        🎬 Extend from movie short (AI scene generator)
      </button>

      {open && (
        <div style={{
          background: "var(--color-background-secondary)", borderRadius: 10,
          padding: "14px", marginTop: 6,
          border: "0.5px solid #D0AEFF",
        }}>
          <div style={{ fontSize: 12, color: "var(--color-text-secondary)", marginBottom: 10 }}>
            Upload a movie short — Claude Opus analyzes the characters, style, and story,
            then writes a continuation storyboard using the same characters.
            The original video becomes the first clip; generated scenes chain from its last frame.
          </div>

          {/* Video file picker */}
          <div style={{ marginBottom: 10 }}>
            <label style={labelStyle}>Movie short (MP4 / MOV / WebM · max 500 MB)</label>
            <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <input
                ref={fileRef}
                type="file"
                accept="video/mp4,video/quicktime,video/webm,video/x-msvideo,.mp4,.mov,.webm,.avi"
                style={{ display: "none" }}
                onChange={e => { if (e.target.files[0]) setFile(e.target.files[0]); }}
              />
              <button onClick={() => fileRef.current.click()} style={smallBtnStyle}>
                ↑ Choose video
              </button>
              {file && (
                <span style={{ fontSize: 12, color: "var(--color-text-secondary)" }}>
                  {file.name} ({(file.size / 1024 / 1024).toFixed(1)} MB)
                </span>
              )}
            </div>
          </div>

          {/* Scene count + settings */}
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr 1fr", gap: 10, marginBottom: 12 }}>
            <div>
              <label style={labelStyle}>Scenes to generate</label>
              <select value={nScenes} onChange={e => setNScenes(parseInt(e.target.value))} style={inputStyle}>
                {[2, 3, 4, 5, 6, 8].map(n => <option key={n} value={n}>{n} scenes</option>)}
              </select>
            </div>
            <div>
              <label style={labelStyle}>Resolution</label>
              <select value={resolution} onChange={e => setResolution(e.target.value)} style={inputStyle}>
                {RESOLUTIONS.map(r => <option key={r}>{r}</option>)}
              </select>
            </div>
            <div>
              <label style={labelStyle}>Aspect ratio</label>
              <select value={aspectRatio} onChange={e => setAspectRatio(e.target.value)} style={inputStyle}>
                {ASPECT_RATIOS.filter(r => r !== "auto").map(r => <option key={r}>{r}</option>)}
              </select>
            </div>
            <div>
              <label style={labelStyle}>Duration (sec)</label>
              <select value={duration} onChange={e => setDuration(e.target.value)} style={inputStyle}>
                {["4", "5", "6", "7", "8", "9", "10"].map(d => <option key={d}>{d}</option>)}
              </select>
            </div>
          </div>

          <div style={{ marginBottom: 10, fontSize: 12, color: "#6B21A8", background: "#F5EDFF", borderRadius: 6, padding: "7px 10px" }}>
            Tip: After scenes are created, use <strong>Sequential render + Chain clips</strong> — each clip's last frame automatically becomes the next clip's start frame to keep characters consistent.
          </div>

          {error && (
            <div style={{ background: "#FCEBEB", border: "0.5px solid #F09595", borderRadius: 6, padding: "8px 12px", fontSize: 12, color: "#A32D2D", marginBottom: 10 }}>
              {error}
            </div>
          )}

          {result && !error && (
            <div style={{ background: "#EAF3DE", border: "0.5px solid #C0DD97", borderRadius: 6, padding: "10px 12px", marginBottom: 10, fontSize: 12 }}>
              <div style={{ fontWeight: 500, color: "#3B6D11", marginBottom: 6 }}>
                ✓ Storyboard generated — {result.clips.length - 1} new scenes added
              </div>
              {result.story_so_far && (
                <div style={{ color: "#4A6D2B", marginBottom: 4 }}>
                  <strong>Story so far:</strong> {result.story_so_far}
                </div>
              )}
              {result.visual_style && (
                <div style={{ color: "#4A6D2B", marginBottom: 4 }}>
                  <strong>Visual style:</strong> {result.visual_style}
                </div>
              )}
              {result.character_anchors?.length > 0 && (
                <div style={{ color: "#4A6D2B" }}>
                  <strong>Characters:</strong>{" "}
                  {result.character_anchors.map(c => `${c.tag}: ${c.description}`).join(" · ")}
                </div>
              )}
            </div>
          )}

          <button
            onClick={analyze}
            disabled={!file || loading}
            style={{
              ...smallBtnStyle,
              background: loading ? "#F5EDFF" : "#7C3AED",
              borderColor: "#6D28D9",
              color: "#fff",
              padding: "8px 16px",
              opacity: (!file || loading) ? 0.6 : 1,
            }}
          >
            {loading ? <><Spinner /> Analyzing with Claude Opus…</> : "✦ Analyze & generate scenes"}
          </button>
        </div>
      )}
    </div>
  );
}

// ─── ProjectView ──────────────────────────────────────────────────────────────
function ProjectView({ project, onBack }) {
  const [clips, setClips] = useState(project.clips || []);
  const [proj, setProj] = useState(project);
  const [rendering, setRendering] = useState(false);
  const [addingClip, setAddingClip] = useState(false);
  const [logs, setLogs] = useState([]);
  const [crossfadeDuration, setCrossfadeDuration] = useState(0.5);
  const [draftMode, setDraftMode] = useState(false);
  const [showCostEstimate, setShowCostEstimate] = useState(false);
  const [autoChain, setAutoChain] = useState(true);
  const sseRef = useRef(null);
  const sseRetryDelayRef = useRef(1000);
  const sseRetryTimerRef = useRef(null);
  const renderingRef = useRef(false);

  const log = msg => setLogs(l => [`${new Date().toLocaleTimeString()} ${msg}`, ...l.slice(0, 29)]);

  const loadProject = useCallback(async () => {
    const r = await fetch(`${API}/projects/${proj.id}`);
    const data = await r.json();
    setProj(data);
    setClips(data.clips || []);
  }, [proj.id]);

  // SSE connection for real-time updates during rendering
  const connectSSE = useCallback(() => {
    if (sseRef.current) sseRef.current.close();
    if (sseRetryTimerRef.current) clearTimeout(sseRetryTimerRef.current);

    const es = new EventSource(`${API}/projects/${proj.id}/render/stream`);
    sseRef.current = es;

    const onTerminal = async () => {
      renderingRef.current = false;
      es.close();
      sseRef.current = null;
      await loadProject();
      setRendering(false);
    };

    es.onmessage = async (e) => {
      sseRetryDelayRef.current = 1000; // reset backoff on any successful message
      const event = JSON.parse(e.data);
      if (event.type === "clip_complete") {
        log(`✓ Clip ${event.clip_id} complete`);
        await loadProject();
      } else if (event.type === "clip_error") {
        log(`✗ Clip ${event.clip_id} error: ${event.message}`);
        await loadProject();
      } else if (event.type === "clip_start") {
        log(`⟳ Clip ${event.clip_id} generating (attempt ${event.attempt})...`);
        await loadProject();
      } else if (event.type === "clip_queued") {
        log(`↑ Clip ${event.clip_id} queued`);
        await loadProject();
      } else if (event.type === "chain_complete") {
        log(`⛓ Clip ${event.from_clip} → ${event.to_clip} chained`);
      } else if (event.type === "stitch_start") {
        log("✂ Stitching clips...");
      } else if (event.type === "stitch_complete") {
        log("🎬 Stitch complete!");
        await onTerminal();
      } else if (event.type === "done") {
        if (event.error) log(`Error: ${event.error}`);
        await onTerminal();
      }
    };

    es.onerror = () => {
      es.close();
      sseRef.current = null;
      if (renderingRef.current) {
        // Reconnect with exponential backoff (max 30s)
        sseRetryTimerRef.current = setTimeout(() => {
          sseRetryDelayRef.current = Math.min(sseRetryDelayRef.current * 2, 30000);
          connectSSE();
        }, sseRetryDelayRef.current);
      } else {
        setRendering(false);
      }
    };
  }, [proj.id, loadProject]);

  useEffect(() => {
    loadProject();
    return () => {
      sseRef.current?.close();
      if (sseRetryTimerRef.current) clearTimeout(sseRetryTimerRef.current);
    };
  }, []);

  const addClip = async () => {
    setAddingClip(true);
    const r = await fetch(`${API}/projects/${proj.id}/clips`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        prompt: "", image_url: "https://example.com/placeholder.jpg",
        name: `Scene ${clips.length + 1}`, order: clips.length,
      }),
    });
    const clip = await r.json();
    setClips(c => [...c, clip]);
    log(`Added: Scene ${clips.length + 1}`);
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
    setClips(await r.json());
  };

  const generateClip = async (clipId) => {
    const r = await fetch(`${API}/projects/${proj.id}/clips/${clipId}/generate`, { method: "POST" });
    const updated = await r.json();
    setClips(c => c.map(x => x.id === clipId ? updated : x));
    log(`Submitted clip ${clipId}`);
  };

  const pollClip = async (clipId) => {
    const r = await fetch(`${API}/projects/${proj.id}/clips/${clipId}/poll`);
    const updated = await r.json();
    setClips(c => c.map(x => x.id === clipId ? updated : x));
    log(`Polled clip ${clipId}: ${updated.status}`);
  };

  const useAsNext = async (clipId) => {
    const r = await fetch(`${API}/projects/${proj.id}/clips/${clipId}/use-as-next`, { method: "POST" });
    if (!r.ok) { const d = await r.json(); alert(d.detail); return; }
    const updated = await r.json();
    setClips(c => c.map(x => x.id === updated.id ? updated : x));
    log(`Extracted last frame of clip ${clipId} → next clip start`);
  };

  const startRender = async (parallel = false) => {
    sseRetryDelayRef.current = 1000;
    renderingRef.current = true;
    setRendering(true);
    connectSSE();
    const r = await fetch(`${API}/projects/${proj.id}/render`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        parallel, stitch: true, draft: draftMode,
        crossfade: true, crossfade_duration: crossfadeDuration,
        auto_chain: !parallel && autoChain,
      }),
    });
    const data = await r.json();
    log(`Render started: ${data.message}`);
    await loadProject();
  };

  const stitch = async () => {
    await fetch(`${API}/projects/${proj.id}/render/stitch?crossfade=true&crossfade_duration=${crossfadeDuration}`, { method: "POST" });
    log("Stitching triggered...");
    await loadProject();
  };

  const completeClips = clips.filter(c => c.status === "complete");
  const allComplete = clips.length > 0 && clips.every(c => c.status === "complete");
  const validClips = clips.filter(c => !c.is_passthrough && c.image_url && c.image_url !== "https://example.com/placeholder.jpg" && c.prompt);

  return (
    <div style={{ maxWidth: 860, margin: "0 auto", padding: "0 0 40px" }}>
      <style>{spinKeyframes}</style>

      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 20 }}>
        <button onClick={onBack} style={{ ...smallBtnStyle, fontSize: 13 }}>← Projects</button>
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 18, fontWeight: 500, color: "var(--color-text-primary)" }}>{proj.name}</div>
          {proj.description && <div style={{ fontSize: 13, color: "var(--color-text-secondary)", marginTop: 2 }}>{proj.description}</div>}
        </div>
        <Badge status={proj.status} />
        {proj.status === "rendering" && <Spinner />}
      </div>

      {/* Extend from video panel */}
      <ExtendPanel
        project={proj}
        onClipsAdded={newClips => setClips(c => [...c, ...newClips])}
        onLog={log}
      />

      {/* Filmstrip */}
      <FilmStrip clips={clips} />

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
      <div style={{ background: "var(--color-background-secondary)", borderRadius: 10, padding: "12px 14px", marginBottom: 10 }}>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center", marginBottom: 10 }}>
          <span style={{ fontSize: 13, color: "var(--color-text-secondary)", marginRight: 4 }}>Render:</span>

          <button
            onClick={() => startRender(false)}
            disabled={rendering || clips.length === 0 || proj.status === "rendering"}
            style={{ ...smallBtnStyle, background: "#E6F1FB", borderColor: "#B5D4F4", color: "#185FA5" }}
          >▶ Sequential</button>

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

        {/* Render options row */}
        <div style={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
          <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, color: "var(--color-text-secondary)", cursor: "pointer" }}>
            <input type="checkbox" checked={draftMode} onChange={e => setDraftMode(e.target.checked)} />
            <span style={{ color: draftMode ? "#3B6D11" : "inherit" }}>Draft mode (480p, ~30% cheaper)</span>
          </label>

          <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, color: "var(--color-text-secondary)", cursor: "pointer" }} title="Sequential only: extract last frame of each clip and use it as the start of the next clip to maintain character continuity">
            <input type="checkbox" checked={autoChain} onChange={e => setAutoChain(e.target.checked)} />
            <span style={{ color: autoChain ? "#6B21A8" : "inherit" }}>Chain clips (keep characters consistent)</span>
          </label>

          <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, color: "var(--color-text-secondary)" }}>
            Crossfade:
            <select
              value={crossfadeDuration}
              onChange={e => setCrossfadeDuration(parseFloat(e.target.value))}
              style={{ ...inputStyle, padding: "3px 6px", width: "auto", fontSize: 12 }}
            >
              <option value={0}>None (hard cut)</option>
              <option value={0.3}>0.3s (quick)</option>
              <option value={0.5}>0.5s (default)</option>
              <option value={1.0}>1.0s (smooth)</option>
              <option value={1.5}>1.5s (dreamy)</option>
            </select>
          </label>

          <button
            onClick={() => setShowCostEstimate(s => !s)}
            style={{ ...smallBtnStyle, fontSize: 11 }}
          >💰 {showCostEstimate ? "Hide" : "Estimate cost"}</button>
        </div>

        {showCostEstimate && validClips.length > 0 && (
          <div style={{ marginTop: 10 }}>
            <CostEstimate clips={validClips} draft={draftMode} />
          </div>
        )}
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
            onUseAsNext={useAsNext}
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

      {/* Activity log */}
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

// ─── ProjectList ──────────────────────────────────────────────────────────────
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
    setNewName(""); setNewDesc(""); setCreating(false);
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
              borderRadius: 12, padding: "12px 16px", marginBottom: 8,
              cursor: "pointer", display: "flex", alignItems: "center", gap: 12,
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

// ─── Shared styles ────────────────────────────────────────────────────────────
const labelStyle = {
  display: "block", fontSize: 11, fontWeight: 500,
  color: "var(--color-text-secondary)", textTransform: "uppercase",
  letterSpacing: "0.06em", marginBottom: 5,
};

const inputStyle = {
  width: "100%", boxSizing: "border-box", padding: "7px 10px",
  fontSize: 13, borderRadius: 7, border: "0.5px solid var(--color-border-secondary)",
  background: "var(--color-background-primary)", color: "var(--color-text-primary)",
  fontFamily: "var(--font-sans)",
};

const smallBtnStyle = {
  padding: "5px 12px", fontSize: 12, fontWeight: 500, borderRadius: 7,
  border: "0.5px solid var(--color-border-secondary)",
  background: "var(--color-background-primary)", color: "var(--color-text-primary)",
  cursor: "pointer", display: "inline-flex", alignItems: "center", gap: 5, whiteSpace: "nowrap",
};

export default function App() {
  const [selected, setSelected] = useState(null);
  if (selected) return <ProjectView project={selected} onBack={() => setSelected(null)} />;
  return <ProjectList onSelect={setSelected} />;
}
