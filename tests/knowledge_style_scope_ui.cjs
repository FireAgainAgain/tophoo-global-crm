// Read-only component check: neither business APIs nor real database writes are used.
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');

(async () => {
  const browser = await chromium.launch({channel:'msedge', headless:true});
  try {
    const page = await browser.newPage();
    const css = fs.readFileSync('app/static/css/knowledge-library-ui.css', 'utf8');
    await page.setContent('<!doctype html><div id="foreign">Other module</div><div class="crm-communication-scripts"><div class="script-workbench" id="inside"></div></div><div class="script-category-menu" id="knowledge-category-menu">Menu</div>');
    await page.addStyleTag({content:css});
    const measured = await page.evaluate(() => {
      const el=document.querySelector('#foreign');
      const read=el=>{const s=getComputedStyle(el);return {display:s.display,background:s.backgroundColor,border:s.borderWidth,padding:s.padding,position:s.position};};
      const before=read(el);
      el.className='script-workbench script-reader script-editor script-category-menu';
      return {before,after:read(el),inside:read(document.querySelector('#inside')),menu:read(document.querySelector('#knowledge-category-menu'))};
    });
    assert.deepEqual(measured.before, measured.after, 'Knowledge styles must not affect similarly named elements in another module');
    assert.equal(measured.inside.display, 'grid');
    assert.equal(measured.menu.position, 'fixed', 'The portaled category menu must remain styled');
    console.log('PASS: knowledge styles stay inside the module; portaled menu and current layout work. No business requests.');
  } finally { await browser.close(); }
})().catch(error=>{console.error(error.message);process.exit(1);});
