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
  showTrails: true, // true: render movement trajectories & rotation paths
  mapImage: new Image(),
  mapLoaded: false,
  hoveredEvent: null,

  // Multi-Match Heatmap Aggregate State
  viewMode: 'match', // 'match' or 'aggregate'
  aggMap: 'Ascent',
  aggSide: 'all', // 'all', 'attack', 'defense'
  aggType: 'death', // 'death', 'kill'
  heatStyle: 'gradient', // 'gradient' or 'points'
  aggregateData: null,
  activeHotspotId: null,
  availableMaps: [],

  // Undo Tag Buffer Stack
  tagHistoryStack: [], // Array of { tag_id, name }

  // Telestrator State
  telestratorActive: false,
  teleTool: 'pen', // 'pen', 'arrow', 'circle', 'cone'
  teleColor: '#ff4655',
  isDrawing: false,
  drawStartX: 0,
  drawStartY: 0,
  savedCanvasImage: null,

  // Perspective Diff & Cognitive Blindspots State
  perspectiveDiff: null,
  diffFilter: 'blindspots',

  // Practice Drills State
  trainingRoutine: null,

  // OBS Studio & Automation State
  obsStatus: {
    connected: false,
    recording: false,
    duration_seconds: 0.0,
    output_path: '',
    game_state: 'DISCONNECTED',
  },
  obsPollInterval: null,
};

// DOM Elements
const matchSelect = document.getElementById('match-select');
const videoPlayer = document.getElementById('video-player');
const videoWrapper = document.getElementById('video-wrapper');
const videoPlaceholder = document.getElementById('video-placeholder');
const videoFileInput = document.getElementById('video-file-input');
const obsHudPill = document.getElementById('obs-hud-pill');
const obsText = document.getElementById('obs-text');
const btnObsSettings = document.getElementById('btn-obs-settings');
const obsModal = document.getElementById('obs-modal');
const btnCloseObs = document.getElementById('btn-close-obs');
const obsModalDot = document.getElementById('obs-modal-dot');
const obsModalStatusText = document.getElementById('obs-modal-status-text');
const obsModalModeBadge = document.getElementById('obs-modal-mode-badge');
const btnObsModeMock = document.getElementById('btn-obs-mode-mock');
const btnObsModeLive = document.getElementById('btn-obs-mode-live');
const obsLiveFields = document.getElementById('obs-live-fields');
const obsHostInput = document.getElementById('obs-host-input');
const obsPortInput = document.getElementById('obs-port-input');
const obsPasswordInput = document.getElementById('obs-password-input');
const btnToggleAutoCapture = document.getElementById('btn-toggle-auto-capture');
const obsTestFeedback = document.getElementById('obs-test-feedback');
const btnTestObs = document.getElementById('btn-test-obs');
const btnSaveObs = document.getElementById('btn-save-obs');

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
const btnToggleTrails = document.getElementById('btn-toggle-trails');

// Multi-Match Aggregate DOM Elements
const btnViewMatch = document.getElementById('btn-view-match');
const btnViewAggregate = document.getElementById('btn-view-aggregate');
const matchMinimapToggles = document.getElementById('match-minimap-toggles');
const aggControlsBar = document.getElementById('agg-controls-bar');
const aggMapSelect = document.getElementById('agg-map-select');
const btnHeatGradient = document.getElementById('btn-heat-gradient');
const matchMinimapLegend = document.getElementById('match-minimap-legend');
const aggMinimapLegend = document.getElementById('agg-minimap-legend');
const aggHotspotsContainer = document.getElementById('agg-hotspots-container');
const aggClusterCount = document.getElementById('agg-cluster-count');
const aggMatchesBadge = document.getElementById('agg-matches-badge');
const aggInsightsBanner = document.getElementById('agg-insights-banner');
const hotspotsList = document.getElementById('hotspots-list');

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

// Perspective Diff DOM Elements
const btnOpenDiff = document.getElementById('btn-open-diff');
const diffModal = document.getElementById('diff-modal');
const btnCloseDiff = document.getElementById('btn-close-diff');
const diffKpiGrid = document.getElementById('diff-kpi-grid');
const diffCategoryGrid = document.getElementById('diff-category-grid');
const diffCardsContainer = document.getElementById('diff-cards-container');
const diffTakeawaysList = document.getElementById('diff-takeaways-list');

// Practice Drills DOM Elements
const btnOpenDrills = document.getElementById('btn-open-drills');
const drillsModal = document.getElementById('drills-modal');
const btnCloseDrills = document.getElementById('btn-close-drills');
const btnCopyDrills = document.getElementById('btn-copy-drills');
const btnDownloadAimlab = document.getElementById('btn-download-aimlab');
const drillsSummaryBanner = document.getElementById('drills-summary-banner');
const drillsListContainer = document.getElementById('drills-list-container');

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
  setupAggregateControls();
  setupObsControls();
  await loadAvailableMaps();
  await loadMatchList();

  // Poll OBS WebSocket status
  await pollObsStatus();
  state.obsPollInterval = setInterval(pollObsStatus, 3000);
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

    // 4. Fetch tags, perspective diff & practice drills
    await loadTags();
    loadPerspectiveDiff(matchId);
    loadTrainingRoutine(matchId);

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

// -------------------------------------------------------------
// Valorant Map Projection Calibration & Coordinate Conversion
// -------------------------------------------------------------
const MAP_CONFIG = {
  Ascent: { xMultiplier: 0.00007, yMultiplier: -0.00007, xScalar: 0.813895, yScalar: 0.573242 },
  Split: { xMultiplier: 0.000078, yMultiplier: -0.000078, xScalar: 0.842188, yScalar: 0.697578 },
  Fracture: { xMultiplier: 0.000078, yMultiplier: -0.000078, xScalar: 0.556952, yScalar: 1.155886 },
  Bind: { xMultiplier: 0.000059, yMultiplier: -0.000059, xScalar: 0.576941, yScalar: 0.967566 },
  Breeze: { xMultiplier: 0.00007, yMultiplier: -0.00007, xScalar: 0.465123, yScalar: 0.833078 },
  Abyss: { xMultiplier: 0.000081, yMultiplier: -0.000081, xScalar: 0.5, yScalar: 0.5 },
  Lotus: { xMultiplier: 0.000072, yMultiplier: -0.000072, xScalar: 0.454789, yScalar: 0.917752 },
  Sunset: { xMultiplier: 0.000078, yMultiplier: -0.000078, xScalar: 0.5, yScalar: 0.515625 },
  Pearl: { xMultiplier: 0.000078, yMultiplier: -0.000078, xScalar: 0.480469, yScalar: 0.916016 },
  Icebox: { xMultiplier: 0.000072, yMultiplier: -0.000072, xScalar: 0.460214, yScalar: 0.304687 },
  Haven: { xMultiplier: 0.000075, yMultiplier: -0.000075, xScalar: 1.09345, yScalar: 0.642728 },
};

function worldToCanvasCoords(gameX, gameY, canvasWidth, canvasHeight, mapName = 'Ascent') {
  const normKey = Object.keys(MAP_CONFIG).find((k) => k.toLowerCase() === (mapName || 'ascent').toLowerCase()) || 'Ascent';
  const cfg = MAP_CONFIG[normKey];
  // Note the axis flip: Unreal Engine / Valorant API Y drives canvas X, API X drives canvas Y
  const normX = gameY * cfg.xMultiplier + cfg.xScalar;
  const normY = gameX * cfg.yMultiplier + cfg.yScalar;

  return {
    x: normX * canvasWidth,
    y: normY * canvasHeight,
    normX,
    normY,
  };
}

