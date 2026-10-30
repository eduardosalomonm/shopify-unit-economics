const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const {salesSeries} = require('../src/dashboard_charts.js');
test('calendar series retains quiet days and negative results', () => {
  const rows = [{date:'2026-02-28',gross:100,margin:30,after:-10},
                {date:'2026-03-02',gross:80,margin:-20,after:-40}];
  const result = salesSeries(rows,'custom');
  assert.equal(result.length,3);
  assert.equal(result[1].key,'2026-03-01');
  assert.equal(result[1].gross,0);
  assert.equal(result[2].after,-40);
});
test('monthly series includes missing months and years in labels', () => {
  const rows = [{date:'2025-12-31',gross:10,margin:5}, {date:'2026-02-01',gross:20,margin:10}];
  const result = salesSeries(rows,'all');
  assert.equal(result.length,3);
  assert.equal(result[1].key,'2026-01');
  assert.match(result[0].label,/25/);
  assert.match(result[2].label,/26/);
  assert.deepEqual(salesSeries([],'all'),[]);
});
test('losses remain negative in labels and inside the chart bounds', () => {
  const svg = {innerHTML:'',setAttribute(){}};
  const context = {document:{getElementById:()=>svg},hasVariable:true,esc:String,euro:String,Intl};
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(require.resolve('../src/dashboard_charts.js'),'utf8'),context);
  context.drawChart('chart',[{label:'Jan',gross:100,margin:-50,after:-200}]);
  assert.match(svg.innerHTML,/After variable costs -200/);
  const ys = [...svg.innerHTML.matchAll(/cy="([^"]+)"/g)].map(m=>Number(m[1]));
  assert.equal(ys.length,3);
  assert.ok(ys.every(y=>y>=20&&y<=211));
  assert.ok(ys[2]>ys[1]&&ys[1]>ys[0]);
});
