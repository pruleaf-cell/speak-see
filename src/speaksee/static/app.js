(function () {
  const micBtn = document.getElementById("micBtn");
  const micLabel = document.getElementById("micLabel");
  const autoListenEl = document.getElementById("autoListen");
  const genBtn = document.getElementById("genBtn");
  const regenBtn = document.getElementById("regenBtn");
  const saveBtn = document.getElementById("saveBtn");
  const statusText = document.getElementById("statusText");
  const modelText = document.getElementById("modelText");
  const phasePill = document.getElementById("phasePill");

  const liveText = document.getElementById("liveText");
  const promptBox = document.getElementById("promptBox");
  const countdownEl = document.getElementById("countdown");

  const mainImage = document.getElementById("mainImage");
  const skeleton = document.getElementById("skeleton");
  const progressWrap = document.getElementById("progressWrap");
  const progressFill = document.getElementById("progressFill");
  const progressText = document.getElementById("progressText");

  const galleryList = document.getElementById("galleryList");
  const toast = document.getElementById("toast");
  const overlay = document.getElementById("overlay");
  const overlayBtn = document.getElementById("overlayBtn");

  const wsUrl = (location.protocol === "https:" ? "wss://" : "ws://") + location.host + "/ws";
  let ws = null;
  let mic = null;

  let phase = "idle";
  let recording = false;
  let lastNonSilentAt = 0;
  let silenceTimer = null;
  let startInFlight = false;
  let stopInFlight = false;

  // VAD state (auto listen)
  let vadAbove = 0;
  let lastVadStopAt = 0;

  let autogenTimer = null;
  let autogenStartAt = 0;
  const AUTOGEN_DELAY_MS = 1200;

  // UI helpers
  function setPhase(next, detail) {
    phase = next;
    phasePill.textContent = next;
    phasePill.className = "pill " + next;
    statusText.textContent = detail || "";
  }

  function showToast(msg, ms = 1400) {
    toast.textContent = msg;
    toast.classList.add("on");
    setTimeout(() => toast.classList.remove("on"), ms);
  }

  function updateMicLabel() {
    if (recording) {
      micLabel.textContent = "Listening";
      return;
    }
    const auto = !!(autoListenEl && autoListenEl.checked);
    micLabel.textContent = auto ? "Auto" : "Talk";
  }

  function setRecordingUI(on) {
    recording = on;
    micBtn.classList.toggle("recording", on);
    updateMicLabel();
  }

  function setLoading(on) {
    skeleton.classList.toggle("on", on);
    if (on) {
      mainImage.classList.remove("ready");
      progressWrap.classList.add("on");
      progressFill.style.width = "0%";
      progressText.textContent = "";
    } else {
      progressWrap.classList.remove("on");
    }
  }

  function renderGallery(items) {
    galleryList.innerHTML = "";
    for (const it of items || []) {
      const row = document.createElement("div");
      row.className = "thumb";
      const img = document.createElement("img");
      img.src = it.url;
      img.alt = it.id;
      const meta = document.createElement("div");
      meta.className = "meta";
      const ts = document.createElement("div");
      ts.className = "ts";
      ts.textContent = it.ts || "";
      const id = document.createElement("div");
      id.className = "id";
      id.textContent = it.id;
      meta.appendChild(ts);
      meta.appendChild(id);
      row.appendChild(img);
      row.appendChild(meta);
      row.addEventListener("click", () => {
        mainImage.src = it.url;
        mainImage.onload = () => mainImage.classList.add("ready");
      });
      galleryList.appendChild(row);
    }
  }

  function normalizeText(s) {
    return (s || "")
      .trim()
      .toLowerCase()
      .replace(/[^a-z0-9\\s]/g, " ")
      .replace(/\\s+/g, " ")
      .trim();
  }

  function isVoiceCommand(text) {
    const n = normalizeText(text).replace(/^(please|hey|ok|okay)\\s+/, "").replace(/\\s+(please|thanks|thank you)$/, "");
    return (
      n === "regenerate" ||
      n === "more realistic" ||
      n === "more abstract" ||
      n === "save image" ||
      n === "save the image"
    );
  }

  function cancelAutogen() {
    if (autogenTimer) clearInterval(autogenTimer);
    autogenTimer = null;
    countdownEl.textContent = "";
  }

  function scheduleAutogen(text) {
    cancelAutogen();
    if (!text || !text.trim()) return;
    if (isVoiceCommand(text)) return;

    autogenStartAt = Date.now();
    autogenTimer = setInterval(() => {
      const elapsed = Date.now() - autogenStartAt;
      const remain = Math.max(0, AUTOGEN_DELAY_MS - elapsed);
      if (remain <= 0) {
        cancelAutogen();
        sendGenerate(promptBox.value);
        return;
      }
      countdownEl.textContent = "Auto-generate in " + (remain / 1000).toFixed(1) + "s (type to cancel)";
    }, 60);
  }

  promptBox.addEventListener("input", () => {
    // Cancel autogen as soon as the user edits.
    cancelAutogen();
  });

  // WebSocket
  function connectWs() {
    ws = new WebSocket(wsUrl);
    ws.binaryType = "arraybuffer";

    ws.onopen = async () => {
      setPhase("idle", "");
      ws.send(JSON.stringify({ type: "hello", ui_version: "1", client: "web" }));

      if (!mic) mic = new window.SpeakSeeMic.MicStreamer();
      mic.attachWebSocket(ws);
      mic.onRms = onRms;

      // Hands-free: request mic access on load (only mic prompt).
      await ensureMicEnabled();
      updateMicLabel();
    };

    ws.onmessage = (ev) => {
      if (typeof ev.data !== "string") return;
      let msg = null;
      try { msg = JSON.parse(ev.data); } catch (_) { return; }

      if (msg.type === "status") {
        setPhase(msg.phase, msg.detail);
        if (msg.phase === "ready" || msg.phase === "idle") {
          setLoading(false);
        }
        return;
      }
      if (msg.type === "models") {
        modelText.textContent = `STT: ${msg.stt_model} · SD: ${msg.image_model} · device: ${msg.device}`;
        return;
      }
      if (msg.type === "transcript_partial") {
        liveText.textContent = msg.text || "…";
        return;
      }
      if (msg.type === "transcript_final") {
        const t = msg.text || "";
        liveText.textContent = t || "…";
        promptBox.value = t;
        scheduleAutogen(t);
        return;
      }
      if (msg.type === "gen_started") {
        setLoading(true);
        progressText.textContent = "Starting…";
        return;
      }
      if (msg.type === "gen_progress") {
        const pct = msg.percent || 0;
        progressFill.style.width = pct + "%";
        progressText.textContent = `Step ${msg.step}/${msg.total_steps}`;
        return;
      }
      if (msg.type === "gen_result") {
        mainImage.src = msg.url;
        mainImage.onload = () => {
          mainImage.classList.add("ready");
          setLoading(false);
        };
        showToast("Generated");
        return;
      }
      if (msg.type === "gallery") {
        renderGallery(msg.items || []);
        return;
      }
      if (msg.type === "saved") {
        showToast("Saved image");
        return;
      }
      if (msg.type === "error") {
        showToast(msg.message || "Error");
        setPhase("ready", "");
        setLoading(false);
        return;
      }
    };

    ws.onclose = () => {
      setPhase("idle", "Disconnected. Reconnecting…");
      setRecordingUI(false);
      cancelAutogen();
      try { if (mic) mic.stopStreaming(); } catch (_) {}
      setTimeout(connectWs, 600);
    };
  }

  async function ensureMicEnabled() {
    if (!mic) return;
    try {
      if (overlay) overlay.hidden = true;
      await mic.enable();
      if (overlay) overlay.hidden = true;
    } catch (e) {
      if (overlay) overlay.hidden = false;
    }
  }

  if (overlayBtn) {
    overlayBtn.addEventListener("click", async () => {
      await ensureMicEnabled();
      if (overlay && overlay.hidden) showToast("Microphone enabled");
    });
  }

  if (autoListenEl) {
    autoListenEl.addEventListener("change", async () => {
      updateMicLabel();
      vadAbove = 0;
      if (autoListenEl.checked) {
        await ensureMicEnabled();
        showToast("Auto listen on");
      } else {
        stopRecording();
        showToast("Auto listen off");
      }
    });
  }

  // Mic control + silence detection + auto-start (VAD)
  function onRms(rms) {
    const now = Date.now();

    // Auto listen: start streaming when speech is detected.
    const auto = !!(autoListenEl && autoListenEl.checked);
    const canAutoStart =
      auto &&
      !recording &&
      !startInFlight &&
      (phase === "idle" || phase === "ready") &&
      document.activeElement !== promptBox &&
      !autogenTimer;

    const START_THRESH = 0.015; // tweakable
    const START_FRAMES = 2;
    const COOLDOWN_MS = 350;

    if (canAutoStart) {
      if (rms > START_THRESH) vadAbove += 1;
      else vadAbove = Math.max(0, vadAbove - 1);

      if (vadAbove >= START_FRAMES && now - lastVadStopAt > COOLDOWN_MS) {
        vadAbove = 0;
        startRecording();
      }
    } else if (!recording) {
      vadAbove = 0;
    }

    // Silence detection while streaming (auto-stop after speech ends).
    if (!recording) return;
    const THRESH = 0.013; // stop threshold (slightly lower for hysteresis)
    if (rms > THRESH) lastNonSilentAt = now;
    if (!lastNonSilentAt) lastNonSilentAt = now;

    const SILENCE_MS = 1200;
    if (now - lastNonSilentAt > SILENCE_MS) {
      stopRecording();
    }
  }

  async function startRecording() {
    if (!mic || recording || startInFlight) return;
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    startInFlight = true;
    cancelAutogen();
    liveText.textContent = "…";
    lastNonSilentAt = Date.now();
    setRecordingUI(true);
    try {
      await ensureMicEnabled();
      await mic.startStreaming();
    } catch (e) {
      setRecordingUI(false);
      showToast("Mic error");
    } finally {
      startInFlight = false;
    }
  }

  async function stopRecording() {
    if (!mic || !recording || stopInFlight) return;
    stopInFlight = true;
    setRecordingUI(false);
    lastVadStopAt = Date.now();
    try { await mic.stopStreaming(); } catch (_) {}
    finally { stopInFlight = false; }
  }

  function toggleRecording() {
    if (recording) stopRecording();
    else startRecording();
  }

  // Button supports click-to-toggle; hold-to-talk starts after 200ms hold.
  let holdTimer = null;
  let holdActive = false;
  let suppressNextClick = false;
  micBtn.addEventListener("click", (e) => {
    if (suppressNextClick) {
      suppressNextClick = false;
      return;
    }
    toggleRecording();
  });
  micBtn.addEventListener("pointerdown", (e) => {
    holdActive = false;
    suppressNextClick = false;
    if (holdTimer) clearTimeout(holdTimer);
    holdTimer = setTimeout(() => {
      holdActive = true;
      if (!recording) startRecording();
    }, 200);
  });
  micBtn.addEventListener("pointerup", (e) => {
    if (holdTimer) clearTimeout(holdTimer);
    holdTimer = null;
    if (holdActive) {
      holdActive = false;
      suppressNextClick = true;
      stopRecording();
    }
  });
  micBtn.addEventListener("pointercancel", () => {
    if (holdTimer) clearTimeout(holdTimer);
    holdTimer = null;
    if (holdActive) {
      holdActive = false;
      suppressNextClick = true;
      stopRecording();
    }
  });

  // Actions
  function sendGenerate(text) {
    const prompt = (text || "").trim();
    if (!prompt) return;
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    ws.send(JSON.stringify({ type: "generate", prompt }));
  }
  function sendAction(name, value) {
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    const msg = { type: "action", name };
    if (value !== undefined) msg.value = value;
    ws.send(JSON.stringify(msg));
  }

  genBtn.addEventListener("click", () => sendGenerate(promptBox.value));
  regenBtn.addEventListener("click", () => sendAction("regenerate"));
  saveBtn.addEventListener("click", () => sendAction("save_image"));

  // Keyboard shortcuts
  let spaceDownAt = 0;
  let ignoreNextSpaceUp = false;
  const SPACE_HOLD_MS = 200;

  window.addEventListener("keydown", (e) => {
    const ae = document.activeElement;
    const inText =
      ae &&
      (ae.tagName === "TEXTAREA" ||
        ae.tagName === "INPUT" ||
        ae.isContentEditable);

    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      sendGenerate(promptBox.value);
      return;
    }
    if (e.key === "Enter" && document.activeElement === promptBox) {
      // Enter generates; Shift+Enter inserts newline.
      if (!e.shiftKey) {
        e.preventDefault();
        sendGenerate(promptBox.value);
      }
      return;
    }

    if (e.key === "Escape") {
      cancelAutogen();
      stopRecording();
      return;
    }

    // Don't steal typing keys while editing the prompt.
    if (inText) return;

    if (e.key === " " || e.code === "Space") {
      e.preventDefault();
      if (!recording) {
        startRecording();
        spaceDownAt = Date.now();
        ignoreNextSpaceUp = false;
      } else {
        stopRecording();
        ignoreNextSpaceUp = true;
      }
      return;
    }
    if (e.key === "r" || e.key === "R") {
      sendAction("regenerate");
      return;
    }
    if (e.key === "s" || e.key === "S") {
      sendAction("save_image");
      return;
    }
  });

  window.addEventListener("keyup", (e) => {
    if (e.key === " " || e.code === "Space") {
      e.preventDefault();
      if (ignoreNextSpaceUp) {
        ignoreNextSpaceUp = false;
        return;
      }
      if (recording && spaceDownAt) {
        const dur = Date.now() - spaceDownAt;
        if (dur >= SPACE_HOLD_MS) stopRecording();
      }
      spaceDownAt = 0;
    }
  });

  // Init
  connectWs();
  setLoading(false);
})();
