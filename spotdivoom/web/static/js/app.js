/**
 * SpotDivoom 64 — Web Dashboard & Pixel Simulator
 *
 * Status arrives over a server-sent event stream (/api/events) whenever the daemon reports a
 * change; if the stream drops, the page falls back to polling /api/status.
 */

document.addEventListener('DOMContentLoaded', () => {
  const $ = (id) => document.getElementById(id);

  // Elements
  const matrixCanvas = $('matrixCanvas');
  const ctx = matrixCanvas.getContext('2d');
  const btnModeLed = $('btnModeLed');
  const btnModeSmooth = $('btnModeSmooth');

  // Header Elements
  const headerWeatherIcon = $('headerWeatherIcon');
  const headerTemp = $('headerTemp');
  const headerCity = $('headerCity');
  const headerClock = $('headerClock');
  const pixooStatusDot = $('pixooStatusDot');
  const pixooStatusText = $('pixooStatusText');

  // Hardware Elements
  const brightnessSlider = $('brightnessSlider');
  const brightnessValueDisplay = $('brightnessValueDisplay');
  const presetChips = document.querySelectorAll('.preset-chip');

  // Now Playing Elements
  const playbackBadge = $('playbackBadge');
  const playbackBadgeText = $('playbackBadgeText');
  const equalizerBars = $('equalizerBars');
  const trackCoverImg = $('trackCoverImg');
  const trackTitle = $('trackTitle');
  const trackArtist = $('trackArtist');
  const trackAlbum = $('trackAlbum');
  const trackProgressFill = $('trackProgressFill');
  const trackTimeElapsed = $('trackTimeElapsed');
  const trackTimeTotal = $('trackTimeTotal');
  const btnPlayPause = $('btnPlayPause');
  const btnPrev = $('btnPrev');
  const btnNext = $('btnNext');
  const btnLike = $('btnLike');
  const spotifyNote = $('spotifyNote');

  // Login
  const loginCard = $('loginCard');
  const loginOpenLink = $('loginOpenLink');
  const loginPastedUrl = $('loginPastedUrl');

  // Ambient Elements
  const idleCoverTitle = $('idleCoverTitle');
  const idleWeatherStat = $('idleWeatherStat');

  // Settings Form
  const settingsForm = $('settingsForm');
  const btnSaveSettings = $('btnSaveSettings');
  let serverSettings = null;  // the app's current settings, from the latest status
  let formDirty = false;      // true once the user edits the form, until they save
  btnSaveSettings.disabled = true;  // enabled once the form shows the app's real settings
  const toastContainer = $('toastContainer');

  // State
  let renderMode = 'led'; // 'led' or 'smooth'
  let isDraggingSlider = false;
  let lastFrameVersion = -1;
  let lastStatusAt = 0;
  let playback = null;        // last playback object from the server
  let playbackAt = 0;         // when we received it (for local progress)
  let loginUrlLoaded = false;
  const offscreenImg = new Image();

  // Helper: Toast Notifications
  function showToast(message) {
    const toast = document.createElement('div');
    toast.className = 'toast';
    toast.textContent = message;
    toastContainer.appendChild(toast);
    setTimeout(() => {
      toast.style.opacity = '0';
      setTimeout(() => toast.remove(), 300);
    }, 2800);
  }

  async function postJson(url, body) {
    const res = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body || {}),
    });
    let data = {};
    try { data = await res.json(); } catch (e) {}
    return { ok: res.ok && data.success !== false, data };
  }

  // Format Milliseconds to M:SS
  function formatMs(ms) {
    if (!ms || ms <= 0) return '0:00';
    const totalSecs = Math.floor(ms / 1000);
    const mins = Math.floor(totalSecs / 60);
    const secs = totalSecs % 60;
    return `${mins}:${secs < 10 ? '0' : ''}${secs}`;
  }

  // Weather Condition Icon Mapper
  function getWeatherIcon(code, isDay) {
    if (code === 0) return isDay ? '☀️' : '🌙';
    if (code === 1 || code === 2) return isDay ? '⛅' : '☁️';
    if (code === 3 || code === 45 || code === 48) return '🌫️';
    if (code >= 51 && code <= 67) return '🌧️';
    if (code >= 71 && code <= 86) return '❄️';
    if (code >= 95) return '⛈️';
    return '⛅';
  }

  // ---------- LED simulator ----------

  function drawMatrixFrame() {
    if (!offscreenImg.complete || offscreenImg.naturalWidth === 0) return;

    const width = matrixCanvas.width;
    const height = matrixCanvas.height;
    ctx.clearRect(0, 0, width, height);

    if (renderMode === 'smooth') {
      ctx.imageSmoothingEnabled = true;
      ctx.drawImage(offscreenImg, 0, 0, width, height);
      return;
    }

    // LED Diode Simulation: 64x64 grid
    const tempCanvas = document.createElement('canvas');
    tempCanvas.width = 64;
    tempCanvas.height = 64;
    const tCtx = tempCanvas.getContext('2d');
    tCtx.drawImage(offscreenImg, 0, 0, 64, 64);
    const imgData = tCtx.getImageData(0, 0, 64, 64).data;

    // Background matrix panel
    ctx.fillStyle = '#07090d';
    ctx.fillRect(0, 0, width, height);

    const step = width / 64;
    const radius = (step * 0.78) / 2;

    for (let y = 0; y < 64; y++) {
      for (let x = 0; x < 64; x++) {
        const idx = (y * 64 + x) * 4;
        const r = imgData[idx];
        const g = imgData[idx + 1];
        const b = imgData[idx + 2];

        const cx = x * step + step / 2;
        const cy = y * step + step / 2;

        ctx.beginPath();
        ctx.arc(cx, cy, radius, 0, Math.PI * 2);

        if (r === 0 && g === 0 && b === 0) {
          ctx.fillStyle = '#12151b'; // Dark unlit diode
          ctx.fill();
        } else {
          ctx.fillStyle = `rgb(${r},${g},${b})`;
          ctx.fill();

          // Subtle glossy diode highlight
          ctx.beginPath();
          ctx.arc(cx - radius * 0.25, cy - radius * 0.25, radius * 0.35, 0, Math.PI * 2);
          ctx.fillStyle = 'rgba(255, 255, 255, 0.16)';
          ctx.fill();
        }
      }
    }
  }

  function fetchMatrixFrame() {
    offscreenImg.onload = () => drawMatrixFrame();
    offscreenImg.src = `/api/frame?t=${Date.now()}`;
  }

  btnModeLed.addEventListener('click', () => {
    renderMode = 'led';
    btnModeLed.classList.add('active');
    btnModeSmooth.classList.remove('active');
    drawMatrixFrame();
  });

  btnModeSmooth.addEventListener('click', () => {
    renderMode = 'smooth';
    btnModeSmooth.classList.add('active');
    btnModeLed.classList.remove('active');
    drawMatrixFrame();
  });

  // ---------- Now playing ----------

  function renderProgress() {
    if (!playback) return;
    let progress = playback.progress_ms || 0;
    if (playback.is_playing) progress += Date.now() - playbackAt;
    const total = playback.duration_ms || 0;
    progress = total ? Math.min(progress, total) : progress;
    trackProgressFill.style.width = total ? `${(progress / total) * 100}%` : '0%';
    trackTimeElapsed.textContent = formatMs(progress);
    trackTimeTotal.textContent = formatMs(total);
  }

  function renderPlayback(data) {
    playback = data.playback && data.playback.title ? data.playback : null;
    playbackAt = Date.now();
    const playing = Boolean(playback && playback.is_playing);

    if (playback) {
      playbackBadge.className = `playback-indicator-badge ${playing ? 'playing' : 'paused'}`;
      playbackBadgeText.textContent = playing ? 'Playing' : 'Paused';
      equalizerBars.classList.toggle('animating', playing);
      trackTitle.textContent = playback.title || 'Unknown Title';
      trackArtist.textContent = playback.artist || 'Unknown Artist';
      trackAlbum.textContent = playback.album || '';
      if (playback.image_url && trackCoverImg.src !== playback.image_url) {
        trackCoverImg.src = playback.image_url;
      }
      renderProgress();
    } else {
      playbackBadge.className = 'playback-indicator-badge';
      playbackBadgeText.textContent = 'Idle';
      equalizerBars.classList.remove('animating');
      trackTitle.textContent = 'Nothing playing';
      trackArtist.textContent = 'Showing covers from your Liked Songs';
      trackAlbum.textContent = 'with the time and weather';
      trackProgressFill.style.width = '0%';
      trackTimeElapsed.textContent = '0:00';
      trackTimeTotal.textContent = '0:00';
    }

    // Controls
    const canControl = Boolean(data.daemon && data.spotify && data.spotify.authorized);
    [btnPlayPause, btnPrev, btnNext].forEach((b) => { b.disabled = !canControl; });
    $('iconPlay').hidden = playing;
    $('iconPause').hidden = !playing;
    btnPlayPause.setAttribute('aria-label', playing ? 'Pause' : 'Play');
    btnPlayPause.title = playing ? 'Pause' : 'Play';

    const liked = Boolean(playback && playback.liked);
    btnLike.disabled = !canControl || !playback || playback.liked === null || playback.liked === undefined;
    btnLike.setAttribute('aria-pressed', String(liked));
    const likeLabel = liked ? 'Remove from Liked Songs' : 'Save to Liked Songs';
    btnLike.title = likeLabel;
    btnLike.setAttribute('aria-label', likeLabel);

    // Notes: Spotify outage, night mode
    const notes = [];
    if (data.spotify && data.spotify.error) notes.push(data.spotify.error);
    if (data.night && data.night.active) {
      const labels = { dim: 'dimmed', clock: 'showing the night clock', screen_off: 'off' };
      notes.push(`Night mode: the Pixoo is ${labels[data.night.mode] || 'in night mode'}.`);
    }
    spotifyNote.textContent = notes.join(' ');
    spotifyNote.hidden = notes.length === 0;
  }

  setInterval(renderProgress, 1000);

  async function sendControl(action) {
    const { ok, data } = await postJson(`/api/playback/${action}`);
    if (!ok) showToast(data.error || 'Spotify did not accept that.');
    else if (action === 'like') showToast('Saved to Liked Songs');
    else if (action === 'unlike') showToast('Removed from Liked Songs');
  }

  btnPlayPause.addEventListener('click', () => sendControl('toggle'));
  btnPrev.addEventListener('click', () => sendControl('previous'));
  btnNext.addEventListener('click', () => sendControl('next'));
  btnLike.addEventListener('click', () => {
    sendControl(btnLike.getAttribute('aria-pressed') === 'true' ? 'unlike' : 'like');
  });

  // ---------- Spotify login ----------

  async function loadLoginUrl() {
    if (loginUrlLoaded) return;
    loginUrlLoaded = true;
    try {
      const res = await fetch('/api/auth/status');
      const data = await res.json();
      if (data.authorize_url) loginOpenLink.href = data.authorize_url;
    } catch (e) {
      loginUrlLoaded = false;
    }
  }

  function renderLogin(data) {
    const needsLogin = Boolean(data.spotify && !data.spotify.authorized);
    loginCard.hidden = !needsLogin;
    if (needsLogin) loadLoginUrl();
  }

  $('btnLoginComplete').addEventListener('click', async () => {
    const url = loginPastedUrl.value.trim();
    if (!url) {
      showToast('Paste the address from the page Spotify sent you to.');
      loginPastedUrl.focus();
      return;
    }
    const { ok, data } = await postJson('/api/auth/complete', { url });
    if (!ok) {
      showToast(data.error || 'Login failed. Open the login link again and paste the new address.');
      loginUrlLoaded = false;
      return;
    }
    loginPastedUrl.value = '';
    loginCard.hidden = true;
    showToast('Logged in to Spotify');
    document.dispatchEvent(new CustomEvent('spotdivoom:login'));
    fetchStatus();
  });

  // ---------- Status ----------

  function applyStatus(data) {
    lastStatusAt = Date.now();

    // 1. Header Clock & Weather
    if (data.idle) {
      if (data.idle.time) headerClock.textContent = data.idle.time;
      if (data.idle.weather) {
        const w = data.idle.weather;
        headerWeatherIcon.textContent = getWeatherIcon(w.weather_code, w.is_day);
        headerTemp.textContent = `${w.temperature}${w.unit}`;
        headerCity.textContent = w.city || 'Local Weather';
        idleWeatherStat.textContent = `${w.temperature}${w.unit} in ${w.city || 'Local'}`;
      }
      if (data.idle.current_cover_title) {
        idleCoverTitle.textContent = data.idle.current_cover_title;
      }
    }

    // 2. Hardware Connectivity
    if (data.pixoo) {
      const night = data.night && data.night.active ? ' • Night' : '';
      pixooStatusDot.className = `pill-dot status-dot ${data.pixoo.connected ? 'online' : 'offline'}`;
      pixooStatusText.textContent = `${data.pixoo.connected ? 'Online' : 'Offline'} • ${data.pixoo.ip || 'No IP'}${night}`;

      if (!isDraggingSlider && data.pixoo.brightness !== undefined) {
        brightnessSlider.value = data.pixoo.brightness;
        brightnessValueDisplay.textContent = `${data.pixoo.brightness}%`;
        presetChips.forEach((chip) => {
          chip.classList.toggle('active', parseInt(chip.dataset.val, 10) === data.pixoo.brightness);
        });
      }
    }

    // 3. Playback card, login
    renderPlayback(data);
    renderLogin(data);

    // 4. Simulator: refetch only when the frame changed
    if (data.frame_version !== undefined && data.frame_version !== lastFrameVersion) {
      lastFrameVersion = data.frame_version;
      fetchMatrixFrame();
    }

    // 5. Keep the settings form in step with the app until the user starts editing it
    if (data.settings) {
      serverSettings = data.settings;
      if (!formDirty) {
        populateSettings(data.settings);
        btnSaveSettings.disabled = false;
      }
    }
  }

  async function fetchStatus() {
    try {
      const res = await fetch('/api/status');
      if (res.ok) applyStatus(await res.json());
    } catch (e) {
      console.warn('Status poll error:', e);
    }
  }

  function connectStream() {
    if (!window.EventSource) return;
    const source = new EventSource('/api/events');
    source.onmessage = (event) => {
      try { applyStatus(JSON.parse(event.data)); } catch (e) {}
    };
    // EventSource reconnects on its own; the watchdog below polls in the meantime
  }

  // Watchdog: the stream sends at least every 20s, so poll if it has gone quiet
  setInterval(() => {
    if (Date.now() - lastStatusAt > 25000) fetchStatus();
  }, 5000);

  // ---------- Brightness ----------

  async function setBrightness(val) {
    const { ok } = await postJson('/api/control/brightness', { brightness: val });
    showToast(ok ? `Brightness set to ${val}%` : 'Could not reach the Pixoo.');
  }

  brightnessSlider.addEventListener('input', (e) => {
    isDraggingSlider = true;
    brightnessValueDisplay.textContent = `${e.target.value}%`;
  });

  brightnessSlider.addEventListener('change', async (e) => {
    isDraggingSlider = false;
    await setBrightness(parseInt(e.target.value, 10));
  });

  presetChips.forEach((chip) => {
    chip.addEventListener('click', async () => {
      const val = parseInt(chip.dataset.val, 10);
      brightnessSlider.value = val;
      brightnessValueDisplay.textContent = `${val}%`;
      presetChips.forEach((c) => c.classList.remove('active'));
      chip.classList.add('active');
      await setBrightness(val);
    });
  });

  // ---------- Action buttons ----------

  $('btnActionTestPattern').addEventListener('click', async () => {
    showToast('Sending test graphic...');
    await fetch('/api/control/test-pixoo', { method: 'POST' });
  });

  $('btnActionTestIdle').addEventListener('click', async () => {
    showToast('Pushing idle screen...');
    await fetch('/api/control/test-idle', { method: 'POST' });
  });

  $('btnActionClear').addEventListener('click', async () => {
    showToast('Clearing display...');
    await fetch('/api/control/clear', { method: 'POST' });
  });

  $('btnManualCycleCover').addEventListener('click', async () => {
    showToast('Showing the next idle screen...');
    await fetch('/api/control/cycle', { method: 'POST' });
  });

  // ---------- Settings ----------

  const boolSelects = {
    use_24h_time: 'selectTimeFormat',
    always_show_hud: 'selectAlwaysShowHud',
    hud_accent: 'selectHudAccent',
    show_progress: 'selectShowProgress',
    show_title: 'selectShowTitle',
  };
  const valueFields = {
    on_pause: 'selectOnPause',
    hud_position: 'selectHudPosition',
    weather_unit: 'selectWeatherUnit',
    idle_transition: 'selectIdleTransition',
    night_mode: 'selectNightMode',
    night_start: 'inputNightStart',
    night_end: 'inputNightEnd',
    idle_cycle_interval: 'inputCycleInterval',
    night_brightness: 'inputNightBrightness',
  };

  function populateSettings(s) {
    Object.entries(boolSelects).forEach(([key, id]) => {
      if (s[key] !== undefined) $(id).value = s[key] ? 'true' : 'false';
    });
    Object.entries(valueFields).forEach(([key, id]) => {
      if (s[key] !== undefined && s[key] !== null) $(id).value = s[key];
    });
    const screens = String(s.idle_screens || 'cover').split(',');
    $('idleScreenCover').checked = screens.includes('cover');
    $('idleScreenForecast').checked = screens.includes('forecast');

    const boost = s.enhance_contrast || 1.0;
    if (boost >= 1.25) $('presetUltra').checked = true;
    else if (boost >= 1.1) $('presetPunchy').checked = true;
    else $('presetNormal').checked = true;
  }

  settingsForm.addEventListener('input', () => { formDirty = true; });
  settingsForm.addEventListener('change', () => { formDirty = true; });

  settingsForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const boostVal = parseFloat(document.querySelector('input[name="enhancementPreset"]:checked').value);
    const screens = ['idleScreenCover', 'idleScreenForecast'].filter((id) => $(id).checked).map((id) => $(id).value);
    if (!screens.length) {
      showToast('Pick at least one idle screen.');
      return;
    }

    const form = { enhance_contrast: boostVal, enhance_color: boostVal, idle_screens: screens.join(',') };
    Object.entries(boolSelects).forEach(([key, id]) => { form[key] = $(id).value === 'true'; });
    Object.entries(valueFields).forEach(([key, id]) => { form[key] = $(id).value; });

    // Send only what differs from the app, so a stale field can never overwrite a setting
    const payload = {};
    Object.entries(form).forEach(([key, value]) => {
      if (!serverSettings || String(value) !== String(serverSettings[key])) payload[key] = value;
    });
    if (!Object.keys(payload).length) {
      formDirty = false;
      showToast('Nothing to save; these are already your settings.');
      return;
    }

    try {
      const { ok, data } = await postJson('/api/settings', payload);
      if (ok) {
        formDirty = false;
        showToast(data.saved_to_env === false ? 'Applied (no .env file to save to)' : 'Preferences saved');
      } else if (data.errors) {
        const [field, msg] = Object.entries(data.errors)[0];
        showToast(`${field.replace(/_/g, ' ')} ${msg}`);
      } else {
        showToast('Failed to save settings.');
      }
    } catch (err) {
      showToast('Failed to save settings.');
    }
  });

  // ---------- Start ----------
  fetchStatus();
  connectStream();
});
