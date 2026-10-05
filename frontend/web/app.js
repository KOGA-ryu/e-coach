/**
 * ValLens Review Interface Engine
 * Synchronizes video playback, dynamic minimap telemetry, hotkey review tagging, and telestrator overlays.
 */

// Application State
const state = {
  currentMatchId: null,
  matchMetadata: null,
  events: [],
  chapters: [],
  tags: [],
  authorType: 'solo', // 'solo' or 'coach'
  activeRound: 0,
  minimapFilter: 'all', // 'all', 'kill', 'death'
  radarMode: true, // true: dynamic temporal playback; false: static round
  mapImage: new Image(),
  mapLoaded: false,
  hoveredEvent: null,

  // Undo Tag Buffer Stack
  tagHistoryStack: [], // Array of { tag_id, name }

  // Telestrator State
  telestratorActive: false,
  teleTool: 'pen', // 'pen', 'arrow', 'circle'
  teleColor: '#ff4655',
  isDrawing: false,
  drawStartX: 0,
  drawStartY: 0,
  savedCanvasImage: null,
};

// DOM Elements
const matchSelect = document.getElementById('match-select');
const videoPlayer = document.getElementById('video-player');
const videoWrapper = document.getElementById('video-wrapper');
const videoPlaceholder = document.getElementById('video-placeholder');
const videoFileInput = document.getElementById('video-file-input');

const timecodeDisplay = document.getElementById('timecode-display');
const scrubberContainer = document.getElementById('scrubber-container');
const scrubberProgress = document.getElementById('scrubber-progress');
const scrubberThumb = document.getElementById('scrubber-thumb');
const roundMarkers = document.getElementById('round-markers');
const roundPills = document.getElementById('round-pills');
const roundEventsList = document.getElementById('round-events-list');

const minimapCanvas = document.getElementById('minimap-canvas');
const ctx = minimapCanvas.getContext('2d');
const mapTooltip = document.getElementById('map-tooltip');
const btnRadarMode = document.getElementById('btn-radar-mode');

const tagGrid = document.getElementById('tag-grid');
const tagToast = document.getElementById('tag-toast');
const tagHistoryList = document.getElementById('tag-history-list');
const tagCountEl = document.getElementById('tag-count');
const habitBars = document.getElementById('habit-bars');
const btnUndoTag = document.getElementById('btn-undo-tag');

const btnPlayPause = document.getElementById('btn-play-pause');
const btnPrevFrame = document.getElementById('btn-prev-frame');
const btnNextFrame = document.getElementById('btn-next-frame');
const btnPrevRound = document.getElementById('btn-prev-round');
const btnNextRound = document.getElementById('btn-next-round');

// Telestrator Elements
const teleCanvas = document.getElementById('telestrator-canvas');
const teleCtx = teleCanvas.getContext('2d');
const btnTeleToggle = document.getElementById('btn-telestrator-toggle');
const teleTools = document.getElementById('tele-tools');

// Tag Mapping for 1-9 Hotkeys
const TAG_MAP = {
  '1': { category: 'Mechanics', name: 'crosshair_placement' },
  '2': { category: 'Mechanics', name: 'whiffed_spray' },
  '3': { category: 'Positioning', name: 'over_peeking' },
  '4': { category: 'Positioning', name: 'poor_spacing' },
  '5': { category: 'Utility', name: 'wasted_utility' },
  '6': { category: 'Utility', name: 'late_flash' },
  '7': { category: 'Decision', name: 'forced_fight' },
  '8': { category: 'Decision', name: 'late_rotate' },
  '9': { category: 'Strength', name: 'great_crossfire' },
};

// -------------------------------------------------------------
// Initialization & Match Loading
// -------------------------------------------------------------
async function init() {
  setupEventListeners();
  setupTelestrator();
  await loadMatchList();
}

