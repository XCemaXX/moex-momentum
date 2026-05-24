// Smoke test for the custom plotly bundle. Loads it inside JSDOM and verifies
// the three trace types we use can actually be plotted. Run after build.sh:
//   node smoke.js plotly.min.js
//
// Requires jsdom@22 (CommonJS). Installed alongside esbuild via package.json
// dev-deps if you uncomment; otherwise run a one-off:
//   NODE_EXTRA_CA_CERTS=/etc/ssl/certs/ca-certificates.crt npm install jsdom@22
const { JSDOM } = require('jsdom');
const fs = require('fs');
const vm = require('vm');

if (!process.argv[2]) {
    console.error('usage: node smoke.js <path-to-plotly.min.js>');
    process.exit(1);
}

const dom = new JSDOM(
    `<!DOCTYPE html><div id="chart" style="width:800px;height:600px"></div>`,
    { pretendToBeVisual: true },
);
const { window } = dom;
window.global = window;
window.process = { env: {}, version: 'node' };
window.Buffer = Buffer;

const ctx = vm.createContext(window);
const bundle = fs.readFileSync(process.argv[2], 'utf8');
vm.runInContext(bundle, ctx);
const Plotly = ctx.Plotly;
if (!Plotly) {
    console.error('NO Plotly export');
    process.exit(2);
}
console.log('Plotly.version:', Plotly.version || '(unset)');

const traces = Plotly.PlotSchema.get().traces;
console.log('registered traces:', Object.keys(traces).sort().join(','));
const want = ['scatter', 'bar', 'sankey'];
const missing = want.filter((t) => !traces[t]);
if (missing.length) {
    console.error('MISSING TRACES:', missing);
    process.exit(3);
}

const div = window.document.getElementById('chart');
(async () => {
    await Plotly.newPlot(
        div,
        [{ type: 'scatter', x: [1, 2, 3], y: [10, 20, 15], mode: 'lines' }],
        {
            xaxis: {
                rangeslider: { visible: true },
                rangeselector: { buttons: [{ step: 'all' }] },
            },
            yaxis: { type: 'log' },
        },
    );
    console.log('scatter+log+rangeslider+rangeselector: OK');

    await Plotly.newPlot(div, [
        {
            type: 'sankey',
            node: { label: ['A', 'B', 'C'] },
            link: { source: [0, 1], target: [1, 2], value: [1, 2] },
        },
    ]);
    console.log('sankey: OK');

    await Plotly.newPlot(div, [{ type: 'bar', x: ['a', 'b', 'c'], y: [1, 2, 3] }]);
    console.log('bar: OK');

    console.log('ALL PASSED');
})().catch((e) => {
    console.error('PLOT ERROR:', e && e.message);
    process.exit(4);
});
