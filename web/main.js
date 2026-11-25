(() => {
  const STATE = {
    sessionId: null,
    view: null,
    inspector: null,
    mode: "SPEAK_PRIVATE",
    userToken: "",
    busy: false,
    visualMode: "loop", // loop | transit | warning | dim | normal | bright
  };

  // ── 1. Underwater Tunnel Canvas Renderer ──
  const canvas = document.getElementById("tunnel-canvas");
  const ctx = canvas.getContext("2d");
  let width = 0;
  let height = 0;
  let offset = 0;
  let raindrops = [];
  let lights = [];

  function initCanvas() {
    width = canvas.width = window.innerWidth;
    height = canvas.height = window.innerHeight;
    raindrops = Array.from({ length: 75 }, () => ({
      x: Math.random() * width,
      y: Math.random() * height,
      len: 14 + Math.random() * 28,
      speed: 2.2 + Math.random() * 4.5,
      alpha: 0.12 + Math.random() * 0.25,
    }));
    lights = Array.from({ length: 10 }, (_, idx) => ({
      x: (idx / 10) * (width + 320),
      amber: idx % 2 === 1,
    }));
  }

  function drawTunnel(ts) {
    const mode = STATE.visualMode;
    const speed = mode === "transit" ? 26 : mode === "warning" ? 11 : mode === "loop" ? 5.5 : 0.4;
    offset += speed;

    // Background sky / underwater gradient
    const grad = ctx.createLinearGradient(0, 0, 0, height);
    if (mode === "bright") {
      grad.addColorStop(0, "#5e7f98");
      grad.addColorStop(0.45, "#a68b67");
      grad.addColorStop(1, "#1e293b");
    } else if (mode === "dim") {
      grad.addColorStop(0, "#07090d");
      grad.addColorStop(0.6, "#11151d");
      grad.addColorStop(1, "#05070a");
    } else if (mode === "normal") {
      grad.addColorStop(0, "#0c192b");
      grad.addColorStop(0.6, "#16263a");
      grad.addColorStop(1, "#09111d");
    } else if (mode === "warning") {
      grad.addColorStop(0, "#1d070c");
      grad.addColorStop(0.55, "#0d111e");
      grad.addColorStop(1, "#050912");
    } else {
      grad.addColorStop(0, "#041224");
      grad.addColorStop(0.5, "#082038");
      grad.addColorStop(1, "#030a14");
    }
    ctx.fillStyle = grad;
    ctx.fillRect(0, 0, width, height);

    // Underwater subtle wave caustics during loop / bright
    if (mode === "loop" || mode === "transit" || mode === "bright") {
      ctx.save();
      ctx.globalAlpha = mode === "bright" ? 0.18 : 0.08;
      ctx.strokeStyle = mode === "bright" ? "#fde68a" : "#38bdf8";
      ctx.lineWidth = 2;
      for (let i = 0; i < 4; i++) {
        ctx.beginPath();
        const baseY = height * (0.18 + i * 0.14);
        for (let x = 0; x <= width; x += 48) {
          const y = baseY + Math.sin(x * 0.008 + ts * 0.0014 + i) * 14;
          if (x === 0) ctx.moveTo(x, y);
          else ctx.lineTo(x, y);
        }
        ctx.stroke();
      }
      ctx.restore();
    }

    // Alternating tunnel light boards rushing past
    if (mode === "loop" || mode === "transit" || mode === "warning") {
      const span = width + 320;
      for (const bar of lights) {
        bar.x -= speed;
        if (bar.x < -160) bar.x += span;
        const barW = mode === "transit" ? 90 : 34;
        const color =
          mode === "warning"
            ? "rgba(239, 68, 68, 0.34)"
            : bar.amber
            ? "rgba(245, 158, 11, 0.22)"
            : "rgba(56, 189, 248, 0.24)";
        const lg = ctx.createLinearGradient(bar.x, 0, bar.x + barW, 0);
        lg.addColorStop(0, "transparent");
        lg.addColorStop(0.5, color);
        lg.addColorStop(1, "transparent");
        ctx.fillStyle = lg;
        ctx.fillRect(bar.x, 0, barW, height * 0.65);
      }
    }

    // Normal ending: subtle police red/blue reflections on wet glass
    if (mode === "normal") {
      const pulse = (Math.sin(ts * 0.006) + 1) * 0.5;
      ctx.fillStyle = `rgba(239, 68, 68, ${0.07 * pulse})`;
      ctx.fillRect(0, 0, width * 0.45, height);
      ctx.fillStyle = `rgba(59, 130, 246, ${0.08 * (1 - pulse)})`;
      ctx.fillRect(width * 0.55, 0, width * 0.45, height);
    }

    // Dim ending: flickering cold platform tube
    if (mode === "dim" && Math.sin(ts * 0.03) > 0.72) {
      ctx.fillStyle = "rgba(180, 195, 215, 0.06)";
      ctx.fillRect(0, 0, width, height * 0.35);
    }

    // Bright ending: radiant warm dawn rays
    if (mode === "bright") {
      const rg = ctx.createRadialGradient(width * 0.5, height * 0.12, 20, width * 0.5, height * 0.12, width * 0.7);
      rg.addColorStop(0, "rgba(255, 248, 220, 0.45)");
      rg.addColorStop(0.5, "rgba(251, 191, 36, 0.14)");
      rg.addColorStop(1, "transparent");
      ctx.fillStyle = rg;
      ctx.fillRect(0, 0, width, height);
    }

    // Rain streaks on glass (stop raining in bright true ending!)
    if (mode !== "bright") {
      ctx.strokeStyle = "rgba(186, 230, 253, 0.24)";
      ctx.lineWidth = 1.1;
      for (const drop of raindrops) {
        drop.y += drop.speed;
        drop.x -= mode === "transit" ? 4.5 : 0.8;
        if (drop.y > height) {
          drop.y = -drop.len;
          drop.x = Math.random() * width;
        }
        if (drop.x < 0) drop.x = width;
        ctx.globalAlpha = drop.alpha;
        ctx.beginPath();
        ctx.moveTo(drop.x, drop.y);
        ctx.lineTo(drop.x - (mode === "transit" ? 9 : 2), drop.y + drop.len);
        ctx.stroke();
      }
      ctx.globalAlpha = 1;
    }

    requestAnimationFrame(drawTunnel);
  }

  window.addEventListener("resize", initCanvas);
  initCanvas();
  requestAnimationFrame(drawTunnel);

  function setVisualMode(mode) {
    STATE.visualMode = mode;
    document.body.setAttribute("data-visual", mode);
  }

  // ── 2. API Helpers ──
  async function apiFetch(path, options = {}) {
    const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
    if (STATE.userToken) {
      headers["X-User-Token"] = STATE.userToken;
    }
    const res = await fetch(path, { ...options, headers });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      throw new Error(data.detail || `请求失败 (${res.status})`);
    }
    return data;
  }

  // ── 3. UI Rendering ──
  const elClock = document.getElementById("led-clock");
  const elLoop = document.getElementById("loop-count");
  const elTurn = document.getElementById("turn-indicator");
  const elSkipBtn = document.getElementById("btn-skip-t2");
  const elTransit = document.getElementById("transit-badge");
  const elZones = document.getElementById("zones-grid");
  const elNpcList = document.getElementById("npc-list");
  const elEventFeed = document.getElementById("event-feed");
  const elCurrentZone = document.getElementById("current-zone-pill");
  const elPlayerItems = document.getElementById("player-items-badge");
  const elSelectTarget = document.getElementById("select-target");
  const elSelectClue = document.getElementById("select-clue");
  const elSelectMove = document.getElementById("select-move");
  const elHintsBar = document.getElementById("hints-bar");
  const elSpeechInput = document.getElementById("speech-input");
  const elSubmitBtn = document.getElementById("btn-submit-turn");
  const elInputError = document.getElementById("input-error");
  const elClueList = document.getElementById("clue-list");
  const elClueCount = document.getElementById("clue-count");
  const elPuzzleSlots = document.getElementById("puzzle-slots");
  const elPuzzleBadge = document.getElementById("puzzle-status-badge");
  const elPuzzleHint = document.getElementById("puzzle-hint");
  const elNotebook = document.getElementById("notebook-list");

  function appendEvents(events) {
    if (!events || !events.length) return;
    for (const ev of events) {
      const div = document.createElement("div");
      div.className = `event-item kind-${ev.kind || "info"} actor-${ev.actor || "sys"}`;
      div.textContent = ev.text || "";
      elEventFeed.appendChild(div);
    }
    elEventFeed.scrollTop = elEventFeed.scrollHeight;
  }

  function renderZones(view) {
    const moveChoice = elSelectMove.value;
    elZones.innerHTML = "";
    for (const z of view.zones) {
      const box = document.createElement("div");
      const isPlayer = view.player.zone === z.id;
      const isMove = moveChoice === z.id;
      box.className = `zone-box ${isPlayer ? "is-player" : ""} ${isMove ? "is-move-target" : ""}`;
      box.onclick = () => {
        elSelectMove.value = z.id === view.player.zone ? "" : z.id;
        renderZones(view);
        refreshTargetOptions();
      };

      const occupants = [];
      if (isPlayer) {
        occupants.push(`<span class="occ-chip is-me">你（乘客）</span>`);
      }
      for (const npc of view.npcs) {
        if (npc.zone === z.id) {
          const stClass =
            npc.status === "DETAINED"
              ? "status-detained"
              : npc.status === "TRACKING_ZHOU"
              ? "status-track"
              : "";
          const stSuffix =
            npc.status === "DETAINED"
              ? " · 已控制"
              : npc.status === "TRACKING_ZHOU"
              ? " · 追踪中"
              : "";
          occupants.push(`<span class="occ-chip ${stClass}">${npc.name}${stSuffix}</span>`);
        }
      }

      box.innerHTML = `
        <div class="zone-top">
          <span class="zone-name">${z.name}</span>
          <span class="zone-tag">${isMove ? "本回合移往此处" : z.id}</span>
        </div>
        <div class="zone-occupants">${occupants.join("") || '<span class="zone-tag">空无一人</span>'}</div>
      `;
      elZones.appendChild(box);
    }
  }

  function statLabel(key) {
    return { guard: "防备", guilt: "愧疚", panic: "恐慌", resolve: "把握值" }[key] || key;
  }

  function zoneName(view, zid) {
    const z = view.zones.find((item) => item.id === zid);
    return z ? z.name : zid;
  }

  function renderNpcs(view) {
    elNpcList.innerHTML = "";
    for (const npc of view.npcs) {
      const card = document.createElement("div");
      const sameZone = npc.zone === view.player.zone;
      card.className = `npc-card ${sameZone ? "same-zone" : ""}`;
      card.onclick = () => {
        if (npc.zone !== view.player.zone) {
          elSelectMove.value = npc.zone;
          renderZones(view);
          refreshTargetOptions();
        }
        elSelectTarget.value = npc.id;
      };

      const bars = Object.entries(npc.stats)
        .map(([k, val]) => {
          const mark = k === "resolve" ? '<div class="stat-threshold" title="过线 70 亮证"></div>' : "";
          return `
            <div class="stat-row">
              <span>${statLabel(k)}</span>
              <div class="stat-bar">
                <div class="stat-fill ${k}" style="width:${Math.min(100, Math.max(0, val))}%"></div>
                ${mark}
              </div>
              <span>${val}</span>
            </div>
          `;
        })
        .join("");

      card.innerHTML = `
        <div class="npc-head">
          <div><span class="npc-name">${npc.name}</span><span class="npc-role">${npc.role}</span></div>
          <span class="mood-badge">${npc.mood}</span>
        </div>
        <div class="npc-meta">
          <span>位置：${zoneName(view, npc.zone)}${sameZone ? "（同区）" : ""}</span>
          <span>${npc.status || ""}</span>
        </div>
        ${bars}
      `;
      elNpcList.appendChild(card);
    }
  }

  function refreshTargetOptions() {
    if (!STATE.view) return;
    const view = STATE.view;
    const effectiveZone = elSelectMove.value || view.player.zone;
    const prev = elSelectTarget.value;
    const candidates = view.npcs.filter((n) => n.zone === effectiveZone);
    elSelectTarget.innerHTML = "";
    if (!candidates.length) {
      const opt = document.createElement("option");
      opt.value = "";
      opt.textContent = "该区暂无乘客";
      elSelectTarget.appendChild(opt);
    } else {
      for (const n of candidates) {
        const opt = document.createElement("option");
        opt.value = n.id;
        opt.textContent = `${n.name}（${n.role}）`;
        elSelectTarget.appendChild(opt);
      }
      if (candidates.some((c) => c.id === prev)) {
        elSelectTarget.value = prev;
      }
    }
  }

  function renderCluesAndPuzzle(view) {
    elClueCount.textContent = `${view.clues.length} / 8`;
    elClueList.innerHTML = "";
    const prevClue = elSelectClue.value;
    elSelectClue.innerHTML = '<option value="">不出示线索牌</option>';

    for (const c of view.clues) {
      const card = document.createElement("div");
      card.className = `clue-card ${c.has_physical ? "is-physical" : ""}`;
      card.innerHTML = `
        <div class="clue-title">
          <span>${c.name}</span>
          <span>${c.has_physical ? "★ 本轮实物" : c.id.split("_")[0]}</span>
        </div>
        <div class="clue-text">${c.text}</div>
      `;
      elClueList.appendChild(card);

      const opt = document.createElement("option");
      opt.value = c.id;
      opt.textContent = `${c.has_physical ? "★[实物] " : ""}${c.name}`;
      elSelectClue.appendChild(opt);
    }
    if (view.clues.some((c) => c.id === prevClue)) {
      elSelectClue.value = prevClue;
    }

    renderPuzzleContainer(elPuzzleSlots, view, "main");
    elPuzzleBadge.textContent = view.puzzle.solved ? "已洞悉真相" : "未完成";
    elPuzzleBadge.classList.toggle("solved", !!view.puzzle.solved);

    elNotebook.innerHTML = view.notebook.length
      ? view.notebook.map((n) => `<li>${n}</li>`).join("")
      : "<li>尚无观察记录（点击“观察细节”或车尾装睡偷听获取）</li>";
  }

  function renderPuzzleContainer(container, view, prefix) {
    container.innerHTML = "";
    for (const meta of view.puzzle.slots_meta) {
      const wrap = document.createElement("div");
      wrap.className = "puzzle-slot";
      const curVal = view.puzzle.slots[meta.slot] || "";
      const options = [
        '<option value="">— 选择线索牌 —</option>',
        ...view.clues.map(
          (c) => `<option value="${c.id}" ${curVal === c.id ? "selected" : ""}>${c.name}</option>`
        ),
      ].join("");
      wrap.innerHTML = `
        <label for="${prefix}-slot-${meta.slot}">${meta.label}</label>
        <select id="${prefix}-slot-${meta.slot}" data-slot="${meta.slot}">${options}</select>
      `;
      container.appendChild(wrap);
    }
  }

  function renderHints(view) {
    elHintsBar.innerHTML = "";
    if (STATE.mode === "WAIT" || STATE.mode === "OBSERVE") return;
    for (const h of view.speech_hints) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "hint-chip";
      btn.textContent = `💡 ${h.label}`;
      btn.onclick = () => {
        elSpeechInput.value = h.prefill;
        elSpeechInput.focus();
      };
      elHintsBar.appendChild(btn);
    }
  }

  function renderInspector(inspector) {
    if (!inspector) return;
    document.getElementById("inspector-flags").textContent = JSON.stringify(
      {
        turn: inspector.turn,
        loop_count: inspector.loop_count,
        player_items: inspector.player_items,
        npc_items: inspector.items,
        flags: inspector.flags,
      },
      null,
      2
    );

    const memBox = document.getElementById("inspector-memories");
    memBox.innerHTML = "";
    for (const [npcId, mems] of Object.entries(inspector.memories || {})) {
      const div = document.createElement("div");
      div.className = "memory-card";
      div.innerHTML = `
        <strong>${npcId} 私有记忆 (${mems.length})</strong>
        <ul>${mems.length ? mems.map((m) => `<li>${m}</li>`).join("") : "<li>暂无</li>"}</ul>
      `;
      memBox.appendChild(div);
    }

    const logBox = document.getElementById("inspector-logs");
    logBox.innerHTML = "";
    const logs = (inspector.logs || []).slice().reverse();
    for (const entry of logs) {
      const div = document.createElement("div");
      div.className = "log-entry";
      const retryHtml = entry.retry
        ? `<div style="color:#fde68a;margin-top:4px;">↳ 重决策：<code>${entry.retry.action}(${entry.retry.target || ""})</code> → <strong>${entry.retry.verdict}</strong> ${entry.retry.reason || ""}</div>`
        : "";
      div.innerHTML = `
        <div class="log-top">
          <span>[T${entry.turn} ${entry.clock}] ${entry.npc}${entry.forced ? " (规则强制)" : ""}${entry.skipped_llm ? " (省调用跳过)" : ""}</span>
          <span class="verdict-badge verdict-${entry.verdict}">${entry.verdict}</span>
        </div>
        <div>动作提案：<code>${entry.proposed.action}(${entry.proposed.target || ""})</code> ${entry.reason ? `· ${entry.reason}` : ""}</div>
        ${retryHtml}
        <div>命中标签：<code>${(entry.tags_hit || []).join(", ") || "无"}</code> ｜ 数值变动：<code>${JSON.stringify(entry.delta || {})}</code></div>
        ${entry.thought ? `<div style="color:#c084fc;margin-top:3px;">内心独白：${entry.thought}</div>` : ""}
        <div style="color:#64748b;font-size:11px;margin-top:3px;">llm_ms=${entry.llm_ms}ms · json_repaired=${entry.json_repaired}</div>
      `;
      logBox.appendChild(div);
    }
  }

  function updateModeControls() {
    document.querySelectorAll(".mode-btn").forEach((b) => {
      b.classList.toggle("active", b.dataset.mode === STATE.mode);
    });
    const isWait = STATE.mode === "WAIT";
    const isObserve = STATE.mode === "OBSERVE";
    const isPublic = STATE.mode === "SPEAK_PUBLIC";
    document.getElementById("target-group").classList.toggle("hidden", isWait || isPublic);
    document.getElementById("clue-group").classList.toggle("hidden", isWait || isObserve);
    elSpeechInput.classList.toggle("hidden", isWait || isObserve);
    elSubmitBtn.textContent = isWait ? "静观 / 装睡（推进 1 分钟）" : isObserve ? "执行观察" : "发送并推进 1 分钟";
    if (STATE.view) renderHints(STATE.view);
  }

  function renderAll(view, inspector) {
    STATE.view = view;
    if (inspector) STATE.inspector = inspector;

    elClock.textContent = view.clock;
    elLoop.textContent = view.loop_count;
    elTurn.textContent = `${view.turn}/${view.max_turns}`;
    elCurrentZone.textContent = `当前位置：${zoneName(view, view.player.zone)}`;
    const hasLogbook = view.player.items.includes("ITEM_LOGBOOK");
    elPlayerItems.textContent = hasLogbook ? "随身物：降噪耳机 + ★老赵记录本与旧工牌" : "随身物：降噪耳机";
    elSkipBtn.classList.toggle("hidden", !view.can_skip_to_t2);

    if (view.ending) {
      setVisualMode(view.ending.visual || "normal");
      showEndingOverlay(view.ending);
    } else if (view.turn >= 7) {
      setVisualMode("warning");
    } else {
      setVisualMode("loop");
    }

    renderZones(view);
    renderNpcs(view);
    refreshTargetOptions();
    renderCluesAndPuzzle(view);
    updateModeControls();
    renderInspector(STATE.inspector);

    if (view.awaiting_final_puzzle) {
      openFinalPuzzleModal(view);
    }
  }

  // ── 4. Dramatic Overlays (Rollback Clock & Endings) ──
  async function playRollbackAnimation(descText) {
    const overlay = document.getElementById("rollback-overlay");
    const flash = document.getElementById("arc-flash");
    const clockEl = document.getElementById("rollback-clock");
    const descEl = document.getElementById("rollback-desc");
    const actionsEl = document.getElementById("rollback-actions");

    actionsEl.classList.add("hidden");
    descEl.textContent = descText || "";
    clockEl.textContent = "23:59";
    overlay.classList.remove("hidden");
    flash.classList.remove("active");
    void flash.offsetWidth;
    flash.classList.add("active");

    const seq = ["23:59", "23:58", "23:57", "23:56", "23:55", "23:54", "23:53", "23:52"];
    for (const c of seq) {
      clockEl.textContent = c;
      await new Promise((r) => setTimeout(r, 150));
    }
    actionsEl.classList.remove("hidden");
  }

  function showEndingOverlay(ending) {
    const overlay = document.getElementById("ending-overlay");
    overlay.className = `ending-overlay visual-${ending.visual || "normal"}`;
    document.getElementById("ending-clock").textContent =
      ending.visual === "bright" ? "00:00 · 终点站 · 安全抵达" : "00:00 · 江心站";
    document.getElementById("ending-title").textContent = ending.title;
    document.getElementById("ending-narration").textContent = ending.narration;

    const fbox = document.getElementById("ending-farewells");
    fbox.innerHTML = (ending.farewells || [])
      .map((f) => `<div class="farewell-item"><strong>${f.name || f.npc}：</strong>“${f.text}”</div>`)
      .join("");
    overlay.classList.remove("hidden");
  }

  function openFinalPuzzleModal(view) {
    const modal = document.getElementById("final-puzzle-modal");
    renderPuzzleContainer(document.getElementById("final-puzzle-slots"), view, "final");
    document.getElementById("final-puzzle-feedback").textContent = "";
    modal.classList.remove("hidden");
  }

  // ── 5. User Actions ──
  async function startSession() {
    elEventFeed.innerHTML = "";
    const data = await apiFetch("/api/session", { method: "POST", body: "{}" });
    STATE.sessionId = data.session_id;
    renderAll(data.view, data.inspector);
    appendEvents([
      { kind: "broadcast", text: data.view.opening_narration },
      ...(data.events || []),
    ]);
  }

  async function doRestart(skipToT2) {
    document.getElementById("rollback-overlay").classList.add("hidden");
    document.getElementById("ending-overlay").classList.add("hidden");
    document.getElementById("final-puzzle-modal").classList.add("hidden");
    elSelectMove.value = "";
    const data = await apiFetch("/api/restart", {
      method: "POST",
      body: JSON.stringify({ session_id: STATE.sessionId, skip_to_t2: !!skipToT2 }),
    });
    elEventFeed.innerHTML = "";
    renderAll(data.view, data.inspector);
    appendEvents(data.events || []);
  }

  async function submitTurn() {
    if (STATE.busy || !STATE.sessionId) return;
    elInputError.classList.add("hidden");

    const move = elSelectMove.value || null;
    const action = { type: STATE.mode, target: null, text: "", clue_id: null };
    if (STATE.mode === "SPEAK_PRIVATE") {
      action.target = elSelectTarget.value || null;
      action.text = elSpeechInput.value.trim();
      action.clue_id = elSelectClue.value || null;
    } else if (STATE.mode === "SPEAK_PUBLIC") {
      action.text = elSpeechInput.value.trim();
      action.clue_id = elSelectClue.value || null;
    } else if (STATE.mode === "OBSERVE") {
      action.target = elSelectTarget.value || null;
    }

    STATE.busy = true;
    elSubmitBtn.disabled = true;
    elTransit.classList.remove("hidden");
    const prevVisual = STATE.visualMode;
    setVisualMode("transit");
    const startTs = performance.now();

    try {
      const data = await apiFetch("/api/turn", {
        method: "POST",
        body: JSON.stringify({ session_id: STATE.sessionId, move, action }),
      });

      // Keep smooth tunnel acceleration transition at least 900ms for atmospheric pacing
      const elapsed = performance.now() - startTs;
      if (elapsed < 900) {
        await new Promise((r) => setTimeout(r, 900 - elapsed));
      }

      elSpeechInput.value = "";
      elSelectClue.value = "";
      elSelectMove.value = "";

      appendEvents(data.events || []);
      renderAll(data.view, data.inspector);

      const resetEvent = (data.events || []).find((e) => e.kind === "loop_reset");
      if (resetEvent) {
        await playRollbackAnimation(resetEvent.text);
      }
    } catch (err) {
      setVisualMode(prevVisual);
      elInputError.textContent = err.message;
      elInputError.classList.remove("hidden");
    } finally {
      STATE.busy = false;
      elSubmitBtn.disabled = false;
      elTransit.classList.add("hidden");
    }
  }

  async function submitPuzzleFrom(prefix, feedbackEl) {
    const slots = {};
    for (const k of ["1", "2", "3", "4"]) {
      const sel = document.getElementById(`${prefix}-slot-${k}`);
      slots[k] = sel && sel.value ? sel.value : null;
    }
    const data = await apiFetch("/api/puzzle", {
      method: "POST",
      body: JSON.stringify({ session_id: STATE.sessionId, slots }),
    });
    feedbackEl.textContent = data.hint;
    renderAll(data.view, STATE.inspector);
    return data.solved;
  }

  // ── 6. Event Listeners ──
  document.querySelectorAll(".mode-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      STATE.mode = btn.dataset.mode;
      updateModeControls();
    });
  });

  elSelectMove.addEventListener("change", () => {
    if (STATE.view) renderZones(STATE.view);
    refreshTargetOptions();
  });

  elSubmitBtn.addEventListener("click", submitTurn);
  elSpeechInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") submitTurn();
  });

  document.getElementById("btn-check-puzzle").addEventListener("click", () => {
    submitPuzzleFrom("main", elPuzzleHint);
  });

  document.getElementById("btn-restart").addEventListener("click", () => doRestart(false));
  document.getElementById("btn-skip-t2").addEventListener("click", () => doRestart(true));
  document.getElementById("btn-rollback-t1").addEventListener("click", () => {
    document.getElementById("rollback-overlay").classList.add("hidden");
    elEventFeed.innerHTML = "";
    appendEvents([{ kind: "broadcast", text: STATE.view.opening_narration }]);
  });
  document.getElementById("btn-rollback-t2").addEventListener("click", () => doRestart(true));
  document.getElementById("btn-ending-t1").addEventListener("click", () => doRestart(false));
  document.getElementById("btn-ending-t2").addEventListener("click", () => doRestart(true));

  document.getElementById("btn-final-check-go").addEventListener("click", async () => {
    const fb = document.getElementById("final-puzzle-feedback");
    await submitPuzzleFrom("final", fb);
    document.getElementById("final-puzzle-modal").classList.add("hidden");
    const fin = await apiFetch("/api/finalize", {
      method: "POST",
      body: JSON.stringify({ session_id: STATE.sessionId }),
    });
    appendEvents(fin.events || []);
    renderAll(fin.view, fin.inspector);
    const resetEv = (fin.events || []).find((e) => e.kind === "loop_reset");
    if (resetEv) await playRollbackAnimation(resetEv.text);
  });

  document.getElementById("btn-final-skip").addEventListener("click", async () => {
    document.getElementById("final-puzzle-modal").classList.add("hidden");
    const fin = await apiFetch("/api/finalize", {
      method: "POST",
      body: JSON.stringify({ session_id: STATE.sessionId }),
    });
    appendEvents(fin.events || []);
    renderAll(fin.view, fin.inspector);
    const resetEv = (fin.events || []).find((e) => e.kind === "loop_reset");
    if (resetEv) await playRollbackAnimation(resetEv.text);
  });

  // Inspector Drawer
  const drawer = document.getElementById("inspector-drawer");
  document.getElementById("btn-inspector").addEventListener("click", () => {
    const isHidden = drawer.classList.toggle("hidden");
    drawer.setAttribute("aria-hidden", String(isHidden));
    if (!isHidden) renderInspector(STATE.inspector);
  });
  document.getElementById("btn-close-inspector").addEventListener("click", () => {
    drawer.classList.add("hidden");
    drawer.setAttribute("aria-hidden", "true");
  });

  // User Token Modal
  const tokenModal = document.getElementById("token-modal");
  const tokenInput = document.getElementById("token-input");
  document.getElementById("btn-token").addEventListener("click", () => {
    tokenInput.value = STATE.userToken;
    tokenModal.classList.remove("hidden");
  });
  document.getElementById("btn-close-token").addEventListener("click", () => tokenModal.classList.add("hidden"));
  document.getElementById("btn-clear-token").addEventListener("click", () => {
    STATE.userToken = "";
    tokenInput.value = "";
    tokenModal.classList.add("hidden");
  });
  document.getElementById("btn-save-token").addEventListener("click", () => {
    STATE.userToken = tokenInput.value.trim();
    tokenModal.classList.add("hidden");
  });

  startSession().catch((err) => {
    elEventFeed.innerHTML = `<div class="event-item kind-brake">初始化失败：${err.message}</div>`;
  });
})();
