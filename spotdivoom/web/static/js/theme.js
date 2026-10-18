/**
 * SpotDivoom 64 — looks (themes) and the personal touches that go with them:
 * the record shelf, your name in the header, and a caption from your listening.
 */

document.addEventListener('DOMContentLoaded', () => {
  const root = document.documentElement;
  const lookSelect = document.getElementById('lookSelect');
  const shelf = document.getElementById('recordShelf');
  const shelfRow = document.getElementById('shelfRow');
  const shelfCaption = document.getElementById('shelfCaption');

  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  // ---------- Look switcher ----------
  const known = [...lookSelect.options].map((o) => o.value);
  const DEFAULT_LOOK = 'faded-film';
  if (!known.includes(root.dataset.theme)) root.dataset.theme = DEFAULT_LOOK;
  lookSelect.value = root.dataset.theme;

  lookSelect.addEventListener('change', () => {
    root.dataset.theme = lookSelect.value;
    try { localStorage.setItem('spotdivoom-look', lookSelect.value); } catch (e) {}
    document.dispatchEvent(new CustomEvent('spotdivoom:theme', { detail: lookSelect.value }));
  });

  // ---------- Personal touches from your Spotify stats ----------
  function firstName(name) {
    return String(name || '').trim().split(/\s+/)[0] || 'Your';
  }

  function shelfRecords(stats) {
    const seen = new Set();
    const records = [];
    for (const term of ['short_term', 'medium_term', 'long_term']) {
      for (const t of stats.top_tracks[term] || []) {
        if (!t.image || seen.has(t.image)) continue;
        seen.add(t.image);
        records.push(t);
        if (records.length === 12) return records;
      }
    }
    return records;
  }

  function caption(stats) {
    const artist = stats.top_artists.short_term?.[0]?.name;
    const track = stats.top_tracks.short_term?.[0];
    const parts = [];
    if (artist) parts.push(`Mostly ${artist} lately.`);
    if (track) parts.push(`Your most played track this month is “${track.name}”.`);
    return parts.join(' ');
  }

  document.addEventListener('spotdivoom:stats', ({ detail: stats }) => {
    const name = firstName(stats.profile?.name);
    document.getElementById('brandSubtitle').textContent = `${name}'s listening room`;
    document.getElementById('storyTitle').textContent = `${name}'s listening story`;

    const records = shelfRecords(stats);
    if (!records.length) return;
    shelfCaption.textContent = caption(stats);
    shelfRow.innerHTML = records.map((t) => `
      <a class="shelf-item" href="${esc(t.url)}" target="_blank" rel="noopener" title="${esc(t.name)} by ${esc(t.artist)}">
        <span class="shelf-art"><img src="${esc(t.image)}" alt="${esc(t.name)} by ${esc(t.artist)}" loading="lazy"></span>
        <span class="shelf-label"><span class="shelf-track">${esc(t.name)}</span><span class="shelf-artist">${esc(t.artist)}</span></span>
      </a>`).join('');
    shelf.hidden = false;
  });
});