function getEventNormCoords(ev) {
  if (!ev || ev.pos_x === null || ev.pos_y === null) return { x: 0, y: 0 };
  if (Math.abs(ev.pos_x) > 2 || Math.abs(ev.pos_y) > 2) {
    const activeMap = state.matchMetadata ? getMapNameFromPath(state.matchMetadata.map_id) : 'Ascent';
    const pt = worldToCanvasCoords(ev.pos_x, ev.pos_y, 1, 1, activeMap);
    return { x: pt.normX, y: pt.normY };
  }
  return { x: ev.pos_x, y: ev.pos_y };
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
// -3s Pre-Roll Event Seek & Auto-Play
// -------------------------------------------------------------
function seekToEventWithPreRoll(eventTimeMs, bufferSeconds = 3.0) {
  const targetSec = Math.max(0, (eventTimeMs - bufferSeconds * 1000) / 1000);
  videoPlayer.currentTime = targetSec;

  if (videoPlayer.duration && !isNaN(videoPlayer.duration)) {
    videoPlayer.play().catch(() => {});
    btnPlayPause.textContent = 'PAUSE';
  } else {
    // Virtual scrub fallback when running review without an offline video asset
    timecodeDisplay.textContent = formatTimecode(targetSec);
    const pct = videoPlayer.duration ? (targetSec / videoPlayer.duration) * 100 : 0;
    if (scrubberProgress) scrubberProgress.style.width = `${pct}%`;
    if (scrubberThumb) scrubberThumb.style.left = `${pct}%`;
  }

  // Refresh dynamic radar
  if (state.radarMode) {
    renderMinimap();
  }
  showToast(`Scrubbed to ${formatTime(targetSec)} (-${bufferSeconds}s pre-roll)`);
}

// -------------------------------------------------------------
// -------------------------------------------------------------
// Round Navigation & Events Feed
// -------------------------------------------------------------
function formatRelativeTime(ms, startMs) {
  const diffSec = Math.max(0, Math.floor((ms - startMs) / 1000));
  const m = Math.floor(diffSec / 60);
  const s = diffSec % 60;
  return `+${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
}

function buildRoundPills() {
  roundPills.innerHTML = '';
  const roundDropdown = document.getElementById('round-select-dropdown');
  if (roundDropdown) {
    roundDropdown.innerHTML = '';
  }

  state.chapters.forEach((ch, idx) => {
    // Round Pill
    const pill = document.createElement('button');
    pill.className = `round-pill ${idx === state.activeRound ? 'active' : ''}`;
    pill.textContent = `R${ch.round_num + 1}`;
    pill.title = ch.comment || `Round ${ch.round_num + 1}`;
    pill.dataset.round = ch.round_num;
    pill.addEventListener('click', () => selectRound(ch.round_num));
    roundPills.appendChild(pill);

    // Dropdown Option for rapid jumper
    if (roundDropdown) {
      const opt = document.createElement('option');
      opt.value = ch.round_num;
      opt.textContent = `Round ${ch.round_num + 1}`;
      if (idx === state.activeRound) opt.selected = true;
      roundDropdown.appendChild(opt);
    }
  });

  if (roundDropdown && !roundDropdown.dataset.listenerAttached) {
    roundDropdown.dataset.listenerAttached = 'true';
    roundDropdown.addEventListener('change', (e) => {
      selectRound(parseInt(e.target.value, 10));
    });
  }
}

function selectRound(roundNum, shouldSeek = true) {
  state.activeRound = roundNum;
  const activeRoundLabel = document.getElementById('info-active-round');
  if (activeRoundLabel) activeRoundLabel.textContent = `ROUND ${roundNum + 1}`;

  const feedRoundLabel = document.getElementById('feed-round-label');
  if (feedRoundLabel) feedRoundLabel.textContent = `ROUND ${roundNum + 1}`;

  // Sync dropdown selector
  const roundDropdown = document.getElementById('round-select-dropdown');
  if (roundDropdown && roundDropdown.value !== String(roundNum)) {
    roundDropdown.value = String(roundNum);
  }

  // Update round pills highlight and auto-scroll into view
  document.querySelectorAll('.round-pill').forEach((pill, idx) => {
    const isActive = idx === roundNum;
    pill.classList.toggle('active', isActive);
    if (isActive) {
      pill.scrollIntoView({ behavior: 'smooth', block: 'nearest', inline: 'nearest' });
    }
  });

  // Filter events feed for this round
  const roundEvents = state.events.filter((e) => e.round_number === roundNum);
  renderRoundEventsFeed(roundEvents, roundNum);

  // Jump video to round start if user clicked a round pill or dropdown
  if (shouldSeek) {
    const chap = state.chapters.find((c) => c.round_num === roundNum);
    if (chap && videoPlayer.duration) {
      videoPlayer.currentTime = chap.start_ms / 1000;
    }
  }

  // Redraw minimap for active round
  renderMinimap();
}

function renderRoundEventsFeed(events, roundNum) {
  roundEventsList.innerHTML = '';

  const chap = state.chapters.find((c) => c.round_num === roundNum);
  const startEv = events ? events.find((e) => e.event_type === 'round_start') : null;
  const roundStartMs = chap ? chap.start_ms : (startEv ? startEv.event_time_ms : (events && events[0] ? events[0].event_time_ms : 0));

  const items = [];

  // Phase 1: Round Start / Buy Phase
  items.push({
    type: 'phase',
    timeMs: roundStartMs,
    relTime: '+00:00',
    title: 'ROUND START · BUY PHASE',
    badgeText: 'PHASE',
    badgeClass: '',
    itemClass: 'phase-item',
  });

  const sortedEvents = (events || []).slice().sort((a, b) => a.event_time_ms - b.event_time_ms);

  // Phase 2: Action Live / Walls Drop (if combat starts after 20s)
  const firstCombat = sortedEvents.find((e) => e.event_type === 'kill' || e.event_type === 'death');
  if (firstCombat && (firstCombat.event_time_ms - roundStartMs) > 20000) {
    items.push({
      type: 'phase',
      timeMs: roundStartMs + 20000,
      relTime: '+00:20',
      title: 'WALLS DROP · COMBAT ACTIVE',
      badgeText: 'ACTION',
      badgeClass: '',
      itemClass: 'phase-item',
    });
  }

  const firstKillEv = sortedEvents.find((e) => e.event_type === 'kill');
  let lastDeathTime = -999999;

  sortedEvents.forEach((e) => {
    if (e.event_type === 'round_start') return;

    const relTime = formatRelativeTime(e.event_time_ms, roundStartMs);

    if (e.event_type === 'kill') {
      const isAce = e.player_puuid === 'player-ace-001';
      const isFB = (e === firstKillEv);
      const isTrade = (e.event_time_ms - lastDeathTime <= 3000);
      const weapon = e.metadata.weapon || 'Gun';
      const victim = (e.metadata.victim || 'Enemy').replace('player-', '');

      items.push({
        type: 'kill',
        timeMs: e.event_time_ms,
        relTime: relTime,
        title: `${isAce ? 'ACE ELIMINATED' : 'KILL:'} [${weapon}] ➔ ${victim}`,
        badgeText: isFB ? 'FIRST BLOOD' : (isTrade ? 'TRADE' : (isAce ? 'ACE' : '')),
        badgeClass: isFB ? 'fb' : (isTrade ? 'trade' : ''),
        itemClass: 'kill-item',
      });
    } else if (e.event_type === 'death') {
      lastDeathTime = e.event_time_ms;
      const isAce = e.player_puuid === 'player-ace-001';
      if (isAce) {
        const isFD = (firstKillEv && firstKillEv.metadata.victim === 'player-ace-001');
        const killer = (e.metadata.killer || 'Enemy').replace('player-', '');
        const weapon = e.metadata.weapon || 'Gun';

        items.push({
          type: 'death',
          timeMs: e.event_time_ms,
          relTime: relTime,
          title: `ACE ELIMINATED by ${killer} [${weapon}]`,
          badgeText: isFD ? 'FIRST DEATH' : 'DEATH',
          badgeClass: 'fd',
          itemClass: 'death-item',
        });
      }
    } else if (e.event_type === 'plant') {
      const site = e.metadata.site || 'A';
      items.push({
        type: 'plant',
        timeMs: e.event_time_ms,
        relTime: relTime,
        title: `SPIKE PLANTED (Site ${site})`,
        badgeText: 'SPIKE',
        badgeClass: '',
        itemClass: 'plant-item',
      });
    } else if (e.event_type === 'defuse') {
      items.push({
        type: 'defuse',
        timeMs: e.event_time_ms,
        relTime: relTime,
        title: `SPIKE DEFUSED`,
        badgeText: 'DEFUSE',
        badgeClass: '',
        itemClass: 'defuse-item',
      });
    } else if (e.event_type === 'round_end') {
      const team = e.metadata.winning_team || '';
      const result = e.metadata.round_result || 'Round Concluded';
      items.push({
        type: 'end',
        timeMs: e.event_time_ms,
        relTime: relTime,
        title: `ROUND END · ${team ? `${team} Won` : 'Completed'} (${result})`,
        badgeText: 'ROUND END',
        badgeClass: '',
        itemClass: 'end-item',
      });
    }
  });

  items.sort((a, b) => a.timeMs - b.timeMs);

  if (items.length === 0) {
    roundEventsList.innerHTML = '<div class="feed-empty">No events in this round</div>';
    return;
  }

  items.forEach((item) => {
    const el = document.createElement('div');
    el.className = `feed-item timeline-event-item ${item.itemClass}`;
    el.setAttribute('data-seconds', (item.timeMs / 1000).toFixed(2));
    el.setAttribute('data-event-time', item.timeMs);
    el.innerHTML = `
      <div class="feed-item-left">
        ${item.badgeText ? `<span class="feed-badge ${item.badgeClass}">${item.badgeText}</span>` : ''}
        <span>${item.title}</span>
      </div>
      <div class="feed-time-group">
        <span class="feed-rel-time">${item.relTime}</span>
        <span class="feed-abs-time">${formatTime(item.timeMs / 1000)}</span>
        <button class="event-clip-btn" title="Trim & Download MP4 Clip">✂</button>
      </div>
    `;

    const clipBtn = el.querySelector('.event-clip-btn');
    if (clipBtn) {
      clipBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        const lbl = (item.badgeText || 'event').toLowerCase();
        trimAndDownloadClip(item.timeMs / 1000, lbl, state.activeRound + 1);
      });
    }

    el.addEventListener('click', () => {
      seekToEventWithPreRoll(item.timeMs);
    });
    roundEventsList.appendChild(el);
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

  // If in Multi-Match Aggregate Mode, render aggregated spatial telemetry
  if (state.viewMode === 'aggregate') {
    renderAggregateMinimap(w, h);
    return;
  }


  const currentVideoMs = Math.round((videoPlayer.currentTime || 0) * 1000);

  // 2. Filter events for current view
  const currentEvents = state.events.filter((e) => {
    if (e.round_number !== state.activeRound) return false;
    if (state.minimapFilter === 'kill' && e.event_type !== 'kill') return false;
    if (state.minimapFilter === 'death' && e.event_type !== 'death') return false;
    if (e.pos_x === null || e.pos_y === null) return false;

    // Temporal Live Radar mode check
    if (state.radarMode && (videoPlayer.duration || videoPlayer.currentTime > 0)) {
      return e.event_time_ms <= currentVideoMs;
    }
    return true;
  });

  // 2.5 Draw Movement & Rotation Trajectories
  drawMovementTrajectories(w, h, currentVideoMs);

  // 3. Draw Telemetry Points
  currentEvents.forEach((e) => {
    const coords = getEventNormCoords(e);
    const px = coords.x * w;
    const py = coords.y * h;
    const deltaMs = currentVideoMs - e.event_time_ms;
    const isRecent = state.radarMode && deltaMs >= 0 && deltaMs <= 4000;
    const isPast = state.radarMode && deltaMs > 4000;

    ctx.save();

    // Dim past events so player focus stays on active engagements
    if (isPast) {
      ctx.globalAlpha = 0.4;
    } else {
      ctx.globalAlpha = 1.0;
    }

    // Recent Event Pulsing Radar Shockwave
    if (isRecent) {
      const pulseRatio = (deltaMs % 1000) / 1000;
      const pulseRadius = 10 + pulseRatio * 22;
      ctx.strokeStyle = e.event_type === 'kill' ? `rgba(6, 214, 160, ${1 - pulseRatio})` : `rgba(255, 70, 85, ${1 - pulseRatio})`;
      ctx.lineWidth = 2.5;
      ctx.beginPath();
      ctx.arc(px, py, pulseRadius, 0, Math.PI * 2);
      ctx.stroke();

      // Recent event floating callout pill
      const weapon = e.metadata.weapon || (e.event_type === 'plant' ? 'SPIKE' : '');
      if (weapon) {
        ctx.font = 'bold 10px Rajdhani, sans-serif';
        const textWidth = ctx.measureText(weapon).width;
        ctx.fillStyle = 'rgba(15, 25, 35, 0.85)';
        ctx.fillRect(px - textWidth / 2 - 4, py - 22, textWidth + 8, 14);
        ctx.strokeStyle = e.event_type === 'kill' ? '#06d6a0' : '#ff4655';
        ctx.lineWidth = 1;
        ctx.strokeRect(px - textWidth / 2 - 4, py - 22, textWidth + 8, 14);
        ctx.fillStyle = '#ffffff';
        ctx.textAlign = 'center';
        ctx.fillText(weapon, px, py - 11);
      }
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

function drawMovementTrajectories(w, h, currentVideoMs) {
  if (!state.showTrails) return;

  // 1. Gather all events for active round with valid coordinates
  const roundEvents = state.events
    .filter((e) => e.round_number === state.activeRound && e.pos_x !== null && e.pos_y !== null)
    .sort((a, b) => a.event_time_ms - b.event_time_ms);

  if (roundEvents.length < 2) return;

  const points = roundEvents.map((ev) => {
    const coords = getEventNormCoords(ev);
    return {
      x: coords.x * w,
      y: coords.y * h,
      timeMs: ev.event_time_ms,
      type: ev.event_type,
      metadata: ev.metadata || {},
    };
  });

  const isLive = state.radarMode && (videoPlayer.duration || videoPlayer.currentTime > 0);

  ctx.save();

  // 2. In Live mode, draw upcoming/future rotation path with faint dashed line
  if (isLive) {
    ctx.beginPath();
    ctx.setLineDash([4, 6]);
    ctx.lineWidth = 1.5;
    ctx.strokeStyle = 'rgba(255, 255, 255, 0.16)';
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';

    let started = false;
    for (let i = 0; i < points.length; i++) {
      if (points[i].timeMs >= currentVideoMs || i === 0) {
        if (!started) {
          ctx.moveTo(points[i].x, points[i].y);
          started = true;
        } else {
          ctx.lineTo(points[i].x, points[i].y);
        }
      }
    }
    if (started) {
      ctx.stroke();
    }
    ctx.setLineDash([]);
  }

  // 3. Draw active/traversed trajectory up to current time (or full if not live)
  const traversed = isLive ? points.filter((p) => p.timeMs <= currentVideoMs) : points;

  if (traversed.length >= 2) {
    for (let i = 0; i < traversed.length - 1; i++) {
      const p1 = traversed[i];
      const p2 = traversed[i + 1];

      const grad = ctx.createLinearGradient(p1.x, p1.y, p2.x, p2.y);
      const isLatest = i === traversed.length - 2;
      const alphaStart = 0.35 + (i / traversed.length) * 0.45;
      const alphaEnd = 0.5 + ((i + 1) / traversed.length) * 0.5;

      grad.addColorStop(0, `rgba(0, 245, 212, ${alphaStart})`);
      grad.addColorStop(1, p2.type === 'death' ? `rgba(255, 70, 85, ${alphaEnd})` : `rgba(0, 245, 212, ${alphaEnd})`);

      ctx.beginPath();
      ctx.moveTo(p1.x, p1.y);
      ctx.lineTo(p2.x, p2.y);
      ctx.strokeStyle = grad;
      ctx.lineWidth = isLatest ? 3.5 : 2.5;
      ctx.lineCap = 'round';
      ctx.lineJoin = 'round';
      ctx.shadowColor = 'rgba(0, 245, 212, 0.45)';
      ctx.shadowBlur = 6;
      ctx.stroke();
      ctx.shadowBlur = 0;

      // Draw direction chevron arrow midway along segment
      const dx = p2.x - p1.x;
      const dy = p2.y - p1.y;
      const dist = Math.sqrt(dx * dx + dy * dy);
      if (dist > 18) {
        const midX = (p1.x + p2.x) / 2;
        const midY = (p1.y + p2.y) / 2;
        const angle = Math.atan2(dy, dx);
        const arrowLen = 5;

        ctx.save();
        ctx.fillStyle = `rgba(0, 245, 212, ${alphaEnd})`;
        ctx.beginPath();
        ctx.moveTo(midX + arrowLen * Math.cos(angle), midY + arrowLen * Math.sin(angle));
        ctx.lineTo(midX - arrowLen * Math.cos(angle - Math.PI / 4), midY - arrowLen * Math.sin(angle - Math.PI / 4));
        ctx.lineTo(midX - arrowLen * Math.cos(angle + Math.PI / 4), midY - arrowLen * Math.sin(angle + Math.PI / 4));
        ctx.closePath();
        ctx.fill();
        ctx.restore();
      }
    }
  }

  // 4. Draw Waypoint Nodes
  const nodesToDraw = isLive ? traversed : points;
  nodesToDraw.forEach((pt, idx) => {
    ctx.beginPath();
    ctx.arc(pt.x, pt.y, 3.5, 0, Math.PI * 2);
    if (pt.type === 'kill') {
      ctx.fillStyle = '#06d6a0';
    } else if (pt.type === 'death') {
      ctx.fillStyle = '#ff4655';
    } else if (pt.type === 'plant' || pt.type === 'defuse') {
      ctx.fillStyle = '#ffd166';
    } else {
      ctx.fillStyle = idx === 0 ? '#38bdf8' : '#00f5d4';
    }
    ctx.fill();
    ctx.strokeStyle = '#0b1118';
    ctx.lineWidth = 1;
    ctx.stroke();
  });

  // 5. Active Scrubber Player Puck Indicator (Current Position)
  if (isLive && traversed.length > 0) {
    const head = traversed[traversed.length - 1];
    const roleColor = state.authorType === 'coach' ? '#ffd166' : '#00f5d4';

    // Outer radar ring
    ctx.beginPath();
    ctx.arc(head.x, head.y, 9, 0, Math.PI * 2);
    ctx.strokeStyle = roleColor;
    ctx.lineWidth = 2;
    ctx.shadowColor = roleColor;
    ctx.shadowBlur = 8;
    ctx.stroke();
    ctx.shadowBlur = 0;

    // Inner core
    ctx.beginPath();
    ctx.arc(head.x, head.y, 4, 0, Math.PI * 2);
    ctx.fillStyle = '#ffffff';
    ctx.fill();
  }

  ctx.restore();
}

// -------------------------------------------------------------
// Multi-Match Aggregate Minimap Rendering & Engine
// -------------------------------------------------------------
function renderAggregateMinimap(w, h) {
  if (!state.aggregateData) {
    ctx.fillStyle = '#ece8e1';
    ctx.font = '16px Rajdhani';
    ctx.textAlign = 'center';
    ctx.fillText('Loading Multi-Match Heatmap Telemetry...', w / 2, h / 2);
    return;
  }

  const isDeath = state.aggType === 'death';
  const points = state.aggregateData.points || [];
  const clusters = state.aggregateData.clusters || [];

  // 1. Draw Heat Glow (Smooth Radial Gradients)
  if (state.heatStyle === 'gradient' && points.length > 0) {
    points.forEach((p) => {
      const px = p.norm_x * w;
      const py = p.norm_y * h;
      const grad = ctx.createRadialGradient(px, py, 0, px, py, 34);

      if (isDeath) {
        grad.addColorStop(0, 'rgba(255, 70, 85, 0.45)');
        grad.addColorStop(0.4, 'rgba(255, 120, 0, 0.22)');
        grad.addColorStop(1, 'rgba(255, 200, 0, 0)');
      } else {
        grad.addColorStop(0, 'rgba(6, 214, 160, 0.45)');
        grad.addColorStop(0.4, 'rgba(0, 180, 216, 0.22)');
        grad.addColorStop(1, 'rgba(0, 245, 212, 0)');
      }

      ctx.fillStyle = grad;
      ctx.beginPath();
      ctx.arc(px, py, 34, 0, Math.PI * 2);
      ctx.fill();
    });
  }

  // 2. Draw Individual Event Points
  points.forEach((p) => {
    const px = p.norm_x * w;
    const py = p.norm_y * h;
    ctx.save();
    ctx.fillStyle = isDeath ? 'rgba(255, 70, 85, 0.9)' : 'rgba(6, 214, 160, 0.9)';
    ctx.strokeStyle = '#ffffff';
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.arc(px, py, 3.5, 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();
    ctx.restore();
  });

  // 3. Draw Hotspot Cluster Enclosures & Centroid Badges
  clusters.forEach((c) => {
    const cx = c.center_x * w;
    const cy = c.center_y * h;
    const isSelected = state.activeHotspotId === c.cluster_id;
    const radiusPx = Math.max(26, c.radius * w);

    ctx.save();

    // Outer cluster perimeter ring
    ctx.beginPath();
    ctx.arc(cx, cy, radiusPx, 0, Math.PI * 2);
    if (isSelected) {
      ctx.strokeStyle = '#00f5d4';
      ctx.lineWidth = 3;
      ctx.setLineDash([6, 4]);
      ctx.stroke();

      // Outer glow circle
      ctx.strokeStyle = 'rgba(0, 245, 212, 0.25)';
      ctx.lineWidth = 8;
      ctx.setLineDash([]);
      ctx.stroke();
    } else {
      ctx.strokeStyle = isDeath ? 'rgba(255, 70, 85, 0.7)' : 'rgba(6, 214, 160, 0.7)';
      ctx.lineWidth = 1.5;
      ctx.setLineDash([4, 4]);
      ctx.stroke();
    }

    // Centroid Badge
    ctx.setLineDash([]);
    ctx.beginPath();
    ctx.arc(cx, cy, 12, 0, Math.PI * 2);
    ctx.fillStyle = isSelected ? '#00f5d4' : (isDeath ? '#ff4655' : '#06d6a0');
    ctx.fill();
    ctx.strokeStyle = '#ffffff';
    ctx.lineWidth = 2;
    ctx.stroke();

    // Centroid Text (#1, #2...)
    ctx.fillStyle = isSelected ? '#0b1118' : '#ffffff';
    ctx.font = 'bold 11px Rajdhani';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(`#${c.cluster_id}`, cx, cy);

    // Callout Label Pill
    const labelText = `${c.zone_name.toUpperCase()} (${c.event_count}x • ${c.percentage}%)`;
    ctx.font = 'bold 11px Rajdhani';
    const textWidth = ctx.measureText(labelText).width;
    const pillW = textWidth + 12;
    const pillH = 18;
    const pillX = cx - pillW / 2;
    const pillY = cy - 28;

    ctx.fillStyle = 'rgba(11, 17, 24, 0.9)';
    ctx.strokeStyle = isSelected ? '#00f5d4' : 'rgba(255, 255, 255, 0.35)';
    ctx.lineWidth = 1;
    ctx.fillRect(pillX, pillY, pillW, pillH);
    ctx.strokeRect(pillX, pillY, pillW, pillH);

    ctx.fillStyle = isSelected ? '#00f5d4' : '#ffffff';
    ctx.textBaseline = 'middle';
    ctx.fillText(labelText, cx, pillY + pillH / 2);

    ctx.restore();
  });
}

