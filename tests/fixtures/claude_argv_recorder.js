const fs = require('node:fs');
fs.writeFileSync(process.env.ARG_RECORD_PATH, JSON.stringify(process.argv));
process.exit(1);