async function loadMatchList() {
  try {
    const res = await fetch('/api/matches');
    const matches = await res.json();
    matchSelect.innerHTML = '';

    if (!matches || matches.length === 0) {
      matchSelect.innerHTML = '<option value="">No matches found in DB</option>';
      return;
    }

    matches.forEach((m) => {
      const opt = document.createElement('option');
      opt.value = m.match_id;
      const mapName = getMapNameFromPath(m.map_id);
      opt.textContent = `${mapName.toUpperCase()} — ${m.match_id.slice(0, 8)}... (${(m.match_duration / 60000).toFixed(1)}m)`;
      matchSelect.appendChild(opt);
    });

    // Load first match by default
    loadMatch(matches[0].match_id);
  } catch (err) {
    console.error('Failed to load match list:', err);
  }
}

async function loadMatch(matchId) {
  state.currentMatchId = matchId;

  try {
    // 1. Fetch match overview
    const overviewRes = await fetch(`/api/matches/${matchId}`);
    const overview = await overviewRes.json();
    state.matchMetadata = overview.metadata;

    updateMatchHeader(overview);
    document.getElementById('btn-view-report').href = `/api/matches/${matchId}/report`;

    // 2. Fetch telemetry events
    const eventsRes = await fetch(`/api/matches/${matchId}/events`);
    state.events = await eventsRes.json();

    // 3. Fetch chapters / rounds
    const chaptersRes = await fetch(`/api/matches/${matchId}/chapters`);
    state.chapters = await chaptersRes.json();

    // 4. Fetch tags
    await loadTags();

    // 5. Setup map background
    const mapName = getMapNameFromPath(state.matchMetadata.map_id);
    loadMapImage(mapName);

    // 6. Build UI components
    buildRoundPills();
    buildScrubberMarkers();
    selectRound(0);

    // 7. Configure video source if video_filepath exists
    if (state.matchMetadata.video_filepath) {
      videoPlayer.src = `/api/video?path=${encodeURIComponent(state.matchMetadata.video_filepath)}`;
      videoPlaceholder.style.display = 'none';
    } else {
      videoPlaceholder.style.display = 'flex';
    }

  } catch (err) {
    console.error('Failed to load match data:', err);
  }
}

function updateMatchHeader(overview) {
  const m = overview.metadata;
  document.getElementById('info-map').textContent = getMapNameFromPath(m.map_id).toUpperCase();
  document.getElementById('info-mode').textContent = m.game_mode.includes('Bomb') ? 'COMPETITIVE' : m.game_mode;
  document.getElementById('info-rounds').textContent = overview.rounds_count;
  document.getElementById('info-kd').textContent = `${overview.total_kills} / ${overview.total_deaths}`;
}

function getMapNameFromPath(mapPath) {
  if (!mapPath) return 'ascent';
  const parts = mapPath.split('/');
  return parts[parts.length - 1].toLowerCase();
}

function loadMapImage(mapName) {
  state.mapLoaded = false;
  state.mapImage.onload = () => {
    state.mapLoaded = true;
    renderMinimap();
  };
  state.mapImage.src = `/maps/${mapName}.png`;
}

// -------------------------------------------------------------
// -3s Pre-Roll Event Seek
// -------------------------------------------------------------
function seekToEventWithPreRoll(eventTimeMs) {
  if (!videoPlayer.duration) return;
  // Jump 3 seconds before event to analyze angle isolation and pre-aim
  const targetSec = Math.max(0, (eventTimeMs - 3000) / 1000);
  videoPlayer.currentTime = targetSec;
  showToast(`Pre-roll (-3s) -> ${formatTime(targetSec)}`);
}

// -------------------------------------------------------------
// Round Navigation & Events Feed
// -------------------------------------------------------------
function buildRoundPills() {
  roundPills.innerHTML = '';
  state.chapters.forEach((ch, idx) => {
    const pill = document.createElement('button');
    pill.className = `round-pill ${idx === state.activeRound ? 'active' : ''}`;
    pill.textContent = `R${ch.round_num + 1}`;
    pill.title = ch.comment;
    pill.addEventListener('click', () => selectRound(ch.round_num));
    roundPills.appendChild(pill);
  });
}