async function loadAvailableMaps() {
  try {
    const res = await fetch('/api/analytics/maps');
    const maps = await res.json();
    state.availableMaps = maps || [];

    aggMapSelect.innerHTML = '';
    if (state.availableMaps.length === 0) {
      aggMapSelect.innerHTML = '<option value="Ascent">Ascent</option>';
      return;
    }

    state.availableMaps.forEach((m) => {
      const opt = document.createElement('option');
      opt.value = m.map_name;
      opt.textContent = `${m.map_name.toUpperCase()} (${m.match_count} match${m.match_count > 1 ? 'es' : ''})`;
      if (m.map_name.toLowerCase() === state.aggMap.toLowerCase()) {
        opt.selected = true;
      }
      aggMapSelect.appendChild(opt);
    });

    if (state.availableMaps.length > 0) {
      state.aggMap = state.availableMaps[0].map_name;
    }
  } catch (err) {
    console.error('Failed to load available maps:', err);
  }
}

async function loadAggregateHeatmap() {
  try {
    const url = `/api/analytics/heatmap?map=${encodeURIComponent(state.aggMap)}&type=${state.aggType}&side=${state.aggSide}&limit=20`;
    const res = await fetch(url);
    const data = await res.json();
    state.aggregateData = data;
    state.activeHotspotId = null;

    // Load map image asset
    const cleanMapName = state.aggMap.toLowerCase();
    loadMapImage(cleanMapName);

    // Update UI headers & badges
    aggClusterCount.textContent = data.clusters ? data.clusters.length : 0;
    aggMatchesBadge.textContent = `${data.match_count} MATCH${data.match_count === 1 ? '' : 'ES'} (${data.total_events} ${data.event_type.toUpperCase()}S)`;

    // Render insights banner
    if (data.tactical_insights && data.tactical_insights.length > 0) {
      aggInsightsBanner.style.display = 'block';
      aggInsightsBanner.innerHTML = `<strong>TACTICAL FOCUS:</strong> ${data.tactical_insights[0]}`;
    } else {
      aggInsightsBanner.style.display = 'none';
    }

    // Render hotspot list
    renderHotspotCards(data.clusters || []);

    // Re-draw minimap
    renderMinimap();
  } catch (err) {
    console.error('Failed to load aggregate heatmap:', err);
  }
}

function renderHotspotCards(clusters) {
  hotspotsList.innerHTML = '';
  if (!clusters || clusters.length === 0) {
    hotspotsList.innerHTML = '<div class="empty-tags">No concentrated hotspots found for this filter.</div>';
    return;
  }

  clusters.forEach((c) => {
    const card = document.createElement('div');
    card.className = `hotspot-card ${state.activeHotspotId === c.cluster_id ? 'selected' : ''}`;
    card.dataset.clusterId = c.cluster_id;

    const tagsHtml = (c.correlated_tags || [])
      .map((t) => `<span class="hotspot-tag-pill">${t.name} (x${t.count})</span>`)
      .join('');

    card.innerHTML = `
      <div class="hotspot-header">
        <div class="hotspot-title-group">
          <span class="hotspot-badge">#${c.cluster_id}</span>
          <span class="hotspot-zone">${c.zone_name.toUpperCase()}</span>
        </div>
        <div class="hotspot-stats">
          <strong>${c.event_count}</strong> ${state.aggType.toUpperCase()}S (${c.percentage}%)
        </div>
      </div>
      <div class="hotspot-summary">${c.tactical_summary}</div>
      ${tagsHtml ? `<div class="hotspot-tags">${tagsHtml}</div>` : ''}
    `;

    card.addEventListener('click', () => {
      if (state.activeHotspotId === c.cluster_id) {
        state.activeHotspotId = null;
      } else {
        state.activeHotspotId = c.cluster_id;
      }
      document.querySelectorAll('.hotspot-card').forEach((el) => {
        el.classList.toggle('selected', parseInt(el.dataset.clusterId) === state.activeHotspotId);
      });
      renderMinimap();
    });

    hotspotsList.appendChild(card);
  });
}

function setupAggregateControls() {
  btnViewMatch.addEventListener('click', () => {
    state.viewMode = 'match';
    btnViewMatch.classList.add('active');
    btnViewAggregate.classList.remove('active');
    matchMinimapToggles.style.display = 'flex';
    aggControlsBar.style.display = 'none';
    matchMinimapLegend.style.display = 'flex';
    aggMinimapLegend.style.display = 'none';
    aggHotspotsContainer.style.display = 'none';

    if (state.matchMetadata) {
      loadMapImage(getMapNameFromPath(state.matchMetadata.map_id));
    }
    renderMinimap();
  });

  btnViewAggregate.addEventListener('click', () => {
    state.viewMode = 'aggregate';
    btnViewAggregate.classList.add('active');
    btnViewMatch.classList.remove('active');
    matchMinimapToggles.style.display = 'none';
    aggControlsBar.style.display = 'flex';
    matchMinimapLegend.style.display = 'none';
    aggMinimapLegend.style.display = 'flex';
    aggHotspotsContainer.style.display = 'flex';

    loadAggregateHeatmap();
  });

  aggMapSelect.addEventListener('change', (e) => {
    state.aggMap = e.target.value;
    loadAggregateHeatmap();
  });

  document.querySelectorAll('.segment-btn[data-agg-side]').forEach((btn) => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.segment-btn[data-agg-side]').forEach((b) => b.classList.remove('active'));
      btn.classList.add('active');
      state.aggSide = btn.dataset.aggSide;
      loadAggregateHeatmap();
    });
  });

  document.querySelectorAll('.segment-btn[data-agg-type]').forEach((btn) => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.segment-btn[data-agg-type]').forEach((b) => b.classList.remove('active'));
      btn.classList.add('active');
      state.aggType = btn.dataset.aggType;
      loadAggregateHeatmap();
    });
  });

  btnHeatGradient.addEventListener('click', () => {
    state.heatStyle = state.heatStyle === 'gradient' ? 'points' : 'gradient';
    btnHeatGradient.classList.toggle('active', state.heatStyle === 'gradient');
    btnHeatGradient.textContent = state.heatStyle === 'gradient' ? 'HEAT GLOW' : 'POINTS ONLY';
    renderMinimap();
  });
}

// -------------------------------------------------------------
// Hotkey Review Tagging & Undo Stack
// -------------------------------------------------------------

