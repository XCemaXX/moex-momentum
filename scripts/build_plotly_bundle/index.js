// Custom plotly.js bundle for MOEX momentum pipeline.
// Includes only the trace types our charts use:
//   - Scatter   (line plots: NAV curves, spreads, alpha)            — phase 10
//   - Bar       (planned: monthly-mode chart)                       — task 003
//   - Sankey    (planned: quartile transitions)                     — task 001
// Result is ~1.2 MB on disk, ~406 KB gzip (vs full bundle 4.7 MB / 1.4 MB gzip).
const Plotly = require('plotly.js/lib/core');
Plotly.register([
    require('plotly.js/lib/scatter'),
    require('plotly.js/lib/bar'),
    require('plotly.js/lib/sankey'),
]);
module.exports = Plotly;
