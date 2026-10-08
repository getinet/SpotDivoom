/**
 * SpotDivoom 64 — Web Dashboard & Pixel Simulator
 */

document.addEventListener('DOMContentLoaded', () => {
  // Elements
  const matrixCanvas = document.getElementById('matrixCanvas');
  const ctx = matrixCanvas.getContext('2d');
  const btnModeLed = document.getElementById('btnModeLed');
  const btnModeSmooth = document.getElementById('btnModeSmooth');

  // Header Elements
  const headerWeatherIcon = document.getElementById('headerWeatherIcon');
  const headerTemp = document.getElementById('headerTemp');
  const headerCity = document.getElementById('headerCity');
  const headerClock = document.getElementById('headerClock');
  const pixooStatusDot = document.getElementById('pixooStatusDot');
  const pixooStatusText = document.getElementById('pixooStatusText');

  // Hardware Elements
  const brightnessSlider = document.getElementById('brightnessSlider');
  const brightnessValueDisplay = document.getElementById('brightnessValueDisplay');
  const presetChips = document.querySelectorAll('.preset-chip');
  const btnActionTestPattern = document.getElementById('btnActionTestPattern');
  const btnActionTestIdle = document.getElementById('btnActionTestIdle');
  const btnActionClear = document.getElementById('btnActionClear');
  const btnManualCycleCover = document.getElementById('btnManualCycleCover');

  // Now Playing Elements
  const playbackBadge = document.getElementById('playbackBadge');
  const playbackBadgeText = document.getElementById('playbackBadgeText');
  const equalizerBars = document.getElementById('equalizerBars');
  const trackCoverImg = document.getElementById('trackCoverImg');
  const trackTitle = document.getElementById('trackTitle');
  const trackArtist = document.getElementById('trackArtist');
  const trackAlbum = document.getElementById('trackAlbum');
  const trackProgressFill = document.getElementById('trackProgressFill');
  const trackTimeElapsed = document.getElementById('trackTimeElapsed');
  const trackTimeTotal = document.getElementById('trackTimeTotal');

  // Ambient Elements
  const idleCoverTitle = document.getElementById('idleCoverTitle');
  const idleWeatherStat = document.getElementById('idleWeatherStat');

  // Settings Form Elements
  const settingsForm = document.getElementById('settingsForm');
  const selectOnPause = document.getElementById('selectOnPause');
  const inputCycleInterval = document.getElementById('inputCycleInterval');
  const selectWeatherUnit = document.getElementById('selectWeatherUnit');
  const selectTimeFormat = document.getElementById('selectTimeFormat');
  const toastContainer = document.getElementById('toastContainer');

  // State
  let renderMode = 'led'; // 'led' or 'smooth'
  let isDraggingSlider = false;
  let lastImageTimestamp = 0;
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

  // Render Frame onto Matrix Canvas
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

        // Circular diode
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

  // Refresh Matrix Canvas Frame from Server
  function fetchMatrixFrame() {
    offscreenImg.onload = () => drawMatrixFrame();
    offscreenImg.src = `/api/frame?t=${Date.now()}`;
  }

  // Render Mode Toggle
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

  // Fetch Full Dashboard Status
  async function fetchStatus() {
    try {
      const res = await fetch('/api/status');
      if (!res.ok) return;
      const data = await res.json();

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
        if (data.pixoo.connected) {
          pixooStatusDot.className = 'pill-dot status-dot online';
          pixooStatusText.textContent = `Online • ${data.pixoo.ip}`;
        } else {
          pixooStatusDot.className = 'pill-dot status-dot offline';
          pixooStatusText.textContent = `Offline • ${data.pixoo.ip}`;
        }

        if (!isDraggingSlider && data.pixoo.brightness !== undefined) {
          brightnessSlider.value = data.pixoo.brightness;
          brightnessValueDisplay.textContent = `${data.pixoo.brightness}%`;
          presetChips.forEach(chip => {
            chip.classList.toggle('active', parseInt(chip.dataset.val) === data.pixoo.brightness);
          });
        }
      }

      // 3. Playback Card
      if (data.playback && data.playback.is_playing) {
        playbackBadge.className = 'playback-indicator-badge playing';
        playbackBadgeText.textContent = 'Playing';
        equalizerBars.classList.add('animating');

        trackTitle.textContent = data.playback.title || 'Unknown Title';
        trackArtist.textContent = data.playback.artist || 'Unknown Artist';
        trackAlbum.textContent = data.playback.album || '';

        if (data.playback.image_url && trackCoverImg.src !== data.playback.image_url) {
          trackCoverImg.src = data.playback.image_url;
        }

        const progress = data.playback.progress_ms || 0;
        const total = data.playback.duration_ms || 1;
        const pct = Math.min(100, Math.max(0, (progress / total) * 100));
        trackProgressFill.style.width = `${pct}%`;
        trackTimeElapsed.textContent = formatMs(progress);
        trackTimeTotal.textContent = formatMs(total);
      } else if (data.playback && !data.playback.is_playing && data.playback.title) {
        playbackBadge.className = 'playback-indicator-badge paused';
        playbackBadgeText.textContent = 'Paused';
        equalizerBars.classList.remove('animating');

        trackTitle.textContent = data.playback.title;
        trackArtist.textContent = data.playback.artist;
        trackAlbum.textContent = data.playback.album;
        if (data.playback.image_url) trackCoverImg.src = data.playback.image_url;

        const progress = data.playback.progress_ms || 0;
        const total = data.playback.duration_ms || 1;
        trackProgressFill.style.width = `${Math.min(100, (progress / total) * 100)}%`;
        trackTimeElapsed.textContent = formatMs(progress);
        trackTimeTotal.textContent = formatMs(total);
      } else {
        playbackBadge.className = 'playback-indicator-badge';
        playbackBadgeText.textContent = 'Idle';
        equalizerBars.classList.remove('animating');

        trackTitle.textContent = 'Ambient Mode';
        trackArtist.textContent = 'Liked Songs Library';
        trackAlbum.textContent = 'Local Clock & Weather Active';
        trackProgressFill.style.width = '0%';
        trackTimeElapsed.textContent = '0:00';
        trackTimeTotal.textContent = '0:00';
      }

      // 4. Populate Settings Form (only once on load)
      if (data.settings && !settingsForm.dataset.initialized) {
        settingsForm.dataset.initialized = 'true';
        selectOnPause.value = data.settings.on_pause || 'idle';
        inputCycleInterval.value = data.settings.idle_cycle_interval || 30;
        selectWeatherUnit.value = data.settings.weather_unit || 'F';
        selectTimeFormat.value = data.settings.use_24h_time ? 'true' : 'false';

        const boost = data.settings.enhance_contrast || 1.0;
        if (boost >= 1.25) document.getElementById('presetUltra').checked = true;
        else if (boost >= 1.1) document.getElementById('presetPunchy').checked = true;
        else document.getElementById('presetNormal').checked = true;
      }
    } catch (e) {
      console.warn('Status poll error:', e);
    }
  }

  // Brightness Control
  brightnessSlider.addEventListener('input', (e) => {
    isDraggingSlider = true;
    brightnessValueDisplay.textContent = `${e.target.value}%`;
  });

  brightnessSlider.addEventListener('change', async (e) => {
    isDraggingSlider = false;
    const val = parseInt(e.target.value);
    await fetch('/api/control/brightness', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ brightness: val }),
    });
    showToast(`Brightness set to ${val}%`);
  });

  presetChips.forEach(chip => {
    chip.addEventListener('click', async () => {
      const val = parseInt(chip.dataset.val);
      brightnessSlider.value = val;
      brightnessValueDisplay.textContent = `${val}%`;
      presetChips.forEach(c => c.classList.remove('active'));
      chip.classList.add('active');

      await fetch('/api/control/brightness', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ brightness: val }),
      });
      showToast(`Brightness set to ${val}%`);
    });
  });

  // Action Buttons
  btnActionTestPattern.addEventListener('click', async () => {
    showToast('Sending test graphic...');
    await fetch('/api/control/test-pixoo', { method: 'POST' });
    fetchMatrixFrame();
  });

  btnActionTestIdle.addEventListener('click', async () => {
    showToast('Pushing Idle HUD (Cover + Clock + Weather)...');
    await fetch('/api/control/test-idle', { method: 'POST' });
    fetchMatrixFrame();
  });

  btnActionClear.addEventListener('click', async () => {
    showToast('Clearing display...');
    await fetch('/api/control/clear', { method: 'POST' });
    fetchMatrixFrame();
  });

  btnManualCycleCover.addEventListener('click', async () => {
    showToast('Rotating to next liked track...');
    await fetch('/api/control/cycle', { method: 'POST' });
    setTimeout(fetchMatrixFrame, 400);
  });

  // Save Settings Form
  settingsForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const boostVal = parseFloat(document.querySelector('input[name="enhancementPreset"]:checked').value);

    const payload = {
      on_pause: selectOnPause.value,
      idle_cycle_interval: parseFloat(inputCycleInterval.value),
      weather_unit: selectWeatherUnit.value,
      use_24h_time: selectTimeFormat.value === 'true',
      enhance_contrast: boostVal,
      enhance_color: boostVal,
    };

    try {
      const res = await fetch('/api/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (res.ok) {
        showToast('Preferences saved successfully!');
      }
    } catch (err) {
      showToast('Failed to save settings.');
    }
  });

  // Initial Load & Intervals
  fetchStatus();
  fetchMatrixFrame();

  setInterval(fetchStatus, 2500);
  setInterval(fetchMatrixFrame, 3000);
});
