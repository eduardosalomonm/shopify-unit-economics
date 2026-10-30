// Pure arithmetic shared by the browser and the dependency-free Node tests.
function calculateScenario(base, priceChange, volumeChange, costChange) {
  if (![priceChange, volumeChange, costChange].every(Number.isFinite) ||
      priceChange < -90 || priceChange > 200 || volumeChange < -100 ||
      volumeChange > 500 || costChange < -100 || costChange > 500) {
    throw new Error('Enter price from -90 to 200%, volume and cost from -100 to 500%.');
  }
  const price = 1 + priceChange / 100, volume = 1 + volumeChange / 100;
  const cost = (base.net - base.margin) * (1 + costChange / 100);
  const marginAtBaseVolume = base.net * price - cost;
  return {
    gross: base.gross * price * volume, net: base.net * price * volume,
    cost: cost * volume, margin: marginAtBaseVolume * volume, units: base.units * volume,
    requiredVolumeChange: base.margin > 0 && marginAtBaseVolume > 0
      ? (base.margin / marginAtBaseVolume - 1) * 100 : null
  };
}

function renderScenario() {
  const controls = ['price', 'volume', 'cost'].map(key => document.getElementById(`scenario-${key}`));
  if (!controls[0].dataset.ready) {
    controls.forEach(input => input.addEventListener('input', renderScenario));
    controls[0].dataset.ready = 'true';
    document.getElementById('scenario-reset').addEventListener('click', () => {
      controls.forEach(input => { input.value = '0'; }); renderScenario();
    });
  }
  const base = aggregate(periodRows(currentPeriod));
  const result = document.getElementById('scenario-result');
  const decision = document.getElementById('scenario-decision');
  const error = document.getElementById('scenario-error');
  error.textContent = '';
  if (!base.units) {
    result.textContent = 'No sales in this selection. Change the dates or reset the filters.';
    decision.textContent = 'Import sales before modelling a commercial decision.'; return;
  }
  let scenario;
  try {
    scenario = calculateScenario(base, ...controls.map(input => input.value === '' ? NaN : Number(input.value)));
  } catch (failure) {
    error.textContent = failure.message;
    result.textContent = 'Correct the assumptions to calculate the scenario.';
    decision.textContent = ''; return;
  }
  const metrics = [
    ['Gross sales', base.gross, scenario.gross, euro],
    ['Product cost', base.net - base.margin, scenario.cost, euro],
    ['Units', base.units, scenario.units, number],
    ['Product margin', base.margin, scenario.margin, euro]
  ];
  result.innerHTML = '<table class="scenario-comparison"><thead><tr><th scope="col">Metric</th><th scope="col">Baseline</th><th scope="col">Scenario</th><th scope="col">Change</th></tr></thead><tbody>' +
    metrics.map(([label, before, after, format], index) => `<tr${index === 3 ? ' class="result-row"' : ''}><th scope="row">${label}</th><td>${format(before)}</td><td>${format(after)}</td><td>${format(after - before)}</td></tr>`).join('') + '</tbody></table>';
  const needed = scenario.requiredVolumeChange;
  if (needed === null) {
    decision.textContent = scenario.margin <= 0
      ? 'This scenario does not generate positive product margin. More volume alone cannot fix a loss per unit; review price and product cost first.'
      : 'The baseline has no positive product margin to preserve. This scenario improves it; validate demand before changing prices.';
  } else {
    decision.textContent = needed >= 0
      ? `You need ${pct(needed)} more volume to preserve baseline product margin at this price and unit cost.`
      : `Volume could fall by ${pct(-needed)} before product margin drops below baseline at this price and unit cost.`;
  }
}
if (typeof module !== 'undefined' && module.exports) module.exports = { calculateScenario };