let activeDeleteTimer = null;

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
      state.tagHistoryStack.push({ action: 'create', tag_id: data.tag_id, name: mapping.name });
      showToast(`[${key}] ${mapping.name.replace(/_/g, ' ')} logged (${state.authorType.toUpperCase()})`);
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
    if (last.action === 'delete') {
      // Re-create previously deleted tag
      const res = await fetch(`/api/matches/${state.currentMatchId}/tags`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          timestamp_ms: last.timestamp_ms,
          category: last.category,
          name: last.name,
          author: last.author,
        }),
      });
      if (res.ok) {
        showToast(`Restored tag [${last.name.replace(/_/g, ' ')}]`);
        await loadTags();
      }
    } else {
      // Undo newly created tag
      const res = await fetch(`/api/tags/${last.tag_id}`, { method: 'DELETE' });
      if (res.ok) {
        showToast(`Undid tag [${last.name.replace(/_/g, ' ')}]`);
        await loadTags();
      }
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
    loadPerspectiveDiff(state.currentMatchId);
    loadTrainingRoutine(state.currentMatchId);
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
    item.dataset.time = t.timestamp_ms;
    const cleanName = (t.name || '').replace(/_/g, ' ');

    item.innerHTML = `
      <div class="tag-item-left">
        <span class="tag-badge ${t.author}">${t.author}</span>
        <span class="tag-name" title="${cleanName}">${cleanName}</span>
        <span class="feed-time">${formatTime(t.timestamp_ms / 1000)}</span>
      </div>
      <div class="tag-item-actions">
        <button class="tag-clip-btn" data-time="${t.timestamp_ms / 1000}" data-name="${cleanName}" title="Trim & Download MP4 Clip (-3s/+2s)">✂ CLIP</button>
        <button class="tag-delete-btn" data-id="${t.tag_id}" title="Click to Delete">×</button>
      </div>
    `;

    tagHistoryList.appendChild(item);
  });
}

