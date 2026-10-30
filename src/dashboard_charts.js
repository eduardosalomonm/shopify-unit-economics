// Calendar buckets keep quiet trading periods visible instead of joining over them.
function salesSeries(rows, period) {
  if (!rows.length) return [];
  const monthly = period === 'all';
  const dates = rows.map(row => row.date).sort();
  const start = monthly ? `${dates[0].slice(0, 7)}-01` : dates[0];
  const end = monthly ? `${dates[dates.length - 1].slice(0, 7)}-01` : dates[dates.length - 1];
  const buckets = new Map();
  const cursor = new Date(`${start}T00:00:00Z`);
  while (cursor.toISOString().slice(0, 10) <= end) {
    const key = cursor.toISOString().slice(0, monthly ? 7 : 10);
    buckets.set(key, {key, gross: 0, margin: 0, after: 0,
      label: cursor.toLocaleDateString('en-GB', monthly
        ? {month: 'short', year: '2-digit', timeZone: 'UTC'}
        : {day: 'numeric', month: 'short', timeZone: 'UTC'})});
    if (monthly) cursor.setUTCMonth(cursor.getUTCMonth() + 1);
    else cursor.setUTCDate(cursor.getUTCDate() + 1);
  }
  rows.forEach(row => {
    const bucket = buckets.get(row.date.slice(0, monthly ? 7 : 10));
    for (const key of ['gross', 'margin', 'after']) bucket[key] += row[key] || 0;
  });
  return [...buckets.values()];
}

function drawChart(id, series) {
  const svg = document.getElementById(id);
  if (!svg) return;
  svg.setAttribute('role', 'img');
  svg.setAttribute('aria-label', 'Sales and margin trend. Negative margins are shown below zero.');
  if (!series.length) {
    svg.innerHTML = '<text x="380" y="125" text-anchor="middle" fill="#77809e" font-size="13">No sales in this view</text>';
    return;
  }
  const keys = hasVariable ? ['gross', 'margin', 'after'] : ['gross', 'margin'];
  const values = series.flatMap(row => keys.map(key => row[key] || 0));
  const high = Math.max(1, ...values), low = Math.min(0, ...values);
  const padding = (high - low) * 0.08;
  const max = high + padding, min = low < 0 ? low - padding : 0;
  const left = 62, right = 724, top = 20, bottom = 211;
  const x = index => series.length === 1 ? (left + right) / 2
    : left + index * (right - left) / (series.length - 1);
  const y = value => bottom - (value - min) * (bottom - top) / (max - min);
  const ticks = Array.from({length: 5}, (_, i) => min + (max - min) * i / 4);
  if (min < 0) ticks.push(0);
  let markup = ticks.map(value => `<line x1="${left}" y1="${y(value)}" x2="${right}" y2="${y(value)}" stroke="${value === 0 ? '#77809e' : '#e6e9f3'}"/><text x="${left - 8}" y="${y(value) + 3}" text-anchor="end" fill="#77809e" font-size="10">${esc(new Intl.NumberFormat('en-GB', {notation:'compact',maximumFractionDigits:1}).format(value))}</text>`).join('');
  const colours = {gross: '#5a4fe8', margin: '#3e9f9a', after: '#ad7214'};
  const names = {gross: 'Gross sales', margin: 'Product margin', after: 'After variable costs'};
  for (const key of keys) {
    const path = series.map((row, i) => `${i ? 'L' : 'M'}${x(i)},${y(row[key] || 0)}`).join(' ');
    markup += `<path d="${path}" fill="none" stroke="${colours[key]}" stroke-width="2.5"${key === 'after' ? ' stroke-dasharray="6 4"' : ''}/>`;
    markup += series.map((row, i) => `<circle cx="${x(i)}" cy="${y(row[key] || 0)}" r="${series.length > 60 ? 2 : 3.5}" fill="${colours[key]}"><title>${esc(`${row.label}: ${names[key]} ${euro(row[key] || 0)}`)}</title></circle>`).join('');
  }
  const step = Math.max(1, Math.ceil(series.length / 7));
  markup += series.map((row, i) => i % step === 0 || i === series.length - 1
    ? `<text x="${x(i)}" y="241" text-anchor="middle" fill="#77809e" font-size="10">${esc(row.label)}</text>` : '').join('');
  svg.innerHTML = markup;
}

if (typeof module !== 'undefined' && module.exports) module.exports = {salesSeries};
