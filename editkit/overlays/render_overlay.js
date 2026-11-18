// Render an HTML overlay template to a video with alpha (ProRes 4444 .mov) or to a single PNG still.
// usage: node render_overlay.js --template t.html --out o.mov --w 1080 --h 1920 --fps 30 --dur 3 --params '{"title":"..."}'
//        add --still 1.2 to write one PNG at t=1.2s instead of a video.
const { chromium } = require('playwright');
const { spawn } = require('child_process');
const path = require('path');

const args = {};
for (let i = 2; i < process.argv.length; i += 2) args[process.argv[i].replace(/^--/, '')] = process.argv[i + 1];
const W = +(args.w || 1080), H = +(args.h || 1920), FPS = +(args.fps || 30), DUR = +(args.dur || 3);
const params = args.params || '{}';

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: W, height: H }, deviceScaleFactor: 1 });
  await page.addInitScript(`window.PARAMS=${params};window.DURATION=${DUR};window.W=${W};window.H=${H};`);
  await page.goto('file://' + path.resolve(args.template));
  await page.waitForFunction(() => typeof window.seek === 'function');
  await page.evaluate(() => document.fonts.ready);
  if (args.still !== undefined) {
    await page.evaluate(t => window.seek(t), +args.still);
    await page.screenshot({ path: args.out, omitBackground: true });
    await browser.close();
    return;
  }
  const ff = spawn('ffmpeg', ['-y', '-v', 'error', '-f', 'image2pipe', '-framerate', String(FPS), '-c:v', 'png', '-i', '-',
    '-c:v', 'prores_ks', '-profile:v', '4444', '-pix_fmt', 'yuva444p10le', '-alpha_bits', '16', args.out], { stdio: ['pipe', 'inherit', 'inherit'] });
  const n = Math.round(DUR * FPS);
  for (let i = 0; i < n; i++) {
    await page.evaluate(t => window.seek(t), i / FPS);
    const buf = await page.screenshot({ omitBackground: true, type: 'png' });
    if (!ff.stdin.write(buf)) await new Promise(r => ff.stdin.once('drain', r));
  }
  ff.stdin.end();
  await new Promise((res, rej) => ff.on('close', c => (c === 0 ? res() : rej(new Error('ffmpeg exit ' + c)))));
  await browser.close();
})().catch(e => { console.error(e); process.exit(1); });