function selectRound(roundNum) {
  state.activeRound = roundNum;
  document.getElementById('info-active-round').textContent = `ROUND ${roundNum + 1}`;

  // Update round pills highlight
  document.querySelectorAll('.round-pill').forEach((pill, idx) => {
    pill.classList.toggle('active', idx === roundNum);
  });

  // Filter events feed
  const roundEvents = state.events.filter((e) => e.round_number === roundNum);
  renderRoundEventsFeed(roundEvents);

  // Jump video to round start if chapter exists
  const chap = state.chapters.find((c) => c.round_num === roundNum);
  if (chap && videoPlayer.duration) {
    videoPlayer.currentTime = chap.start_ms / 1000;
  }

  // Redraw minimap for active round
  renderMinimap();
}

function renderRoundEventsFeed(events) {
  roundEventsList.innerHTML = '';
  if (!events || events.length === 0) {
    roundEventsList.innerHTML = '<div class="feed-empty">No events in this round</div>';
    return;
  }

  events.forEach((e) => {
    if (e.event_type === 'round_start' || e.event_type === 'round_end') return;

    const item = document.createElement('div');
    const isKill = e.event_type === 'kill';
    const isPlant = e.event_type === 'plant' || e.event_type === 'defuse';
    item.className = `feed-item ${isKill ? 'kill-item' : isPlant ? 'plant-item' : ''}`;

    let label = e.event_type.toUpperCase();
    if (isKill) {
      const weapon = e.metadata.weapon || 'Weapon';
      label = `KILL [${weapon}] -> ${(e.metadata.victim || 'Enemy').slice(0, 8)}`;
    } else if (e.event_type === 'death') {
      const weapon = e.metadata.weapon || 'Weapon';
      label = `DEATH by ${(e.metadata.killer || 'Enemy').slice(0, 8)} [${weapon}]`;
    } else if (e.event_type === 'plant') {
      label = `SPIKE PLANTED (Site ${e.metadata.site || 'A'})`;
    } else if (e.event_type === 'defuse') {
      label = `SPIKE DEFUSED`;
    }

    item.innerHTML = `
      <span>${label}</span>
      <span class="feed-time">${formatTime(e.event_time_ms / 1000)}</span>
    `;

    item.addEventListener('click', () => {
      seekToEventWithPreRoll(e.event_time_ms);
    });

    roundEventsList.appendChild(item);
  });
}

// -------------------------------------------------------------
// Temporal Dynamic Minimap Engine
// -------------------------------------------------------------
function renderMinimap() {
  const w = minimapCanvas.width;
  const h = minimapCanvas.height;

  ctx.clearRect(0, 0, w, h);

  // 1. Draw Map Background
  if (state.mapLoaded) {
    ctx.drawImage(state.mapImage, 0, 0, w, h);
  } else {
    ctx.fillStyle = '#0f1923';
    ctx.fillRect(0, 0, w, h);
    ctx.fillStyle = '#546575';
    ctx.font = '14px Rajdhani';
    ctx.textAlign = 'center';
    ctx.fillText('Loading Map Asset...', w / 2, h / 2);
  }

  const currentVideoMs = Math.round((videoPlayer.currentTime || 0) * 1000);

  // 2. Filter events for current view
  const currentEvents = state.events.filter((e) => {
    if (e.round_number !== state.activeRound) return false;
    if (state.minimapFilter === 'kill' && e.event_type !== 'kill') return false;
    if (state.minimapFilter === 'death' && e.event_type !== 'death') return false;
    if (e.pos_x === null || e.pos_y === null) return false;

    // Temporal Live Radar mode check
    if (state.radarMode && videoPlayer.duration) {
      return e.event_time_ms <= currentVideoMs;
    }
    return true;
  });

  // 3. Draw Telemetry Points
  currentEvents.forEach((e) => {
    const px = e.pos_x * w;
    const py = e.pos_y * h;
    const deltaMs = currentVideoMs - e.event_time_ms;
    const isRecent = state.radarMode && deltaMs >= 0 && deltaMs <= 3000;

    ctx.save();

    // Recent Event Pulsing Radar Shockwave
    if (isRecent) {
      const pulseRatio = (deltaMs % 1000) / 1000;
      const pulseRadius = 10 + pulseRatio * 20;
      ctx.strokeStyle = e.event_type === 'kill' ? `rgba(6, 214, 160, ${1 - pulseRatio})` : `rgba(255, 70, 85, ${1 - pulseRatio})`;
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.arc(px, py, pulseRadius, 0, Math.PI * 2);
      ctx.stroke();
    }

    if (e.event_type === 'kill') {
      // Green / Cyan Crosshair for Kills
      ctx.strokeStyle = '#06d6a0';
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.arc(px, py, 7, 0, Math.PI * 2);
      ctx.stroke();

      ctx.beginPath();
      ctx.moveTo(px - 10, py);
      ctx.lineTo(px + 10, py);
      ctx.moveTo(px, py - 10);
      ctx.lineTo(px, py + 10);
      ctx.stroke();
    } else if (e.event_type === 'death') {
      // Red Skull Marker for Deaths
      ctx.fillStyle = 'rgba(255, 70, 85, 0.9)';
      ctx.beginPath();
      ctx.arc(px, py, 8, 0, Math.PI * 2);
      ctx.fill();
      ctx.strokeStyle = '#ffffff';
      ctx.lineWidth = 1.5;
      ctx.stroke();
    } else if (e.event_type === 'plant' || e.event_type === 'defuse') {
      // Yellow Diamond for Spike
      ctx.fillStyle = '#ffd166';
      ctx.beginPath();
      ctx.moveTo(px, py - 8);
      ctx.lineTo(px + 8, py);
      ctx.lineTo(px, py + 8);
      ctx.lineTo(px - 8, py);
      ctx.closePath();
      ctx.fill();
    }
    ctx.restore();
  });
}

