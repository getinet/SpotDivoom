/**
 * SpotDivoom 64 — "Your Listening Story" stats section
 */

document.addEventListener('DOMContentLoaded', () => {
  const SVG_NS = 'http://www.w3.org/2000/svg';
  // Chart colors come from the active look's CSS tokens (see themes.css)
  let BAR, BAR_PEAK, HEAT_LOW, HEAT_HIGH, HEAT_EMPTY;
  const colorProbe = document.createElement('span');
  colorProbe.style.display = 'none';
  document.body.appendChild(colorProbe);

  function cssColor(token) {
    colorProbe.style.color = `var(${token})`;
    return getComputedStyle(colorProbe).color;
  }

  function rgbParts(color) {
    return (color.match(/[\d.]+/g) || [0, 0, 0]).slice(0, 3).map(Number);
  }

  function readChartColors() {
    BAR = cssColor('--chart-bar');
    BAR_PEAK = cssColor('--chart-peak');
    HEAT_LOW = rgbParts(cssColor('--heat-low'));
    HEAT_HIGH = rgbParts(cssColor('--heat-high'));
    HEAT_EMPTY = cssColor('--heat-empty');
  }
  const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

  const el = (id) => document.getElementById(id);
  const tooltip = el('chartTooltip');
  let stats = null;
  let use24h = false;
  let currentTerm = 'short_term';

  // ---------- Formatting helpers ----------
  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  function hourLabel(h, short = false) {
    if (use24h) return short ? String(h).padStart(2, '0') : `${String(h).padStart(2, '0')}:00`;
    const suffix = h < 12 ? 'am' : 'pm';
    const hr = h % 12 === 0 ? 12 : h % 12;
    return short ? `${hr}${suffix[0]}` : `${hr} ${suffix}`;
  }

  function monthLabel(ym, withYear = true) {
    const [y, m] = ym.split('-').map(Number);
    const d = new Date(y, m - 1, 1);
    return d.toLocaleDateString(undefined, withYear ? { month: 'short', year: 'numeric' } : { month: 'short' });
  }

  function timeAgo(iso) {
    const mins = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
    if (mins < 60) return `${Math.max(mins, 1)} min ago`;
    const hrs = Math.round(mins / 60);
    if (hrs < 24) return `${hrs} hr ago`;
    return `${Math.round(hrs / 24)} d ago`;
  }

  function svg(tag, attrs = {}) {
    const node = document.createElementNS(SVG_NS, tag);
    Object.entries(attrs).forEach(([k, v]) => node.setAttribute(k, v));
    return node;
  }

  // Rounded data-end (4px) anchored flat on the baseline
  function barPath(x, y, w, h, r = 4) {
    if (h <= 0) return '';
    r = Math.min(r, w / 2, h);
    return `M${x},${y + h} V${y + r} Q${x},${y} ${x + r},${y} H${x + w - r} Q${x + w},${y} ${x + w},${y + r} V${y + h} Z`;
  }

  function hbarPath(x, y, w, h, r = 4) {
    if (w <= 0) return '';
    r = Math.min(r, h / 2, w);
    return `M${x},${y} H${x + w - r} Q${x + w},${y} ${x + w},${y + r} V${y + h - r} Q${x + w},${y + h} ${x + w - r},${y + h} H${x} Z`;
  }

  // ---------- Tooltip ----------
  function showTip(evt, html) {
    tooltip.innerHTML = html;
    tooltip.hidden = false;
    const pad = 14;
    const rect = tooltip.getBoundingClientRect();
    let x = evt.clientX + pad;
    let y = evt.clientY - rect.height - pad;
    if (x + rect.width > window.innerWidth - 8) x = evt.clientX - rect.width - pad;
    if (y < 8) y = evt.clientY + pad;
    tooltip.style.left = `${x}px`;
    tooltip.style.top = `${y}px`;
  }
  const hideTip = () => { tooltip.hidden = true; };

  function bindTip(node, html) {
    node.addEventListener('mousemove', (e) => showTip(e, html));
    node.addEventListener('mouseleave', hideTip);
    node.setAttribute('tabindex', '0');
    node.setAttribute('aria-label', html.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim());
    node.addEventListener('focus', () => {
      const r = node.getBoundingClientRect();
      showTip({ clientX: r.left + r.width / 2, clientY: r.top }, html);
    });
    node.addEventListener('blur', hideTip);
  }

  function dataTable(headers, rows) {
    const details = document.createElement('details');
    details.className = 'chart-table';
    details.innerHTML = `<summary>Show data</summary><table><thead><tr>${headers.map((h) => `<th>${esc(h)}</th>`).join('')}</tr></thead>
      <tbody>${rows.map((r) => `<tr>${r.map((c) => `<td>${esc(c)}</td>`).join('')}</tr>`).join('')}</tbody></table>`;
    return details;
  }

  // ---------- Charts ----------
  // Vertical bars: items = [{label, value, tip}], tickEvery = show every Nth x label
  function columnChart(container, items, { tickEvery = 1, unit = '', table } = {}) {
    container.innerHTML = '';
    const W = 600, H = 200, padL = 30, padR = 6, padT = 22, padB = 24;
    const max = Math.max(1, ...items.map((d) => d.value));
    const plotW = W - padL - padR, plotH = H - padT - padB;
    const slot = plotW / items.length;
    const barW = Math.max(2, slot - 2);  // 2px surface gap between bars
    const peakIndex = items.reduce((best, d, i) => (d.value > items[best].value ? i : best), 0);

    const root = svg('svg', { viewBox: `0 0 ${W} ${H}`, class: 'chart-svg', role: 'img' });
    // Recessive gridline at max + baseline
    root.appendChild(svg('line', { x1: padL, x2: W - padR, y1: padT, y2: padT, class: 'grid-line' }));
    const maxLabel = svg('text', { x: padL - 6, y: padT + 4, class: 'axis-label', 'text-anchor': 'end' });
    maxLabel.textContent = max;
    root.appendChild(maxLabel);
    root.appendChild(svg('line', { x1: padL, x2: W - padR, y1: H - padB, y2: H - padB, class: 'axis-line' }));

    items.forEach((d, i) => {
      const x = padL + i * slot + 1;
      const h = (d.value / max) * plotH;
      const y = H - padB - h;
      const isPeak = i === peakIndex && d.value > 0;
      if (h > 0) root.appendChild(svg('path', { d: barPath(x, y, barW, h), fill: isPeak ? BAR_PEAK : BAR }));

      if (isPeak) {
        const t = svg('text', { x: x + barW / 2, y: y - 6, class: 'peak-label', 'text-anchor': 'middle' });
        t.textContent = `${d.value}${unit}`;
        root.appendChild(t);
      }
      if (i % tickEvery === 0) {
        const t = svg('text', { x: x + barW / 2, y: H - 8, class: 'axis-label', 'text-anchor': 'middle' });
        t.textContent = d.tick ?? d.label;
        root.appendChild(t);
      }
      // Hit target spans the full column height, larger than the mark
      const hit = svg('rect', { x: padL + i * slot, y: padT, width: slot, height: plotH, class: 'hit-target' });
      bindTip(hit, d.tip);
      root.appendChild(hit);
    });

    container.appendChild(root);
    if (table) container.appendChild(dataTable(table.headers, table.rows));
  }

  function barListChart(container, items, { table } = {}) {
    container.innerHTML = '';
    const rowH = 28, W = 600, padL = 64, padR = 44;
    const H = items.length * rowH + 4;
    const max = Math.max(1, ...items.map((d) => d.value));
    const root = svg('svg', { viewBox: `0 0 ${W} ${H}`, class: 'chart-svg', role: 'img' });
    root.appendChild(svg('line', { x1: padL, x2: padL, y1: 0, y2: H, class: 'axis-line' }));

    items.forEach((d, i) => {
      const y = i * rowH + 5;
      const w = (d.value / max) * (W - padL - padR);
      const label = svg('text', { x: padL - 10, y: y + 13, class: 'axis-label strong', 'text-anchor': 'end' });
      label.textContent = d.label;
      root.appendChild(label);
      if (w > 0) root.appendChild(svg('path', { d: hbarPath(padL, y, w, 18), fill: BAR }));
      const val = svg('text', { x: padL + w + 8, y: y + 13, class: 'axis-label' });
      val.textContent = d.value;
      root.appendChild(val);
      const hit = svg('rect', { x: 0, y: y - 4, width: W, height: rowH, class: 'hit-target' });
      bindTip(hit, d.tip);
      root.appendChild(hit);
    });

    container.appendChild(root);
    if (table) container.appendChild(dataTable(table.headers, table.rows));
  }

  // Sequential single-hue ramp: dark green (few) -> Spotify green (many); zero recedes to the surface
  function rampColor(t) {
    const c = HEAT_LOW.map((f, i) => Math.round(f + (HEAT_HIGH[i] - f) * t));
    return `rgb(${c.join(',')})`;
  }

  function heatmap(container, week, countLabel) {
    container.innerHTML = '';
    const W = 600, padL = 36, padT = 4, padB = 22;
    const cell = (W - padL) / 24;
    const H = padT + cell * 7 + padB;
    const max = Math.max(1, ...week.flat());
    const root = svg('svg', { viewBox: `0 0 ${W} ${H}`, class: 'chart-svg', role: 'img' });

    week.forEach((row, d) => {
      const label = svg('text', { x: padL - 8, y: padT + d * cell + cell / 2 + 4, class: 'axis-label', 'text-anchor': 'end' });
      label.textContent = DAYS[d];
      root.appendChild(label);
      row.forEach((count, h) => {
        const x = padL + h * cell, y = padT + d * cell;
        const rect = svg('rect', {
          x: x + 1, y: y + 1, width: cell - 2, height: cell - 2, rx: 3,
          fill: count ? rampColor(Math.sqrt(count / max)) : HEAT_EMPTY,
        });
        bindTip(rect, `<strong>${DAYS[d]}, ${hourLabel(h)}</strong><br>${countLabel(count)}`);
        root.appendChild(rect);
      });
    });
    [0, 6, 12, 18].forEach((h) => {
      const t = svg('text', { x: padL + h * cell + cell / 2, y: H - 6, class: 'axis-label', 'text-anchor': 'middle' });
      t.textContent = hourLabel(h, true);
      root.appendChild(t);
    });
    container.appendChild(root);

    const legend = document.createElement('div');
    legend.className = 'heat-legend';
    legend.innerHTML = `<span>Fewer</span><span class="heat-ramp"></span><span>More</span>`;
    container.appendChild(legend);
    container.appendChild(dataTable(['Day', ...Array.from({ length: 24 }, (_, h) => hourLabel(h, true))],
      week.map((row, d) => [DAYS[d], ...row])));
  }

  // ---------- Renderers ----------
  function renderTiles(h) {
    const mins = h.avg_length_s ? `${Math.floor(h.avg_length_s / 60)}:${String(h.avg_length_s % 60).padStart(2, '0')}` : '—';
    const tiles = [
      { label: 'Liked songs', value: h.library_size?.toLocaleString() ?? '—', note: 'in your library' },
      { label: 'Typical release year', value: h.median_year ?? '—', note: 'median of your top tracks' },
      { label: 'Fresh drops', value: h.fresh_share != null ? `${h.fresh_share}%` : '—', note: 'of top tracks released in the last 2 years' },
      { label: 'Loyalty', value: h.loyalty != null ? `${h.loyalty}%` : '—', note: "of this month's top artists are all-time favorites" },
      { label: 'Artist variety', value: h.variety != null ? `${h.variety}%` : '—', note: 'unique artists across your top 50 tracks' },
      { label: 'Singles', value: h.singles_share != null ? `${h.singles_share}%` : '—', note: 'of favorites come from singles, not albums' },
      { label: 'Explicit', value: h.explicit_share != null ? `${h.explicit_share}%` : '—', note: 'of your top tracks' },
      { label: 'Average song', value: mins, note: 'minutes per track' },
    ];
    el('storyTiles').innerHTML = tiles.map((t) => `
      <div class="stat-tile">
        <span class="stat-label">${esc(t.label)}</span>
        <span class="tile-value">${esc(t.value)}</span>
        <span class="tile-note">${esc(t.note)}</span>
      </div>`).join('');
  }

  function artistItem(a, i) {
    const img = a.image ? `<img src="${esc(a.image)}" alt="" loading="lazy">` : '<div class="img-placeholder"></div>';
    return `<a class="artist-card" href="${esc(a.url)}" target="_blank" rel="noopener">
      ${img}<span class="artist-rank">${i + 1}</span><span class="artist-name">${esc(a.name)}</span></a>`;
  }

  function trackItem(t, meta) {
    const img = t.image ? `<img src="${esc(t.image)}" alt="" loading="lazy">` : '<div class="img-placeholder"></div>';
    const name = t.url ? `<a href="${esc(t.url)}" target="_blank" rel="noopener">${esc(t.name)}</a>` : esc(t.name);
    return `<li class="track-row">${img}<div class="track-text"><span class="track-name">${name}</span>
      <span class="track-sub">${esc(t.artist)}</span></div>${meta ? `<span class="track-meta">${esc(meta)}</span>` : ''}</li>`;
  }

  function renderFavorites() {
    const artists = stats.top_artists[currentTerm] || [];
    const tracks = stats.top_tracks[currentTerm] || [];
    el('storyArtists').innerHTML = artists.length ? artists.slice(0, 8).map(artistItem).join('') : '<p class="chapter-hint">Not enough listening yet for this range.</p>';
    el('storyTracks').innerHTML = tracks.slice(0, 8).map((t) => trackItem(t)).join('');
  }

  function chips(list) {
    if (!list.length) return '<p class="chapter-hint">Nothing here yet.</p>';
    return list.map((a) => `<a class="artist-chip" href="${esc(a.url)}" target="_blank" rel="noopener">
      ${a.image ? `<img src="${esc(a.image)}" alt="">` : ''}<span>${esc(a.name)}</span></a>`).join('');
  }

  function renderClock(l) {
    const fromLikes = l.clock_source === 'likes';
    const countLabel = (n) => (fromLikes ? `${n} song${n === 1 ? '' : 's'} liked` : `${n} play${n === 1 ? '' : 's'}`);
    el('clockTitle').textContent = fromLikes ? 'When you save music' : 'When you listen';
    el('clockHint').textContent = fromLikes
      ? `Based on when you added songs to Liked Songs. Listening times will appear here once Spotify shares your recent plays and SpotDivoom logs your plays.`
      : `Based on ${l.plays_sampled} recent plays${l.span_days ? ` over ${l.span_days} day${l.span_days === 1 ? '' : 's'}` : ''}` +
        `${l.logged_plays ? `, including ${l.logged_plays} logged by SpotDivoom` : ''}. Gets richer the longer SpotDivoom runs.`;

    columnChart(el('hourChart'), l.hours.map((v, h) => ({
      label: hourLabel(h), tick: hourLabel(h, true), value: v,
      tip: `<strong>${hourLabel(h)}</strong><br>${countLabel(v)}`,
    })), {
      tickEvery: 3,
      table: { headers: ['Hour', fromLikes ? 'Songs liked' : 'Plays'], rows: l.hours.map((v, h) => [hourLabel(h), v]) },
    });
    heatmap(el('weekChart'), l.week, countLabel);
  }

  function renderLibrary(lib) {
    const months = lib.months;
    const total = months.reduce((s, m) => s + m.count, 0);
    const parts = [`${total} song${total === 1 ? '' : 's'} liked in the last 2 years.`];
    if (lib.biggest_month) parts.push(`Your biggest month ever: ${monthLabel(lib.biggest_month.month)} with ${lib.biggest_month.count}.`);
    if (lib.first_like) parts.push(`First like: ${new Date(lib.first_like).toLocaleDateString(undefined, { month: 'long', year: 'numeric' })}.`);
    el('libraryHint').textContent = parts.join(' ');

    columnChart(el('libraryChart'), months.map((m, i) => ({
      label: monthLabel(m.month),
      tick: i % 6 === 0 ? monthLabel(m.month, m.month.endsWith('-01') || i === 0) : '',
      value: m.count,
      tip: `<strong>${monthLabel(m.month)}</strong><br>${m.count} song${m.count === 1 ? '' : 's'} liked`,
    })), {
      tickEvery: 6,
      table: { headers: ['Month', 'Songs liked'], rows: months.map((m) => [monthLabel(m.month), m.count]) },
    });
  }

  function renderDecades(decades) {
    const total = decades.reduce((s, d) => s + d.count, 0);
    const top = decades.reduce((a, b) => (b.count > (a?.count ?? -1) ? b : a), null);
    el('decadeHint').textContent = top
      ? `${Math.round((100 * top.count) / total)}% of your top tracks are from the ${top.decade}.`
      : 'No release dates available yet.';
    barListChart(el('decadeChart'), decades.map((d) => ({
      label: d.decade, value: d.count,
      tip: `<strong>${d.decade}</strong><br>${d.count} of your top tracks (${Math.round((100 * d.count) / total)}%)`,
    })), { table: { headers: ['Decade', 'Top tracks'], rows: decades.map((d) => [d.decade, d.count]) } });
  }

  function renderRecent(l) {
    const hasRecent = l.recent.length > 0;
    el('recentChapter').hidden = !hasRecent;
    if (!hasRecent) return;
    el('storyRecent').innerHTML = l.recent.map((t) => trackItem(t, timeAgo(t.played_at))).join('');
    el('onRepeatCol').hidden = !l.on_repeat.length;
    el('storyOnRepeat').innerHTML = l.on_repeat.map((t) => trackItem(t, `${t.plays}×`)).join('');
  }

  function render() {
    readChartColors();
    const p = stats.personality;
    const l = stats.listening;

    if (stats.profile.image) {
      el('storyAvatar').src = stats.profile.image;
      el('storyAvatar').hidden = false;
    }
    el('storyGreeting').textContent = `${String(stats.profile.name || '').trim().split(/\s+/)[0] || 'You'}, you're a…`;
    el('storyPersona').textContent = p.taste_label;
    el('storyPersonaLine').textContent = p.taste_line;
    if (p.time_label) {
      const peak = l.peak_hour != null ? hourLabel(l.peak_hour) : '';
      el('storyTimeLine').innerHTML = l.clock_source === 'likes'
        ? `<strong>${esc(p.time_label)}</strong>: you save the most music around ${esc(peak)}, especially on ${esc(l.peak_day)}s.`
        : `<strong>${esc(p.time_label)}</strong>: ${esc(p.time_line)} Peak: ${esc(peak)} on ${esc(l.peak_day)}s.`;
    }

    const notice = el('storyNotice');
    notice.hidden = !l.recent_error;
    if (l.recent_error) {
      notice.textContent = 'Recently played is locked: SpotDivoom needs one more Spotify permission. ' +
        'Restart SpotDivoom and approve the Spotify prompt to unlock your listening clock and recent plays.';
    }

    renderTiles(stats.headline);
    renderFavorites();
    el('storyNewObsessions').innerHTML = chips(stats.evolution.new_obsessions);
    el('storyRideOrDie').innerHTML = chips(stats.evolution.ride_or_die);
    renderClock(l);
    renderLibrary(stats.library);
    renderDecades(stats.decades);
    renderRecent(l);

    const at = new Date(stats.generated_at);
    el('storyUpdated').textContent = `Updated ${at.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit', hour12: !use24h })}`;
  }

  async function loadStats(refresh = false) {
    el('btnRefreshStats').disabled = true;
    try {
      // Status only supplies the 12/24-hour preference; fetch it alongside the stats
      const [status, res] = await Promise.all([
        fetch('/api/status').then((r) => r.json()).catch(() => null),
        fetch(`/api/stats${refresh ? '?refresh=1' : ''}`),
      ]);
      use24h = Boolean(status?.settings?.use_24h_time);
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Could not load stats.');
      stats = data;
      document.dispatchEvent(new CustomEvent('spotdivoom:stats', { detail: data }));
      el('storyError').hidden = true;
      el('storyLoading').hidden = true;
      el('storyBody').hidden = false;
      render();
    } catch (err) {
      el('storyLoading').hidden = true;
      el('storyError').hidden = false;
      el('storyError').textContent = err.message;
      el('storyUpdated').textContent = 'Unavailable';
    } finally {
      el('btnRefreshStats').disabled = false;
    }
  }

  document.querySelectorAll('[data-term]').forEach((btn) => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('[data-term]').forEach((b) => b.classList.toggle('active', b === btn));
      currentTerm = btn.dataset.term;
      if (stats) renderFavorites();
    });
  });
  el('btnRefreshStats').addEventListener('click', () => loadStats(true));

  // Redraw charts in the new look's colors
  document.addEventListener('spotdivoom:theme', () => { if (stats) render(); });

  loadStats();
});
