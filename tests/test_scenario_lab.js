// Run with: node --test tests/test_scenario_lab.js
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { calculateScenario } = require('../src/scenario_lab.js');
const base = { gross: 1210, net: 1000, margin: 400, units: 100 };
test('neutral assumptions preserve the baseline', () => {
  const result = calculateScenario(base, 0, 0, 0);
  assert.equal(result.margin, base.margin);
  assert.equal(result.gross, base.gross);
  assert.equal(result.requiredVolumeChange, 0);
});
test('discounting requires enough volume to recover lost margin', () => {
  const result = calculateScenario(base, -10, 0, 0);
  assert.equal(result.margin, 300);
  assert.ok(Math.abs(result.requiredVolumeChange - 100 / 3) < 1e-8);
  assert.ok(Math.abs(calculateScenario(base, -10, result.requiredVolumeChange, 0).margin - 400) < 1e-8);
});
test('price, volume and supplier cost changes combine', () => {
  const result = calculateScenario(base, 10, 20, 10);
  assert.equal(result.gross, 1597.2);
  assert.equal(result.units, 120);
  assert.equal(result.cost, 792);
  assert.equal(result.margin, 528);
});
test('zero sales, losses and nonpositive baselines do not invent recovery ratios', () => {
  assert.equal(calculateScenario(base, 0, -100, 0).margin, 0);
  assert.equal(calculateScenario(base, -90, 0, 0).requiredVolumeChange, null);
  assert.equal(calculateScenario({...base, margin: -100}, 0, 0, 0).requiredVolumeChange, null);
  assert.equal(calculateScenario({gross:0, net:0, margin:0, units:0}, 0, 0, 0).margin, 0);
});
test('invalid and out-of-range assumptions are rejected', () => {
  for (const values of [[NaN,0,0], [Infinity,0,0], [-91,0,0], [201,0,0], [0,-101,0], [0,501,0], [0,0,-101], [0,0,501]]) {
    assert.throws(() => calculateScenario(base, ...values));
  }
});