// -------------------------------------------------------------
// Hotkey Review Tagging & Undo Stack
// -------------------------------------------------------------
async function logTag(key) {
  const mapping = TAG_MAP[key];
  if (!mapping || !state.currentMatchId) return;

  const currentMs = Math.round((videoPlayer.currentTime || 0) * 1000);

  // Visual card click animation
  const card = document.querySelector(`.tag-card[data-key="${key}"]`);
  if (card) {
    card.classList.add('active');
    setTimeout(() => card.classList.remove('active'), 150);
  }

  try {
    const res = await fetch(`/api/matches/${state.currentMatchId}/tags`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        timestamp_ms: currentMs,
        category: mapping.category,
        name: mapping.name,
        author: state.authorType,
      }),
    });

    if (res.ok) {
      const data = await res.json();
      state.tagHistoryStack.push({ tag_id: data.tag_id, name: mapping.name });
      showToast(`[${key}] ${mapping.name} logged at ${formatTime(currentMs / 1000)} (Ctrl+Z to Undo)`);
      await loadTags();
    }
  } catch (err) {
    console.error('Failed to log tag:', err);
  }
}

async function undoLastTag() {
  if (state.tagHistoryStack.length === 0) {
    showToast('No tags to undo');
    return;
  }

  const last = state.tagHistoryStack.pop();
  try {
    const res = await fetch(`/api/tags/${last.tag_id}`, { method: 'DELETE' });
    if (res.ok) {
      showToast(`Undid tag [${last.name}]`);
      await loadTags();
    }
  } catch (err) {
    console.error('Failed to undo tag:', err);
  }
}

async function loadTags() {
  if (!state.currentMatchId) return;

  try {
    const res = await fetch(`/api/matches/${state.currentMatchId}/tags`);
    state.tags = await res.json();
    renderTagHistory();
    renderHabitInsights();
  } catch (err) {
    console.error('Failed to load tags:', err);
  }
}

function renderTagHistory() {
  tagHistoryList.innerHTML = '';
  tagCountEl.textContent = state.tags.length;

  if (state.tags.length === 0) {
    tagHistoryList.innerHTML = '<div class="empty-tags">No tags applied yet. Use numeric keys [1-9] while reviewing.</div>';
    return;
  }

  state.tags.slice().reverse().forEach((t) => {
    const item = document.createElement('div');
    item.className = 'tag-item';

    item.innerHTML = `
      <div class="tag-item-left">
        <span class="tag-badge ${t.author}">${t.author}</span>
        <span class="tag-name">${t.name}</span>
        <span class="feed-time">${formatTime(t.timestamp_ms / 1000)}</span>
      </div>
      <button class="tag-delete-btn" data-id="${t.tag_id}" title="Delete Tag">×</button>
    `;

    item.addEventListener('click', (e) => {
      if (e.target.classList.contains('tag-delete-btn')) {
        deleteTag(t.tag_id);
      } else {
        seekToEventWithPreRoll(t.timestamp_ms);
      }
    });

    tagHistoryList.appendChild(item);
  });
}