async function deleteTag(tagId) {
  const tagObj = state.tags.find((t) => t.tag_id === tagId);
  try {
    const res = await fetch(`/api/tags/${tagId}`, { method: 'DELETE' });
    if (res.ok) {
      if (tagObj) {
        state.tagHistoryStack.push({
          action: 'delete',
          tag_id: tagObj.tag_id,
          timestamp_ms: tagObj.timestamp_ms,
          category: tagObj.category || 'Positioning',
          name: tagObj.name,
          author: tagObj.author || state.authorType,
        });
      }
      showToast(`Deleted [${(tagObj?.name || '').replace(/_/g, ' ')}] (Ctrl+Z to Restore)`);
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
  const totalTags = state.tags.length;
  const maxCount = sorted.length > 0 ? sorted[0][1] : 1;

  if (sorted.length === 0) {
    habitBars.innerHTML = '<div class="empty-tags">Log tags to generate habit distribution</div>';
    return;
  }

  sorted.forEach(([name, count]) => {
    const normalizedPct = Math.max(10, Math.round((count / maxCount) * 100));
    const sharePct = totalTags > 0 ? Math.round((count / totalTags) * 100) : 0;
    const tagEntry = Object.values(TAG_MAP).find((t) => t.name === name);
    const category = tagEntry ? tagEntry.category.toLowerCase() : 'positioning';
    const cleanName = name.replace(/_/g, ' ');

    const row = document.createElement('div');
    row.className = 'habit-row';
    row.innerHTML = `
      <div class="habit-header">
        <span title="${cleanName}">${cleanName}</span>
        <div class="habit-stats">
          <span>${count}x</span>
          <span class="habit-share">(${sharePct}%)</span>
        </div>
      </div>
      <div class="habit-bar-bg">
        <div class="habit-bar-fill ${category}" style="width: ${normalizedPct}%"></div>
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
    } else if (btn.id === 'btn-tool-snapshot') {
      btn.addEventListener('click', exportTelestratorSnapshot);
    } else {
      btn.addEventListener('click', () => {
        document.querySelectorAll('.tool-btn').forEach((b) => {
          if (b.id !== 'btn-tool-clear' && b.id !== 'btn-tool-snapshot') b.classList.remove('active');
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
    } else if (state.teleTool === 'cone') {
      teleCtx.putImageData(state.savedCanvasImage, 0, 0);
      drawVisionCone(state.drawStartX, state.drawStartY, currX, currY, state.teleColor);
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

function drawVisionCone(fromx, fromy, tox, toy, color) {
  const dx = tox - fromx;
  const dy = toy - fromy;
  const dist = Math.sqrt(dx * dx + dy * dy);
  if (dist < 5) return;

  const centerAngle = Math.atan2(dy, dx);
  // Tactical vision angle: 45-degree sector coverage (±22.5 deg)
  const halfFov = (22.5 * Math.PI) / 180;
  const startAngle = centerAngle - halfFov;
  const endAngle = centerAngle + halfFov;

  teleCtx.save();

  // 1. Semi-translucent field-of-view sector fill
  teleCtx.beginPath();
  teleCtx.moveTo(fromx, fromy);
  teleCtx.arc(fromx, fromy, dist, startAngle, endAngle);
  teleCtx.closePath();

  teleCtx.globalAlpha = 0.22;
  teleCtx.fillStyle = color;
  teleCtx.fill();

  // 2. Solid boundary sightline rays & outer perimeter arc
  teleCtx.globalAlpha = 0.9;
  teleCtx.strokeStyle = color;
  teleCtx.lineWidth = 2.5;
  teleCtx.lineCap = 'round';
  teleCtx.stroke();

  // 3. Dashed centerline representing crosshair direction / primary focal vector
  teleCtx.beginPath();
  teleCtx.setLineDash([5, 4]);
  teleCtx.lineWidth = 1.5;
  teleCtx.moveTo(fromx, fromy);
  teleCtx.lineTo(tox, toy);
  teleCtx.stroke();

  // 4. Reticle tick mark at aimpoint
  teleCtx.setLineDash([]);
  teleCtx.lineWidth = 2;
  const tickLen = 6;
  const perp = centerAngle + Math.PI / 2;
  teleCtx.beginPath();
  teleCtx.moveTo(tox - tickLen * Math.cos(perp), toy - tickLen * Math.sin(perp));
  teleCtx.lineTo(tox + tickLen * Math.cos(perp), toy + tickLen * Math.sin(perp));
  teleCtx.stroke();

  // 5. Player position anchor dot at cone apex
  teleCtx.beginPath();
  teleCtx.arc(fromx, fromy, 4, 0, Math.PI * 2);
  teleCtx.fillStyle = color;
  teleCtx.fill();

  teleCtx.restore();
}

function exportTelestratorSnapshot() {
  const width = teleCanvas.width || (videoWrapper ? videoWrapper.clientWidth : 1280) || 1280;
  const height = teleCanvas.height || (videoWrapper ? videoWrapper.clientHeight : 720) || 720;

  const offscreen = document.createElement('canvas');
  offscreen.width = width;
  offscreen.height = height;
  const octx = offscreen.getContext('2d');

  // 1. Draw base video frame or tactical placeholder grid
  let hasVideoFrame = false;
  if (videoPlayer && videoPlayer.readyState >= 2 && videoPlayer.videoWidth > 0) {
    try {
      octx.drawImage(videoPlayer, 0, 0, width, height);
      hasVideoFrame = true;
    } catch (e) {
      hasVideoFrame = false;
    }
  }

  if (!hasVideoFrame) {
    octx.fillStyle = '#0f141c';
    octx.fillRect(0, 0, width, height);

    // Subtle tactical background grid
    octx.strokeStyle = 'rgba(255, 255, 255, 0.05)';
    octx.lineWidth = 1;
    for (let x = 0; x < width; x += 40) {
      octx.beginPath();
      octx.moveTo(x, 0);
      octx.lineTo(x, height);
      octx.stroke();
    }
    for (let y = 0; y < height; y += 40) {
      octx.beginPath();
      octx.moveTo(0, y);
      octx.lineTo(width, y);
      octx.stroke();
    }

    // Centered placeholder label
    octx.fillStyle = 'rgba(255, 255, 255, 0.2)';
    octx.font = '700 15px "DIN Next LT Pro", Inter, sans-serif';
    octx.textAlign = 'center';
    octx.fillText('NO VIDEO LOADED // TACTICAL BOARD SNAPSHOT', width / 2, height / 2);
  }

  // 2. Overlay Telestrator Drawing Layer
  octx.drawImage(teleCanvas, 0, 0, width, height);

  // 3. Render Tactical HUD Watermark Banner
  const curTimeSec = videoPlayer && !isNaN(videoPlayer.currentTime) ? videoPlayer.currentTime : 0;
  const timeStr = formatTime(curTimeSec);
  const roundStr = `ROUND ${(state.activeRound || 0) + 1}`;
  const mapStr = (state.matchMetadata && state.matchMetadata.map_name) || 'ASCENT';
  const roleStr = (state.authorType || 'solo').toUpperCase();

  const badgeW = 340;
  const badgeH = 54;
  const badgeX = 20;
  const badgeY = height - badgeH - 20;

  octx.save();
  // Translucent backdrop
  octx.fillStyle = 'rgba(15, 23, 42, 0.88)';
  octx.fillRect(badgeX, badgeY, badgeW, badgeH);

  // Accent border & role accent stripe
  octx.strokeStyle = 'rgba(0, 245, 212, 0.4)';
  octx.lineWidth = 1;
  octx.strokeRect(badgeX, badgeY, badgeW, badgeH);

  octx.fillStyle = roleStr === 'COACH' ? '#ffd166' : '#00f5d4';
  octx.fillRect(badgeX, badgeY, 3, badgeH);

  // Text details
  octx.textAlign = 'left';
  octx.fillStyle = '#00f5d4';
  octx.font = '700 11px "DIN Next LT Pro", Inter, sans-serif';
  octx.fillText('VALLENS // TACTICAL REVIEW SNAPSHOT', badgeX + 12, badgeY + 18);

  octx.fillStyle = '#ece8e1';
  octx.font = '700 13px "DIN Next LT Pro", Inter, sans-serif';
  octx.fillText(`${mapStr} · ${roundStr} · ${timeStr}`, badgeX + 12, badgeY + 38);

  octx.fillStyle = roleStr === 'COACH' ? '#ffd166' : '#94a3b8';
  octx.font = '700 10px "DIN Next LT Pro", Inter, sans-serif';
  octx.textAlign = 'right';
  octx.fillText(`PERSPECTIVE: ${roleStr}`, badgeX + badgeW - 12, badgeY + 38);
  octx.restore();

  // 4. Trigger Instant PNG Download
  try {
    offscreen.toBlob((blob) => {
      if (!blob) {
        showToast('Failed to generate snapshot blob');
        return;
      }
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      const timecodeClean = timeStr.replace(':', 'm') + 's';
      a.download = `ValLens_${mapStr}_R${(state.activeRound || 0) + 1}_${timecodeClean}.png`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      setTimeout(() => URL.revokeObjectURL(url), 1500);
      showToast('Tactical Snapshot Downloaded (PNG)');
    }, 'image/png');
  } catch (err) {
    console.error('Snapshot export error:', err);
    showToast('Failed to export snapshot');
  }
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
        selectRound(state.chapters[i].round_num, false);
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

    // Perspective Toggle Hotkey: 'P'
    if (e.key.toLowerCase() === 'p' && !e.ctrlKey && !e.metaKey) {
      e.preventDefault();
      setPerspective(state.authorType === 'solo' ? 'coach' : 'solo');
      showToast(`Switched perspective to ${state.authorType.toUpperCase()}`);
      return;
    }

    // Clip Hotkey: 'C'
    if (e.key.toLowerCase() === 'c' && !e.ctrlKey && !e.metaKey) {
      e.preventDefault();
      const curTime = videoPlayer && !isNaN(videoPlayer.currentTime) ? videoPlayer.currentTime : 0;
      trimAndDownloadClip(curTime, 'manual_moment', state.activeRound + 1);
      return;
    }

    // Tactical Snapshot Hotkey: 'S'
    if (e.key.toLowerCase() === 's' && !e.ctrlKey && !e.metaKey && !e.altKey) {
      e.preventDefault();
      exportTelestratorSnapshot();
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

  // Undo button clicks (Header and Inline History)
  btnUndoTag.addEventListener('click', undoLastTag);
  const btnUndoInline = document.getElementById('btn-undo-tag-inline');
  if (btnUndoInline) {
    btnUndoInline.addEventListener('click', undoLastTag);
  }

  // Tag History List: Delegation for safe 2-step deletion and timestamp seeking
  tagHistoryList.addEventListener('click', async (e) => {
    const clipBtn = e.target.closest('.tag-clip-btn');
    if (clipBtn) {
      e.stopPropagation();
      const timeSec = parseFloat(clipBtn.dataset.time);
      const name = clipBtn.dataset.name || 'flaw';
      trimAndDownloadClip(timeSec, name, state.activeRound + 1);
      return;
    }

    const deleteBtn = e.target.closest('.tag-delete-btn');
    if (deleteBtn) {
      e.stopPropagation();
      const tagId = parseInt(deleteBtn.dataset.id, 10);
      if (deleteBtn.classList.contains('confirming')) {
        if (activeDeleteTimer) clearTimeout(activeDeleteTimer);
        await deleteTag(tagId);
      } else {
        document.querySelectorAll('.tag-delete-btn.confirming').forEach((b) => {
          b.classList.remove('confirming');
          b.textContent = '×';
        });
        deleteBtn.classList.add('confirming');
        deleteBtn.textContent = 'CONFIRM';
        activeDeleteTimer = setTimeout(() => {
          if (deleteBtn && deleteBtn.classList.contains('confirming')) {
            deleteBtn.classList.remove('confirming');
            deleteBtn.textContent = '×';
          }
        }, 3000);
      }
      return;
    }

    const item = e.target.closest('.tag-item');
    if (item && item.dataset.time) {
      seekToEventWithPreRoll(parseInt(item.dataset.time, 10));
    }
  });

  // Match Selector
  matchSelect.addEventListener('change', (e) => {
    if (e.target.value) {
      loadMatch(e.target.value);
    }
  });

  // Perspective Toggle
  function setPerspective(author) {
    state.authorType = author;
    const btnSolo = document.getElementById('btn-author-solo');
    const btnCoach = document.getElementById('btn-author-coach');
    const tagGridEl = document.getElementById('tag-grid');
    const indicator = document.getElementById('tag-perspective-indicator');

    if (btnSolo && btnCoach) {
      btnSolo.classList.toggle('active', author === 'solo');
      btnCoach.classList.toggle('active', author === 'coach');
    }

    if (tagGridEl) {
      tagGridEl.className = `tag-grid ${author}`;
    }

    if (indicator) {
      indicator.className = `tag-perspective-indicator ${author}`;
      const textSpan = indicator.querySelector('.indicator-text');
      if (textSpan) {
        textSpan.innerHTML = `LOGGING PERSPECTIVE: <strong>${author === 'solo' ? 'SOLO (PLAYER)' : 'COACH'}</strong>`;
      }
    }
  }

  document.getElementById('btn-author-solo').addEventListener('click', () => setPerspective('solo'));
  document.getElementById('btn-author-coach').addEventListener('click', () => setPerspective('coach'));

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

  // Quick Clip Moment Button
  const btnQuickClip = document.getElementById('btn-quick-clip');
  if (btnQuickClip) {
    btnQuickClip.addEventListener('click', () => {
      const curTime = videoPlayer && !isNaN(videoPlayer.currentTime) ? videoPlayer.currentTime : 0;
      trimAndDownloadClip(curTime, 'manual_moment', state.activeRound + 1);
    });
  }

  // Batch Export Flaws Button
  const btnBatchClip = document.getElementById('btn-batch-clip');
  if (btnBatchClip) {
    btnBatchClip.addEventListener('click', batchTrimFlaws);
  }

  // Review Reel Montage Buttons (Header and Side Pane)
  const btnGenMontage = document.getElementById('btn-generate-montage');
  if (btnGenMontage) {
    btnGenMontage.addEventListener('click', () => generateReviewMontage('flaws'));
  }
  const btnMontageSide = document.getElementById('btn-montage-side');
  if (btnMontageSide) {
    btnMontageSide.addEventListener('click', () => generateReviewMontage('flaws'));
  }

  // Local Video File Upload
  videoFileInput.addEventListener('change', async (e) => {
    const file = e.target.files[0];
    if (file) {
      const url = URL.createObjectURL(file);
      videoPlayer.src = url;
      videoPlaceholder.style.display = 'none';
      videoPlayer.play();

      if (state.currentMatchId) {
        await associateMatchVideo(state.currentMatchId, file.name);
        showToast(`Loaded VOD: ${file.name}`);
      }
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

  // Movement & Rotation Trails Toggle
  if (btnToggleTrails) {
    btnToggleTrails.addEventListener('click', () => {
      state.showTrails = !state.showTrails;
      btnToggleTrails.classList.toggle('active', state.showTrails);
      renderMinimap();
      showToast(`Rotation Trails: ${state.showTrails ? 'ON' : 'OFF'}`);
    });
  }

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

    if (state.viewMode === 'aggregate') {
      if (!state.aggregateData) return;
      const clusters = state.aggregateData.clusters || [];
      const hitCluster = clusters.find((c) => Math.hypot(c.center_x - mx, c.center_y - my) < 0.05);

      if (hitCluster) {
        mapTooltip.style.display = 'block';
        mapTooltip.style.left = `${e.clientX - rect.left + 15}px`;
        mapTooltip.style.top = `${e.clientY - rect.top}px`;
        const tags = (hitCluster.correlated_tags || []).map((t) => `${t.name} (x${t.count})`).join(', ');
        mapTooltip.innerHTML = `
          <strong>HOTSPOT #${hitCluster.cluster_id}: ${hitCluster.zone_name.toUpperCase()}</strong><br>
          ${hitCluster.event_count} ${state.aggType.toUpperCase()}S (${hitCluster.percentage}%)<br>
          ${tags ? `<em>Tags: ${tags}</em>` : ''}
        `;
        return;
      }

      const points = state.aggregateData.points || [];
      const hitPt = points.find((p) => Math.hypot(p.norm_x - mx, p.norm_y - my) < 0.03);
      if (hitPt) {
        mapTooltip.style.display = 'block';
        mapTooltip.style.left = `${e.clientX - rect.left + 15}px`;
        mapTooltip.style.top = `${e.clientY - rect.top}px`;
        mapTooltip.innerHTML = `
          <strong>${hitPt.event_type.toUpperCase()}</strong>: Rnd ${hitPt.round_number + 1} (${hitPt.match_id.slice(0, 8)})
        `;
        return;
      }
      mapTooltip.style.display = 'none';
      return;
    }

    // Single-match mode hover
    const hit = state.events.find((ev) => {
      if (ev.round_number !== state.activeRound || ev.pos_x === null) return false;
      const coords = getEventNormCoords(ev);
      const dx = coords.x - mx;
      const dy = coords.y - my;
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

    if (state.viewMode === 'aggregate') {
      if (!state.aggregateData) return;
      const clusters = state.aggregateData.clusters || [];
      const hitCluster = clusters.find((c) => Math.hypot(c.center_x - mx, c.center_y - my) < 0.06);
      if (hitCluster) {
        state.activeHotspotId = state.activeHotspotId === hitCluster.cluster_id ? null : hitCluster.cluster_id;
        document.querySelectorAll('.hotspot-card').forEach((el) => {
          el.classList.toggle('selected', parseInt(el.dataset.clusterId) === state.activeHotspotId);
        });
        const selectedCard = document.querySelector(`.hotspot-card[data-cluster-id="${hitCluster.cluster_id}"]`);
        if (selectedCard) {
          selectedCard.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        }
        renderMinimap();
      }
      return;
    }

    const hit = state.events.find((ev) => {
      if (ev.round_number !== state.activeRound || ev.pos_x === null) return false;
      const coords = getEventNormCoords(ev);
      const dx = coords.x - mx;
      const dy = coords.y - my;
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

  // Account Sync Modal Handlers
  const syncModal = document.getElementById('sync-modal');
  const btnOpenSync = document.getElementById('btn-open-sync');
  const btnCloseModal = document.getElementById('btn-close-modal');
  const btnAutoDetect = document.getElementById('btn-auto-detect');
  const btnDoSync = document.getElementById('btn-do-sync');
  const syncStatus = document.getElementById('sync-status');
  const syncRiotId = document.getElementById('sync-riot-id');
  const syncRegion = document.getElementById('sync-region');
  const syncLimit = document.getElementById('sync-limit');
  const syncApiKey = document.getElementById('sync-api-key');

  if (btnOpenSync) {
    btnOpenSync.addEventListener('click', () => {
      syncModal.style.display = 'flex';
      syncStatus.style.display = 'none';
    });
  }

  if (btnCloseModal) {
    btnCloseModal.addEventListener('click', () => {
      syncModal.style.display = 'none';
    });
  }

  if (btnAutoDetect) {
    btnAutoDetect.addEventListener('click', async () => {
      syncStatus.className = 'sync-status-msg';
      syncStatus.textContent = 'Detecting local Riot Client session...';
      syncStatus.style.display = 'block';
      try {
        const res = await fetch('/api/account/detect');
        const data = await res.json();
        if (data.riot_id) {
          syncRiotId.value = data.riot_id;
          syncStatus.className = 'sync-status-msg success';
          syncStatus.textContent = `Detected Local Account: ${data.riot_id}`;
          syncStatus.dataset.puuid = data.puuid;
        } else {
          syncStatus.className = 'sync-status-msg error';
          syncStatus.textContent = 'Valorant / Riot Client is not currently running locally.';
        }
      } catch (err) {
        syncStatus.className = 'sync-status-msg error';
        syncStatus.textContent = 'No local client detected. Run Valorant or enter your Riot ID.';
      }
    });
  }

  if (btnDoSync) {
    btnDoSync.addEventListener('click', async () => {
      const riotId = syncRiotId.value.trim();
      const region = syncRegion.value;
      const limit = parseInt(syncLimit.value, 10);
      const apiKey = syncApiKey.value.trim();
      const puuid = syncStatus.dataset.puuid;

      if (!riotId && !puuid) {
        syncStatus.className = 'sync-status-msg error';
        syncStatus.textContent = 'Please enter your Riot ID (Name#Tag) or click Auto-Detect.';
        syncStatus.style.display = 'block';
        return;
      }

      syncStatus.className = 'sync-status-msg';
      syncStatus.textContent = 'Importing match history from Riot...';
      syncStatus.style.display = 'block';

      try {
        const res = await fetch('/api/account/sync', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            riot_id: riotId,
            region: region,
            limit: limit,
            api_key: apiKey || null,
            puuid: puuid || null,
          }),
        });

        const result = await res.json();
        if (res.ok) {
          syncStatus.className = 'sync-status-msg success';
          syncStatus.textContent = `Success! Synced ${result.synced_count} competitive matches.`;
          await loadMatchList();
          setTimeout(() => {
            syncModal.style.display = 'none';
          }, 1500);
        } else {
          syncStatus.className = 'sync-status-msg error';
          syncStatus.textContent = `Sync error: ${result.error || 'Check Riot ID and region'}`;
        }
      } catch (err) {
        syncStatus.className = 'sync-status-msg error';
        syncStatus.textContent = `Connection error: ${err.message}`;
      }
    });
  }

  // Agent Profiling Matrix Modal Handlers
  const matrixModal = document.getElementById('matrix-modal');
  const btnOpenMatrix = document.getElementById('btn-open-matrix');
  const btnCloseMatrix = document.getElementById('btn-close-matrix');

  if (btnOpenMatrix) {
    btnOpenMatrix.addEventListener('click', () => {
      matrixModal.style.display = 'flex';
      loadAgentMatrix();
    });
  }

  if (btnCloseMatrix) {
    btnCloseMatrix.addEventListener('click', () => {
      matrixModal.style.display = 'none';
    });
  }

  if (matrixModal) {
    matrixModal.addEventListener('click', (e) => {
      if (e.target === matrixModal) {
        matrixModal.style.display = 'none';
      }
    });
  }

  // Perspective Diff Modal Handlers
  if (btnOpenDiff) {
    btnOpenDiff.addEventListener('click', () => {
      diffModal.style.display = 'flex';
      if (!state.perspectiveDiff && state.currentMatchId) {
        loadPerspectiveDiff(state.currentMatchId);
      } else {
        renderPerspectiveDiffModal();
      }
    });
  }

  if (btnCloseDiff) {
    btnCloseDiff.addEventListener('click', () => {
      diffModal.style.display = 'none';
    });
  }

  if (diffModal) {
    diffModal.addEventListener('click', (e) => {
      if (e.target === diffModal) {
        diffModal.style.display = 'none';
      }
    });
  }

  // Perspective Diff Filter Tabs
  document.querySelectorAll('.diff-tab-btn').forEach((btn) => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.diff-tab-btn').forEach((b) => b.classList.remove('active'));
      btn.classList.add('active');
      state.diffFilter = btn.dataset.tab;
      renderDiffCards();
    });
  });

  // Practice Drills Modal Handlers
  if (btnOpenDrills) {
    btnOpenDrills.addEventListener('click', () => {
      drillsModal.style.display = 'flex';
      if (!state.trainingRoutine && state.currentMatchId) {
        loadTrainingRoutine(state.currentMatchId);
      } else {
        renderTrainingRoutineModal();
      }
    });
  }

  if (btnCloseDrills) {
    btnCloseDrills.addEventListener('click', () => {
      drillsModal.style.display = 'none';
    });
  }

  if (drillsModal) {
    drillsModal.addEventListener('click', (e) => {
      if (e.target === drillsModal) {
        drillsModal.style.display = 'none';
      }
    });
  }

  if (btnCopyDrills) {
    btnCopyDrills.addEventListener('click', () => {
      if (state.trainingRoutine && state.trainingRoutine.markdown_routine) {
        navigator.clipboard.writeText(state.trainingRoutine.markdown_routine).then(() => {
          showToast('Copied Practice Routine Markdown to Clipboard!');
        }).catch(() => {
          showToast('Failed to copy to clipboard.');
        });
      }
    });
  }

  window.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      if (drillsModal && drillsModal.style.display === 'flex') {
        drillsModal.style.display = 'none';
      }
      if (diffModal && diffModal.style.display === 'flex') {
        diffModal.style.display = 'none';
      }
      if (matrixModal && matrixModal.style.display === 'flex') {
        matrixModal.style.display = 'none';
      }
      if (syncModal && syncModal.style.display === 'flex') {
        syncModal.style.display = 'none';
      }
      if (obsModal && obsModal.style.display === 'flex') {
        obsModal.style.display = 'none';
      }
    }
  });
}

/**
 * Fetch and render the cross-agent profiling matrix and role benchmarks.
 */
async function loadAgentMatrix() {
  const kpiGrid = document.getElementById('matrix-kpi-grid');
  const tbody = document.getElementById('matrix-table-body');
  const insightsList = document.getElementById('matrix-insights-list');

  if (tbody) {
    tbody.innerHTML = `<tr><td colspan="10" style="text-align: center; color: var(--text-muted); padding: 30px;">Loading agent matrix data...</td></tr>`;
  }

  try {
    const res = await fetch('/api/analytics/agents');
    if (!res.ok) {
      throw new Error(`Server returned HTTP ${res.status}`);
    }
    const data = await res.json();
    const agents = data.agents || [];

    // 1. Render Top Macro KPI Cards
    if (kpiGrid) {
      const topDuelsAgent = [...agents].sort((a, b) => (b.first_bloods - a.first_bloods) || (b.opening_duel_win_rate - a.opening_duel_win_rate))[0];
      const highestKdAgent = [...agents].sort((a, b) => b.kd_ratio - a.kd_ratio)[0];
      const roleCount = Object.keys(data.role_breakdown || {}).length;

      kpiGrid.innerHTML = `
        <div class="matrix-kpi-card">
          <div class="matrix-kpi-label">TOTAL AGENTS PLAYED</div>
          <div class="matrix-kpi-val">${agents.length} <span style="font-size:16px; font-weight:normal; color:var(--text-muted);">Agents</span></div>
          <div class="matrix-kpi-sub">${data.total_matches || 0} Matches · ${data.total_rounds || 0} Rounds Analyzed</div>
        </div>
        <div class="matrix-kpi-card cyan">
          <div class="matrix-kpi-label">TOP OPENING DUELIST</div>
          <div class="matrix-kpi-val">${topDuelsAgent ? topDuelsAgent.agent_name : 'N/A'}</div>
          <div class="matrix-kpi-sub">${topDuelsAgent ? `${topDuelsAgent.opening_duel_win_rate.toFixed(1)}% OD Win (${topDuelsAgent.first_bloods} First Bloods)` : 'No duels recorded'}</div>
        </div>
        <div class="matrix-kpi-card purple">
          <div class="matrix-kpi-label">ROLE VERSATILITY</div>
          <div class="matrix-kpi-val">${roleCount} / 4 <span style="font-size:16px; font-weight:normal; color:var(--text-muted);">Roles</span></div>
          <div class="matrix-kpi-sub">${Object.keys(data.role_breakdown || {}).join(', ') || 'None'}</div>
        </div>
        <div class="matrix-kpi-card">
          <div class="matrix-kpi-label">PEAK COMBAT RATING</div>
          <div class="matrix-kpi-val" style="color: #06d6a0;">${highestKdAgent ? `${highestKdAgent.kd_ratio.toFixed(2)} KD` : 'N/A'}</div>
          <div class="matrix-kpi-sub">${highestKdAgent ? `${highestKdAgent.agent_name} (${highestKdAgent.kills}K / ${highestKdAgent.deaths}D)` : 'No combat events'}</div>
        </div>
      `;
    }

    // 2. Render Agent Matrix Table Rows
    if (tbody) {
      if (agents.length === 0) {
        tbody.innerHTML = `<tr><td colspan="10" style="text-align: center; color: var(--text-muted); padding: 30px;">No agent data found. Play or sync matches to populate matrix.</td></tr>`;
      } else {
        tbody.innerHTML = agents.map(agent => {
          const roleClass = (agent.role || 'duelist').toLowerCase();
          const flawsHtml = (agent.top_flaws && agent.top_flaws.length > 0)
            ? agent.top_flaws.map(f => {
                const name = (f.name || f.flaw_name || '').replace(/_/g, ' ');
                return `<span class="tag-pill flaw" title="${name}: ${f.count}x (${f.percentage || 0}%)">${name} <span style="opacity:0.7">(${f.count})</span></span>`;
              }).join('')
            : '<span style="color: var(--text-dim); font-size: 11px;">None logged</span>';

          const kdColor = agent.kd_ratio >= 1.0 ? '#06d6a0' : '#ff4655';
          const fdColor = agent.first_death_rate > 15 ? '#ff4655' : 'var(--text-main)';
          const tradeColor = agent.trade_rate >= 40 ? '#06d6a0' : 'var(--text-main)';

          return `
            <tr>
              <td>
                <div class="agent-cell">
                  ${agent.display_icon ? `<img class="agent-thumb" src="${agent.display_icon}" alt="${agent.agent_name}" onerror="this.style.display='none'" />` : ''}
                  <span class="agent-name-text">${agent.agent_name}</span>
                </div>
              </td>
              <td><span class="role-badge ${roleClass}">${agent.role}</span></td>
              <td><span><strong>${agent.matches_played}</strong> <span style="color:var(--text-muted); font-size:11px;">(${agent.rounds_played}r)</span></span></td>
              <td><span>${agent.kills} / ${agent.deaths} / ${agent.assists}</span></td>
              <td><strong style="color: ${kdColor}; font-size: 14px;">${agent.kd_ratio.toFixed(2)}</strong></td>
              <td>
                <div class="od-cell">
                  <div class="od-pct-text">${agent.opening_duel_win_rate.toFixed(1)}%</div>
                  <div class="od-bar-bg">
                    <div class="od-bar-fill" style="width: ${Math.min(100, Math.max(0, agent.opening_duel_win_rate))}%"></div>
                  </div>
                  <div style="font-size: 10px; color: var(--text-dim); margin-top: 2px;">${agent.first_bloods} FB / ${agent.first_deaths} FD</div>
                </div>
              </td>
              <td><span style="color: ${fdColor}; font-weight: 600;">${agent.first_death_rate.toFixed(1)}%</span></td>
              <td><span style="color: ${tradeColor}; font-weight: 600;">${agent.trade_rate.toFixed(1)}%</span></td>
              <td><div class="flaw-pill-group">${flawsHtml}</div></td>
              <td><div class="diagnosis-cell">${agent.diagnosis || 'Optimal profile.'}</div></td>
            </tr>
          `;
        }).join('');
      }
    }

    // 3. Render Macro Pool Insights
    if (insightsList) {
      if (data.summary_insights && data.summary_insights.length > 0) {
        insightsList.innerHTML = data.summary_insights
          .map(ins => `<div class="matrix-insight-item">${ins}</div>`)
          .join('');
      } else {
        insightsList.innerHTML = `<div class="matrix-insight-item">No macro pool insights available yet.</div>`;
      }
    }
  } catch (err) {
    if (tbody) {
      tbody.innerHTML = `<tr><td colspan="10" style="text-align: center; color: #ff4655; padding: 25px;">Failed to load agent matrix: ${err.message}</td></tr>`;
    }
  }
}

/**
 * Fetch and render Cognitive Blindspots and Perspective Diff.
 */
async function loadPerspectiveDiff(matchId) {
  if (!matchId) return;
  try {
    const res = await fetch(`/api/matches/${matchId}/perspective-diff`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    state.perspectiveDiff = data;
    renderPerspectiveDiffModal();
  } catch (err) {
    console.error('Failed to load perspective diff:', err);
  }
}

function renderPerspectiveDiffModal() {
  if (!state.perspectiveDiff) return;
  const d = state.perspectiveDiff;

  // 1. Render Top KPI Grid & Gauge
  if (diffKpiGrid) {
    let statusClass = 'moderate';
    if (d.agreement_score >= 0.70) statusClass = 'excellent';
    else if (d.agreement_score < 0.40) statusClass = 'significant';

    diffKpiGrid.innerHTML = `
      <div class="diff-gauge-card">
        <div class="diff-gauge-val">${Math.round(d.agreement_score * 100)}%</div>
        <div class="diff-gauge-lbl">COACH ALIGNMENT</div>
        <div class="diff-status-pill ${statusClass}">${d.alignment_status}</div>
      </div>
      <div class="diff-kpi-card">
        <div class="diff-kpi-val">${d.total_solo_tags}</div>
        <div class="diff-kpi-lbl">SOLO REVIEW TAGS</div>
      </div>
      <div class="diff-kpi-card">
        <div class="diff-kpi-val coach">${d.total_coach_tags}</div>
        <div class="diff-kpi-lbl">COACH OBSERVATIONS</div>
      </div>
      <div class="diff-kpi-card">
        <div class="diff-kpi-val agreed">${d.agreed_count}</div>
        <div class="diff-kpi-lbl">MUTUAL CONSENSUS</div>
      </div>
      <div class="diff-kpi-card">
        <div class="diff-kpi-val blindspot">${d.blindspots_count}</div>
        <div class="diff-kpi-lbl">BLINDSPOTS (MISSED)</div>
      </div>
      <div class="diff-kpi-card">
        <div class="diff-kpi-val selfcrit">${d.self_criticisms_count}</div>
        <div class="diff-kpi-lbl">OVER-CRITICAL TAGS</div>
      </div>
    `;
  }

  // 2. Render Category Divergence Breakdown
  if (diffCategoryGrid) {
    diffCategoryGrid.innerHTML = '';
    (d.category_divergence || []).forEach((c) => {
      let scoreClass = 'moderate';
      if (c.alignment_rate >= 0.70) scoreClass = 'consensus';
      else if (c.blindspots_count >= 2 || (c.coach_count > 0 && c.alignment_rate < 0.40)) scoreClass = 'blindspot';

      const maxVal = Math.max(1, c.solo_count + c.coach_count);
      const agreedPct = Math.round((c.agreed_count / maxVal) * 100);
      const blindspotPct = Math.round((c.blindspots_count / maxVal) * 100);
      const selfCritPct = Math.round((c.self_criticisms_count / maxVal) * 100);

      const el = document.createElement('div');
      el.className = 'diff-cat-card';
      el.innerHTML = `
        <div class="diff-cat-header">
          <span class="diff-cat-name">${c.category.toUpperCase()}</span>
          <span class="diff-cat-score ${scoreClass}">${Math.round(c.alignment_rate * 100)}% ALIGNMENT</span>
        </div>
        <div class="diff-cat-stats-row">
          <span>Solo: ${c.solo_count} · Coach: ${c.coach_count}</span>
          <span style="color: ${c.blindspots_count > 0 ? '#ff4655' : 'var(--text-muted)'}; font-weight: 600;">
            ${c.blindspots_count} Blindspot${c.blindspots_count === 1 ? '' : 's'}
          </span>
        </div>
        <div class="diff-cat-bar-track">
          <div class="diff-cat-bar-fill" style="width: ${agreedPct}%; background: #06d6a0;" title="Consensus: ${c.agreed_count}"></div>
          <div class="diff-cat-bar-fill" style="width: ${blindspotPct}%; background: #ff4655;" title="Blindspots: ${c.blindspots_count}"></div>
          <div class="diff-cat-bar-fill" style="width: ${selfCritPct}%; background: #00f5d4;" title="Self-Criticisms: ${c.self_criticisms_count}"></div>
        </div>
      `;
      diffCategoryGrid.appendChild(el);
    });
  }

  // 3. Render Filtered Item Cards
  renderDiffCards();

  // 4. Render Executive Takeaways
  if (diffTakeawaysList) {
    diffTakeawaysList.innerHTML = '';
    (d.executive_takeaways || []).forEach((t) => {
      const item = document.createElement('div');
      item.className = 'diff-takeaway-item';
      item.textContent = t;
      diffTakeawaysList.appendChild(item);
    });
  }
}

function renderDiffCards() {
  if (!diffCardsContainer || !state.perspectiveDiff) return;
  diffCardsContainer.innerHTML = '';
  const d = state.perspectiveDiff;
  const filter = state.diffFilter;

  let items = [];
  if (filter === 'blindspots') {
    items = (d.blindspots || []).map((b) => ({
      type: 'blindspot',
      timeMs: b.timestamp_ms,
      roundNum: b.round_number,
      formattedTime: b.formatted_time,
      relTime: b.round_rel_time,
      tag: b.tag_name,
      cat: b.tag_category,
      badgeText: 'BLINDSPOT',
      badgeClass: 'blindspot',
      message: b.coaching_directive,
      related: b.related_event,
      severity: b.severity,
    }));
  } else if (filter === 'self_criticisms') {
    items = (d.self_criticisms || []).map((sc) => ({
      type: 'self_criticism',
      timeMs: sc.timestamp_ms,
      roundNum: sc.round_number,
      formattedTime: sc.formatted_time,
      relTime: sc.round_rel_time,
      tag: sc.tag_name,
      cat: sc.tag_category,
      badgeText: 'SELF-CRITICISM',
      badgeClass: 'self_criticism',
      message: sc.evaluation,
      related: sc.related_event,
      severity: 'LOW',
    }));
  } else if (filter === 'agreed') {
    items = (d.agreed_tags || []).map((a) => ({
      type: 'agreed',
      timeMs: a.timestamp_ms,
      roundNum: a.round_number,
      formattedTime: a.formatted_time,
      relTime: a.round_rel_time,
      tag: a.coach_tag_name,
      cat: a.tag_category,
      badgeText: 'CONSENSUS',
      badgeClass: 'agreed',
      message: a.notes,
      related: `Time delta: ${a.time_delta_ms}ms`,
      severity: 'LOW',
    }));
  } else {
    // All timeline pips
    items = (d.timeline_pips || []).map((p) => ({
      type: p.type,
      timeMs: p.timestamp_ms,
      roundNum: p.round_number,
      formattedTime: formatTime(p.timestamp_ms / 1000),
      relTime: '',
      tag: p.label,
      cat: p.category,
      badgeText: p.badge,
      badgeClass: p.type,
      message: `Author: ${p.author.toUpperCase()}`,
      related: null,
      severity: p.severity || 'LOW',
    }));
  }

  if (items.length === 0) {
    diffCardsContainer.innerHTML = `<div class="diff-empty-msg">No ${filter.replace(/_/g, ' ')} recorded for this match.</div>`;
    return;
  }

  items.forEach((item) => {
    const card = document.createElement('div');
    card.className = `diff-item-card ${item.type}`;
    card.innerHTML = `
      <div class="diff-card-top">
        <div class="diff-tag-pill-group">
          <span class="diff-tag-badge ${item.badgeClass}">${item.badgeText}</span>
          <strong style="color: #ece8e1; font-size: 13px;">${item.tag.replace(/_/g, ' ').toUpperCase()}</strong>
          <span class="diff-cat-pill">${item.cat}</span>
        </div>
        <div class="diff-meta-group">
          <button class="diff-clip-btn" title="Trim & Download MP4 Clip (-3s/+2s)">✂ CLIP</button>
          <span class="diff-round-pill">R${item.roundNum}</span>
          <span class="diff-time-pill">${item.formattedTime} ${item.relTime ? `(${item.relTime})` : ''}</span>
          <span class="diff-scrub-hint">▶ JUMP (-3s)</span>
        </div>
      </div>
      <div class="diff-card-msg">${item.message}</div>
      ${item.related ? `<div class="diff-related-event">Telemetry context: ${item.related}</div>` : ''}
    `;

    const clipBtn = card.querySelector('.diff-clip-btn');
    if (clipBtn) {
      clipBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        trimAndDownloadClip(item.timeMs / 1000, item.tag, item.roundNum);
      });
    }

    card.addEventListener('click', () => {
      diffModal.style.display = 'none';
      seekToEventWithPreRoll(item.timeMs);
      showToast(`Scrubbed to ${item.badgeText} in Round ${item.roundNum} (${item.tag.replace(/_/g, ' ')})`);
    });

    diffCardsContainer.appendChild(card);
  });
}

/**
 * Fetch and render Actionable Training Routines and Aim Lab Playlist.
 */
async function loadTrainingRoutine(matchId) {
  if (!matchId) return;
  try {
    const res = await fetch(`/api/matches/${matchId}/drills`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    state.trainingRoutine = data;
    if (btnDownloadAimlab) {
      btnDownloadAimlab.href = `/api/matches/${matchId}/drills/aimlab-playlist`;
    }
    renderTrainingRoutineModal();
  } catch (err) {
    console.error('Failed to load training routine:', err);
  }
}

function renderTrainingRoutineModal() {
  if (!state.trainingRoutine) return;
  const r = state.trainingRoutine;

  // 1. Render Summary Banner
  if (drillsSummaryBanner) {
    drillsSummaryBanner.innerHTML = `
      <div class="drills-banner-top">
        <span class="drills-banner-title">PRIORITY PROTOCOL: ${r.primary_focus.toUpperCase()}</span>
        <span class="drills-duration-badge">~${r.total_routine_duration_min} MIN TOTAL WORKOUT</span>
      </div>
      <div class="drills-banner-text">${r.summary}</div>
    `;
  }

  // 2. Render Prescribed Flaw Drill Cards
  if (drillsListContainer) {
    drillsListContainer.innerHTML = '';
    const prescriptions = r.prescriptions || [];

    if (prescriptions.length === 0) {
      drillsListContainer.innerHTML = '<div class="diff-empty-msg">No flaw-specific drills required. Basic fundamentals active.</div>';
      return;
    }

    prescriptions.forEach((p, idx) => {
      const card = document.createElement('div');
      const prioClass = (p.priority || 'medium').toLowerCase();
      card.className = `drill-prescribed-card ${prioClass}`;

      const instructionsHtml = (p.range_exercise.instructions || [])
        .map((inst) => `<li>${inst}</li>`)
        .join('');

      let aimlabHtml = '';
      if (p.aim_trainer_scenarios && p.aim_trainer_scenarios.length > 0) {
        aimlabHtml = `
          <div class="drill-section-box">
            <div class="drill-section-title">
              <span>🎯</span> AIM TRAINER BENCHMARKS (AIM LAB / KOVAAKS)
            </div>
            <div class="aimlab-scenarios-grid">
              ${p.aim_trainer_scenarios
                .map(
                  (sc) => `
                <div class="aimlab-scenario-pill">
                  <div class="aimlab-scenario-top">
                    <span class="aimlab-scenario-name">${sc.scenario_name}</span>
                    <span class="aimlab-plays-badge">${sc.recommended_plays}x Plays</span>
                  </div>
                  <div class="aimlab-scenario-meta">
                    <span>Task: ${sc.task_type} (${sc.platform})</span>
                    <strong style="color: #06d6a0;">Target: ${sc.target_score}</strong>
                  </div>
                  <div class="aimlab-notes">${sc.notes}</div>
                </div>
              `
                )
                .join('')}
            </div>
          </div>
        `;
      }

      let mapDrillHtml = '';
      if (p.map_drill) {
        mapDrillHtml = `
          <div class="drill-section-box">
            <div class="drill-section-title">
              <span>🗺️</span> MAP-SPECIFIC DRY-RUN (${p.map_drill.map_name.toUpperCase()} — ${p.map_drill.callout.toUpperCase()})
            </div>
            <div class="drill-range-details">
              <span><strong>Setup:</strong> ${p.map_drill.setup}</span>
              <span><strong>Objective:</strong> ${p.map_drill.objective}</span>
            </div>
            <ul class="drill-instructions-list">
              ${(p.map_drill.drills || []).map((d) => `<li>${d}</li>`).join('')}
            </ul>
          </div>
        `;
      }

      card.innerHTML = `
        <div class="drill-card-header">
          <div class="drill-title-group">
            <span class="drill-prio-badge ${prioClass}">${p.priority} PRIORITY</span>
            <span class="drill-flaw-name">#${idx + 1}. ${p.tag_name.replace(/_/g, ' ').toUpperCase()} PROTOCOL</span>
            <span class="diff-cat-pill">${p.category}</span>
          </div>
          <span class="drill-time-est">⏱️ ~${p.estimated_time_min} Minutes</span>
        </div>

        <!-- Tier 1: The Range Protocol -->
        <div class="drill-section-box">
          <div class="drill-section-title">
            <span>⚡</span> TIER 1: THE RANGE (${p.range_exercise.exercise_name.toUpperCase()})
          </div>
          <div class="drill-range-details">
            <span><strong>Weapon:</strong> ${p.range_exercise.weapon}</span>
            <span><strong>Mode:</strong> ${p.range_exercise.target_mode}</span>
            <span><strong>Armor:</strong> ${p.range_exercise.armor_setting}</span>
            <span><strong>Duration:</strong> ${p.range_exercise.duration_minutes} min</span>
          </div>
          <ul class="drill-instructions-list">
            ${instructionsHtml}
          </ul>
          <div class="drill-cue-box">
            <strong>Coaching Cue:</strong> "${p.range_exercise.coaching_cue}"
          </div>
        </div>

        <!-- Tier 2: Aim Trainer Scenarios -->
        ${aimlabHtml}

        <!-- Tier 3: Map Specific Dry Run -->
        ${mapDrillHtml}
      `;

      drillsListContainer.appendChild(card);
    });
  }
}

// -------------------------------------------------------------
// Video Moment Clip Trimming Engine (FFmpeg)
// -------------------------------------------------------------
/**
 * Trim a match moment using the backend FFmpeg engine and trigger browser download.
 */
async function trimAndDownloadClip(timestampSeconds, label = 'moment', roundNumber = null, preRoll = 3.0, postRoll = 2.0) {
  if (!state.currentMatchId) {
    showToast('No match currently selected');
    return;
  }

  const cleanLabel = (label || 'moment').replace(/_/g, ' ');
  showToast(`Trimming clip: ${cleanLabel}...`);

  try {
    const res = await fetch(`/api/matches/${state.currentMatchId}/trim`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        timestamp_seconds: timestampSeconds,
        pre_roll: preRoll,
        post_roll: postRoll,
        label: label,
        round_number: roundNumber,
      }),
    });

    if (!res.ok) {
      const err = await res.json();
      showToast(`Clip error: ${err.error || 'Failed'}`);
      return;
    }

    const data = await res.json();
    const clip = data.clip;

    // Trigger instant browser download
    const dlLink = document.createElement('a');
    dlLink.href = clip.download_url;
    dlLink.download = clip.filename;
    document.body.appendChild(dlLink);
    dlLink.click();
    document.body.removeChild(dlLink);

    showToast(`Clip exported: ${clip.filename}`);
  } catch (err) {
    console.error('Trimming error:', err);
    showToast('Failed to export clip');
  }
}

/**
 * Batch export clips for all logged flaw tags in the match.
 */
async function batchTrimFlaws() {
  if (!state.currentMatchId) {
    showToast('No match currently selected');
    return;
  }

  if (state.tags.length === 0) {
    showToast('No tags to export. Tag flaws first [1-9].');
    return;
  }

  showToast(`Batch trimming ${state.tags.length} flaw clips...`);

  try {
    const res = await fetch(`/api/matches/${state.currentMatchId}/trim-all-flaws`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ pre_roll: 3.0, post_roll: 2.0 }),
    });

    if (!res.ok) {
      const err = await res.json();
      showToast(`Batch error: ${err.error || 'Failed'}`);
      return;
    }

    const data = await res.json();
    showToast(`Exported ${data.count} clips to data/clips!`);

    // Automatically trigger download for first clip
    if (data.clips && data.clips.length > 0) {
      const dlLink = document.createElement('a');
      dlLink.href = data.clips[0].download_url;
      dlLink.download = data.clips[0].filename;
      document.body.appendChild(dlLink);
      dlLink.click();
      document.body.removeChild(dlLink);
    }
  } catch (err) {
    console.error('Batch trimming error:', err);
    showToast('Failed to batch trim clips');
  }
}

/**
 * Compile all flaws, blindspots, or key moments into a continuous review montage MP4.
 */
async function generateReviewMontage(filterType = 'flaws') {
  if (!state.currentMatchId) {
    showToast('No match currently selected');
    return;
  }

  showToast('Compiling Review Reel with FFmpeg... (Merging moments)');

  try {
    const res = await fetch(`/api/matches/${state.currentMatchId}/montage`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        filter_type: filterType,
        pre_roll: 3.0,
        post_roll: 2.0,
      }),
    });

    if (!res.ok) {
      const err = await res.json();
      showToast(`Montage error: ${err.error || 'Failed'}`);
      return;
    }

    const data = await res.json();
    const montage = data.montage;

    // Trigger instant browser download
    const dlLink = document.createElement('a');
    dlLink.href = montage.download_url;
    dlLink.download = montage.filename;
    document.body.appendChild(dlLink);
    dlLink.click();
    document.body.removeChild(dlLink);

    // Offer to play directly in VOD player
    if (confirm(`🎬 Review Reel Ready! (${montage.segments_count} moments • ${montage.total_duration_seconds}s)\n\nLoad and play this review reel in the VOD player now?`)) {
      videoPlayer.src = montage.download_url;
      videoPlaceholder.style.display = 'none';
      videoPlayer.play();
    }

    showToast(`Review Reel Ready: ${montage.filename} (${montage.total_duration_seconds}s)`);
  } catch (err) {
    console.error('Montage compilation error:', err);
    showToast('Failed to compile review reel');
  }
}

// -------------------------------------------------------------
// OBS WebSocket HUD & Recording Automation
// -------------------------------------------------------------
let currentObsMode = 'mock';

function setupObsControls() {
  if (obsHudPill) {
    obsHudPill.addEventListener('click', async () => {
      await toggleObsRecording();
    });
  }

  if (btnObsSettings) {
    btnObsSettings.addEventListener('click', () => {
      openObsModal();
    });
  }

  if (btnCloseObs) {
    btnCloseObs.addEventListener('click', () => {
      closeObsModal();
    });
  }

  if (obsModal) {
    obsModal.addEventListener('click', (e) => {
      if (e.target === obsModal) {
        closeObsModal();
      }
    });
  }

  if (btnObsModeMock) {
    btnObsModeMock.addEventListener('click', () => {
      setObsModeUI('mock');
    });
  }

  if (btnObsModeLive) {
    btnObsModeLive.addEventListener('click', () => {
      setObsModeUI('live');
    });
  }

  if (btnToggleAutoCapture) {
    btnToggleAutoCapture.addEventListener('click', async () => {
      await toggleAutoCapture();
    });
  }

  if (btnTestObs) {
    btnTestObs.addEventListener('click', async () => {
      await testObsConnection();
    });
  }

  if (btnSaveObs) {
    btnSaveObs.addEventListener('click', async () => {
      await saveObsConfig();
    });
  }
}

function setObsModeUI(mode) {
  currentObsMode = mode;
  if (mode === 'live') {
    if (btnObsModeLive) btnObsModeLive.classList.add('active');
    if (btnObsModeMock) btnObsModeMock.classList.remove('active');
    if (obsLiveFields) obsLiveFields.style.display = 'block';
    if (obsModalModeBadge) obsModalModeBadge.textContent = 'LIVE OBS v5';
  } else {
    if (btnObsModeMock) btnObsModeMock.classList.add('active');
    if (btnObsModeLive) btnObsModeLive.classList.remove('active');
    if (obsLiveFields) obsLiveFields.style.display = 'none';
    if (obsModalModeBadge) obsModalModeBadge.textContent = 'MOCK MODE';
  }
}

function closeObsModal() {
  if (obsModal) obsModal.style.display = 'none';
}

function updateAutoCaptureUI(enabled) {
  if (!btnToggleAutoCapture) return;
  if (enabled) {
    btnToggleAutoCapture.classList.add('active');
    btnToggleAutoCapture.textContent = 'AUTO-CAPTURE: ON';
  } else {
    btnToggleAutoCapture.classList.remove('active');
    btnToggleAutoCapture.textContent = 'AUTO-CAPTURE: OFF';
  }
}

function updateObsModalStatusUI(connected, recording) {
  if (!obsModalDot || !obsModalStatusText) return;
  if (connected) {
    obsModalDot.classList.add('connected');
    obsModalStatusText.textContent = recording ? 'RECORDING ACTIVE' : 'CONNECTED & READY';
  } else {
    obsModalDot.classList.remove('connected');
    obsModalStatusText.textContent = 'DISCONNECTED';
  }
}

async function openObsModal() {
  if (!obsModal) return;
  obsModal.style.display = 'flex';
  if (obsTestFeedback) obsTestFeedback.style.display = 'none';

  try {
    const res = await fetch('/api/obs/config');
    if (res.ok) {
      const data = await res.json();
      if (obsHostInput) obsHostInput.value = data.host || '127.0.0.1';
      if (obsPortInput) obsPortInput.value = data.port || 4455;
      if (obsPasswordInput) {
        obsPasswordInput.value = '';
        if (data.has_password) {
          obsPasswordInput.placeholder = '(Saved password configured)';
        } else {
          obsPasswordInput.placeholder = 'Leave blank if no server password';
        }
      }
      setObsModeUI(data.use_mock ? 'mock' : 'live');
      updateAutoCaptureUI(Boolean(data.auto_capture_enabled));
      updateObsModalStatusUI(Boolean(data.connected), Boolean(data.recording));
    }
  } catch (err) {
    console.error('Failed to fetch OBS config:', err);
  }
}

async function testObsConnection() {
  if (!btnTestObs || !obsTestFeedback) return;
  btnTestObs.disabled = true;
  btnTestObs.textContent = 'TESTING...';
  obsTestFeedback.style.display = 'block';
  obsTestFeedback.className = 'obs-test-feedback';
  obsTestFeedback.textContent = 'Attempting WebSocket handshake...';

  const useMock = currentObsMode === 'mock';
  const payload = {
    use_mock: useMock,
    host: obsHostInput ? obsHostInput.value.trim() || '127.0.0.1' : '127.0.0.1',
    port: obsPortInput ? parseInt(obsPortInput.value, 10) || 4455 : 4455,
  };
  if (obsPasswordInput && obsPasswordInput.value.trim().length > 0) {
    payload.password = obsPasswordInput.value.trim();
  }

  try {
    const res = await fetch('/api/obs/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (data.success && data.connected) {
      obsTestFeedback.className = 'obs-test-feedback success';
      obsTestFeedback.textContent = `✓ ${data.message || 'Connected to OBS Studio'}`;
      updateObsModalStatusUI(true, false);
    } else {
      obsTestFeedback.className = 'obs-test-feedback error';
      obsTestFeedback.textContent = `✗ ${data.message || data.error || 'Connection failed'}`;
      updateObsModalStatusUI(false, false);
    }
    await pollObsStatus();
  } catch (err) {
    obsTestFeedback.className = 'obs-test-feedback error';
    obsTestFeedback.textContent = `✗ Connection error: ${err.message}`;
    updateObsModalStatusUI(false, false);
  } finally {
    btnTestObs.disabled = false;
    btnTestObs.textContent = 'TEST CONNECTION';
  }
}

async function saveObsConfig() {
  if (!btnSaveObs) return;
  btnSaveObs.disabled = true;
  btnSaveObs.textContent = 'SAVING...';

  const useMock = currentObsMode === 'mock';
  const payload = {
    use_mock: useMock,
    host: obsHostInput ? obsHostInput.value.trim() || '127.0.0.1' : '127.0.0.1',
    port: obsPortInput ? parseInt(obsPortInput.value, 10) || 4455 : 4455,
  };
  if (obsPasswordInput && obsPasswordInput.value.trim().length > 0) {
    payload.password = obsPasswordInput.value.trim();
  }

  try {
    const res = await fetch('/api/obs/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (data.success) {
      showToast(`OBS Configured (${useMock ? 'Mock Client' : 'Live WebSocket v5'})`);
      closeObsModal();
      await pollObsStatus();
    } else {
      if (obsTestFeedback) {
        obsTestFeedback.style.display = 'block';
        obsTestFeedback.className = 'obs-test-feedback error';
        obsTestFeedback.textContent = `✗ ${data.message || data.error || 'Connection failed'}`;
      }
      showToast(`OBS Connection Failed: ${data.error || 'Check Settings'}`);
    }
  } catch (err) {
    showToast('Failed to save OBS configuration');
  } finally {
    btnSaveObs.disabled = false;
    btnSaveObs.textContent = 'SAVE & CONNECT';
  }
}

async function toggleAutoCapture() {
  try {
    const res = await fetch('/api/obs/auto-capture', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
    });
    if (res.ok) {
      const data = await res.json();
      updateAutoCaptureUI(Boolean(data.auto_capture_active));
      showToast(`Zero-Touch Auto-Capture: ${data.auto_capture_active ? 'ENABLED' : 'DISABLED'}`);
    }
  } catch (err) {
    console.error('Failed to toggle auto-capture:', err);
    showToast('Failed to toggle auto-capture');
  }
}

async function pollObsStatus() {
  if (!obsHudPill || !obsText) return;
  try {
    const res = await fetch('/api/obs/status');
    if (!res.ok) return;
    const data = await res.json();
    state.obsStatus = data;
    updateObsHudUI(data);
  } catch (err) {
    updateObsHudUI({ connected: false, recording: false, duration_seconds: 0, game_state: 'DISCONNECTED' });
  }
}

function updateObsHudUI(data) {
  if (!obsHudPill || !obsText) return;

  if (obsModal && obsModal.style.display !== 'none') {
    updateObsModalStatusUI(Boolean(data.connected), Boolean(data.recording));
  }

  obsHudPill.classList.remove('idle', 'recording', 'ingame', 'disconnected');

  if (!data.connected) {
    obsHudPill.classList.add('disconnected');
    obsText.textContent = 'OBS: OFFLINE';
    obsHudPill.title = 'OBS Studio not connected (Check WebSocket)';
    return;
  }

  if (data.recording) {
    obsHudPill.classList.add('recording');
    const dur = Math.max(0, Math.floor(data.duration_seconds || 0));
    const mins = Math.floor(dur / 60).toString().padStart(2, '0');
    const secs = (dur % 60).toString().padStart(2, '0');
    obsText.textContent = `REC ${mins}:${secs}`;
    obsHudPill.title = `OBS Recording Active (${mins}:${secs}) — Click to Stop & Save`;
    return;
  }

  if (data.game_state === 'INGAME') {
    obsHudPill.classList.add('ingame');
    obsText.textContent = 'GAME: IN-GAME';
    obsHudPill.title = 'Valorant In-Game (OBS Standby) — Click to Record Manual Clip';
    return;
  }

  obsHudPill.classList.add('idle');
  obsText.textContent = 'OBS: IDLE';
  obsHudPill.title = 'OBS Studio Ready — Click to Start Recording';
}

async function toggleObsRecording() {
  try {
    const res = await fetch('/api/obs/record', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action: 'toggle' }),
    });
    if (!res.ok) {
      const errData = await res.json();
      showToast(`OBS Error: ${errData.error || 'Failed'}`);
      return;
    }
    const data = await res.json();

    if (data.action === 'started') {
      showToast('OBS Recording Started');
    } else if (data.action === 'stopped') {
      const outName = data.output_path ? data.output_path.split('/').pop() : 'capture';
      showToast(`OBS Recording Stopped (${outName})`);

      // If a match is active, associate video and load into player if empty
      if (state.currentMatchId && data.output_path) {
        await associateMatchVideo(state.currentMatchId, data.output_path);
        if (!videoPlayer.src || videoPlayer.src === window.location.href || videoPlaceholder.style.display !== 'none') {
          videoPlayer.src = `/api/video?path=${encodeURIComponent(data.output_path)}`;
          videoPlaceholder.style.display = 'none';
        }
      }
    }
    await pollObsStatus();
  } catch (err) {
    console.error('Failed to toggle OBS recording:', err);
    showToast('Failed to toggle OBS recording');
  }
}

async function associateMatchVideo(matchId, videoFilepath) {
  try {
    const res = await fetch(`/api/matches/${matchId}/video`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ video_filepath: videoFilepath }),
    });
    if (res.ok) {
      if (state.matchMetadata) {
        state.matchMetadata.video_filepath = videoFilepath;
      }
    }
  } catch (err) {
    console.error('Failed to associate match video:', err);
  }
}

// Start application
window.addEventListener('DOMContentLoaded', init);