async function deleteTag(tagId) {
  try {
    const res = await fetch(`/api/tags/${tagId}`, { method: 'DELETE' });
    if (res.ok) {
      await loadTags();
    }
  } catch (err) {
    console.error('Failed to delete tag:', err);
  }
}

function renderHabitInsights() {
  habitBars.innerHTML = '';

  const counts = {};
  state.tags.forEach((t) => {
    counts[t.name] = (counts[t.name] || 0) + 1;
  });

  const sorted = Object.entries(counts).sort((a, b) => b[1] - a[1]);
  const max = sorted.length > 0 ? sorted[0][1] : 1;

  if (sorted.length === 0) {
    habitBars.innerHTML = '<div class="empty-tags">Log tags to generate habit distribution</div>';
    return;
  }

  sorted.forEach(([name, count]) => {
    const pct = Math.round((count / max) * 100);
    const row = document.createElement('div');
    row.className = 'habit-row';
    row.innerHTML = `
      <div class="habit-header">
        <span>${name}</span>
        <span>${count}x</span>
      </div>
      <div class="habit-bar-bg">
        <div class="habit-bar-fill" style="width: ${pct}%"></div>
      </div>
    `;
    habitBars.appendChild(row);
  });
}

function showToast(msg) {
  tagToast.textContent = msg;
  tagToast.style.display = 'block';
  setTimeout(() => {
    tagToast.style.display = 'none';
  }, 1800);
}

// -------------------------------------------------------------
// Interactive Telestrator Drawing Engine
// -------------------------------------------------------------
function setupTelestrator() {
  resizeTelestratorCanvas();
  window.addEventListener('resize', resizeTelestratorCanvas);

  btnTeleToggle.addEventListener('click', toggleTelestrator);

  document.querySelectorAll('.color-dot').forEach((dot) => {
    dot.addEventListener('click', () => {
      document.querySelectorAll('.color-dot').forEach((d) => d.classList.remove('active'));
      dot.classList.add('active');
      state.teleColor = dot.dataset.color;
    });
  });

  document.querySelectorAll('.tool-btn').forEach((btn) => {
    if (btn.id === 'btn-tool-clear') {
      btn.addEventListener('click', clearTelestrator);
    } else {
      btn.addEventListener('click', () => {
        document.querySelectorAll('.tool-btn').forEach((b) => {
          if (b.id !== 'btn-tool-clear') b.classList.remove('active');
        });
        btn.classList.add('active');
        state.teleTool = btn.dataset.tool;
      });
    }
  });

  teleCanvas.addEventListener('mousedown', (e) => {
    if (!state.telestratorActive) return;
    state.isDrawing = true;
    const rect = teleCanvas.getBoundingClientRect();
    state.drawStartX = e.clientX - rect.left;
    state.drawStartY = e.clientY - rect.top;

    state.savedCanvasImage = teleCtx.getImageData(0, 0, teleCanvas.width, teleCanvas.height);

    if (state.teleTool === 'pen') {
      teleCtx.beginPath();
      teleCtx.moveTo(state.drawStartX, state.drawStartY);
      teleCtx.strokeStyle = state.teleColor;
      teleCtx.lineWidth = 3;
      teleCtx.lineCap = 'round';
      teleCtx.lineJoin = 'round';
    }
  });

  teleCanvas.addEventListener('mousemove', (e) => {
    if (!state.telestratorActive || !state.isDrawing) return;
    const rect = teleCanvas.getBoundingClientRect();
    const currX = e.clientX - rect.left;
    const currY = e.clientY - rect.top;

    if (state.teleTool === 'pen') {
      teleCtx.lineTo(currX, currY);
      teleCtx.stroke();
    } else if (state.teleTool === 'arrow') {
      teleCtx.putImageData(state.savedCanvasImage, 0, 0);
      drawArrow(state.drawStartX, state.drawStartY, currX, currY, state.teleColor);
    } else if (state.teleTool === 'circle') {
      teleCtx.putImageData(state.savedCanvasImage, 0, 0);
      const rad = Math.sqrt(Math.pow(currX - state.drawStartX, 2) + Math.pow(currY - state.drawStartY, 2));
      teleCtx.beginPath();
      teleCtx.arc(state.drawStartX, state.drawStartY, rad, 0, Math.PI * 2);
      teleCtx.strokeStyle = state.teleColor;
      teleCtx.lineWidth = 3;
      teleCtx.stroke();
    }
  });

  window.addEventListener('mouseup', () => {
    state.isDrawing = false;
  });
}

function resizeTelestratorCanvas() {
  const rect = videoWrapper.getBoundingClientRect();
  teleCanvas.width = rect.width;
  teleCanvas.height = rect.height;
}

function toggleTelestrator() {
  state.telestratorActive = !state.telestratorActive;
  if (state.telestratorActive) {
    if (!videoPlayer.paused) {
      videoPlayer.pause();
      btnPlayPause.textContent = 'PLAY';
    }
    teleCanvas.classList.add('active');
    btnTeleToggle.classList.add('active');
    teleTools.style.display = 'flex';
    resizeTelestratorCanvas();
    showToast('Telestrator Active: Draw on video');
  } else {
    teleCanvas.classList.remove('active');
    btnTeleToggle.classList.remove('active');
    teleTools.style.display = 'none';
  }
}

function clearTelestrator() {
  teleCtx.clearRect(0, 0, teleCanvas.width, teleCanvas.height);
}

function drawArrow(fromx, fromy, tox, toy, color) {
  const headlen = 14;
  const angle = Math.atan2(toy - fromy, tox - fromx);

  teleCtx.save();
  teleCtx.strokeStyle = color;
  teleCtx.fillStyle = color;
  teleCtx.lineWidth = 3;

  // Main line
  teleCtx.beginPath();
  teleCtx.moveTo(fromx, fromy);
  teleCtx.lineTo(tox, toy);
  teleCtx.stroke();

  // Arrowhead
  teleCtx.beginPath();
  teleCtx.moveTo(tox, toy);
  teleCtx.lineTo(tox - headlen * Math.cos(angle - Math.PI / 6), toy - headlen * Math.sin(angle - Math.PI / 6));
  teleCtx.lineTo(tox - headlen * Math.cos(angle + Math.PI / 6), toy - headlen * Math.sin(angle + Math.PI / 6));
  teleCtx.closePath();
  teleCtx.fill();
  teleCtx.restore();
}

// -------------------------------------------------------------
// Video Player Controls & Timecode
// -------------------------------------------------------------
function buildScrubberMarkers() {
  roundMarkers.innerHTML = '';
  if (!videoPlayer.duration || !state.chapters) return;

  const totalDur = videoPlayer.duration;
  state.chapters.forEach((ch) => {
    const sec = ch.start_ms / 1000;
    const pct = (sec / totalDur) * 100;
    const marker = document.createElement('div');
    marker.className = 'round-marker';
    marker.style.left = `${pct}%`;
    marker.title = ch.comment;
    roundMarkers.appendChild(marker);
  });
}

function updateScrubber() {
  if (!videoPlayer.duration) return;
  const pct = (videoPlayer.currentTime / videoPlayer.duration) * 100;
  scrubberProgress.style.width = `${pct}%`;
  scrubberThumb.style.left = `${pct}%`;
  timecodeDisplay.textContent = formatTimecode(videoPlayer.currentTime);

  // Sync active round with video playback position
  const currentMs = videoPlayer.currentTime * 1000;
  for (let i = state.chapters.length - 1; i >= 0; i--) {
    if (currentMs >= state.chapters[i].start_ms) {
      if (state.activeRound !== state.chapters[i].round_num) {
        state.activeRound = state.chapters[i].round_num;
        document.getElementById('info-active-round').textContent = `ROUND ${state.activeRound + 1}`;
        document.querySelectorAll('.round-pill').forEach((p, idx) => {
          p.classList.toggle('active', idx === state.activeRound);
        });
      }
      break;
    }
  }

  // Update dynamic minimap in real time as video plays
  if (state.radarMode) {
    renderMinimap();
  }
}

function togglePlay() {
  if (videoPlayer.paused) {
    videoPlayer.play();
    btnPlayPause.textContent = 'PAUSE';
    // Clear telestrator drawings on playback resume
    if (state.telestratorActive) {
      toggleTelestrator();
      clearTelestrator();
    }
  } else {
    videoPlayer.pause();
    btnPlayPause.textContent = 'PLAY';
  }
}

function formatTimecode(sec) {
  const totalMs = Math.round(sec * 1000);
  const hrs = Math.floor(totalMs / 3600000);
  const mins = Math.floor((totalMs % 3600000) / 60000);
  const secs = Math.floor((totalMs % 60000) / 1000);
  const frames = Math.floor((totalMs % 1000) / (1000 / 60)); // 60 fps frames
  return `${pad(hrs)}:${pad(mins)}:${pad(secs)}.${pad(frames)}`;
}

function formatTime(sec) {
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${pad(m)}:${pad(s)}`;
}

function pad(num) {
  return String(num).padStart(2, '0');
}

// -------------------------------------------------------------
// Event Listeners
// -------------------------------------------------------------
function setupEventListeners() {
  // Global Keyboard Hotkeys
  window.addEventListener('keydown', (e) => {
    // If typing in input, ignore
    if (e.target.tagName === 'INPUT' || e.target.tagName === 'SELECT') return;

    // Undo Hotkey: Ctrl+Z or Cmd+Z
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z') {
      e.preventDefault();
      undoLastTag();
      return;
    }

    // Telestrator Toggle Hotkey: 'T'
    if (e.key.toLowerCase() === 't' && !e.ctrlKey && !e.metaKey) {
      e.preventDefault();
      toggleTelestrator();
      return;
    }

    // 1-9 Hotkey Review Tags
    if (TAG_MAP[e.key]) {
      e.preventDefault();
      logTag(e.key);
      return;
    }

    // Space: Play / Pause
    if (e.code === 'Space') {
      e.preventDefault();
      togglePlay();
      return;
    }

    // Arrow Left / Right: Seek +/- 5s
    if (e.code === 'ArrowLeft') {
      videoPlayer.currentTime = Math.max(0, videoPlayer.currentTime - 5);
    } else if (e.code === 'ArrowRight') {
      videoPlayer.currentTime = Math.min(videoPlayer.duration || 0, videoPlayer.currentTime + 5);
    }
  });

  // Undo button click
  btnUndoTag.addEventListener('click', undoLastTag);

  // Match Selector
  matchSelect.addEventListener('change', (e) => {
    if (e.target.value) {
      loadMatch(e.target.value);
    }
  });

  // Perspective Toggle
  document.getElementById('btn-author-solo').addEventListener('click', (e) => {
    state.authorType = 'solo';
    e.target.classList.add('active');
    document.getElementById('btn-author-coach').classList.remove('active');
  });

  document.getElementById('btn-author-coach').addEventListener('click', (e) => {
    state.authorType = 'coach';
    e.target.classList.add('active');
    document.getElementById('btn-author-solo').classList.remove('active');
  });

  // Video Playback Events
  videoPlayer.addEventListener('timeupdate', updateScrubber);
  videoPlayer.addEventListener('loadedmetadata', () => {
    buildScrubberMarkers();
    updateScrubber();
    resizeTelestratorCanvas();
  });

  btnPlayPause.addEventListener('click', togglePlay);
  btnPrevFrame.addEventListener('click', () => {
    videoPlayer.currentTime = Math.max(0, videoPlayer.currentTime - 5);
  });
  btnNextFrame.addEventListener('click', () => {
    videoPlayer.currentTime = Math.min(videoPlayer.duration || 0, videoPlayer.currentTime + 5);
  });

  btnPrevRound.addEventListener('click', () => {
    if (state.activeRound > 0) {
      selectRound(state.activeRound - 1);
    }
  });
  btnNextRound.addEventListener('click', () => {
    if (state.activeRound < state.chapters.length - 1) {
      selectRound(state.activeRound + 1);
    }
  });

  // Playback Speed Selector
  document.querySelectorAll('.speed-btn').forEach((btn) => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.speed-btn').forEach((b) => b.classList.remove('active'));
      btn.classList.add('active');
      videoPlayer.playbackRate = parseFloat(btn.dataset.speed);
    });
  });

  // Local Video File Upload
  videoFileInput.addEventListener('change', (e) => {
    const file = e.target.files[0];
    if (file) {
      const url = URL.createObjectURL(file);
      videoPlayer.src = url;
      videoPlaceholder.style.display = 'none';
      videoPlayer.play();
    }
  });

  // Scrubber Click
  scrubberContainer.addEventListener('click', (e) => {
    if (!videoPlayer.duration) return;
    const rect = scrubberContainer.getBoundingClientRect();
    const pos = (e.clientX - rect.left) / rect.width;
    videoPlayer.currentTime = pos * videoPlayer.duration;
  });

  // Minimap Live Radar Toggle
  btnRadarMode.addEventListener('click', () => {
    state.radarMode = !state.radarMode;
    btnRadarMode.classList.toggle('active', state.radarMode);
    btnRadarMode.textContent = state.radarMode ? 'LIVE RADAR' : 'STATIC ROUND';
    renderMinimap();
  });

  // Minimap Event Filters
  document.querySelectorAll('.mini-btn[data-filter]').forEach((btn) => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.mini-btn[data-filter]').forEach((b) => b.classList.remove('active'));
      btn.classList.add('active');
      state.minimapFilter = btn.dataset.filter;
      renderMinimap();
    });
  });

  // Minimap Mouse Move & Click
  minimapCanvas.addEventListener('mousemove', (e) => {
    const rect = minimapCanvas.getBoundingClientRect();
    const mx = (e.clientX - rect.left) / rect.width;
    const my = (e.clientY - rect.top) / rect.height;

    // Detect hovered event within 0.04 normalized radius
    const hit = state.events.find((ev) => {
      if (ev.round_number !== state.activeRound || ev.pos_x === null) return false;
      const dx = ev.pos_x - mx;
      const dy = ev.pos_y - my;
      return Math.sqrt(dx * dx + dy * dy) < 0.035;
    });

    if (hit) {
      mapTooltip.style.display = 'block';
      mapTooltip.style.left = `${e.clientX - rect.left + 15}px`;
      mapTooltip.style.top = `${e.clientY - rect.top}px`;
      const weapon = hit.metadata.weapon || '';
      mapTooltip.innerHTML = `<strong>${hit.event_type.toUpperCase()}</strong>: ${weapon} (${formatTime(hit.event_time_ms / 1000)})`;
    } else {
      mapTooltip.style.display = 'none';
    }
  });

  minimapCanvas.addEventListener('mouseleave', () => {
    mapTooltip.style.display = 'none';
  });

  minimapCanvas.addEventListener('click', (e) => {
    const rect = minimapCanvas.getBoundingClientRect();
    const mx = (e.clientX - rect.left) / rect.width;
    const my = (e.clientY - rect.top) / rect.height;

    const hit = state.events.find((ev) => {
      if (ev.round_number !== state.activeRound || ev.pos_x === null) return false;
      const dx = ev.pos_x - mx;
      const dy = ev.pos_y - my;
      return Math.sqrt(dx * dx + dy * dy) < 0.035;
    });

    if (hit) {
      seekToEventWithPreRoll(hit.event_time_ms);
    }
  });

  // Tag Grid Card Clicks
  document.querySelectorAll('.tag-card').forEach((card) => {
    card.addEventListener('click', () => {
      logTag(card.dataset.key);
    });
  });
}

// Start application
window.addEventListener('DOMContentLoaded', init);
