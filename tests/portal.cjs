// Browser interaction checks against a mocked HTTP boundary; no installed-site claims.
const {chromium} = require('playwright');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const root = path.resolve(__dirname, '..');
const fixture = {
  event:{event_title:'Annual Reception',host_name:'Aakvatech',starts_on:'2027-01-10 18:00:00',ends_on:'2027-01-10 21:00:00',rsvp_deadline:'2027-01-05 18:00:00',timezone:'Africa/Dar_es_Salaam',venue:'Dar es Salaam',allow_maybe:1,privacy_notice:'Your details are used for this event.'},
  invitation:{guest_name:'Asha',max_attendees:2,response_status:'Pending'},
  functions:[{name:'dinner',function_title:'Dinner',starts_on:'2027-01-10 18:00:00',venue:'Dar es Salaam',meal_options:'Vegetarian\nStandard'}],attendees:[],editable:true
};
(async()=>{
  const browser=await chromium.launch({headless:true});
  try {
    for(const viewport of [{width:390,height:844},{width:1280,height:900}]) {
      const page=await browser.newPage({viewport}); const errors=[];page.on('pageerror',e=>errors.push(e.message));
      await page.route('https://rsvp.test/**',route=>route.fulfill({contentType:'text/html',body:'<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"></head><body><main class="rsvp-shell"><a class="rsvp-brand">AV RSVP</a><div id="rsvp-root"></div></main></body></html>'}));
      await page.goto('https://rsvp.test/rsvp#'+'a'.repeat(64));
      await page.addStyleTag({content:'*{box-sizing:border-box}body{margin:0;font-family:Arial,sans-serif}'+fs.readFileSync(path.join(root,'av_rsvp/www/rsvp.css'),'utf8')});
      await page.evaluate(data=>{
        window.calls=[];window.testState=structuredClone(data);
        window.frappe={ready:fn=>fn(),utils:{escape_html:v=>String(v).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))},call:async({method,args})=>{
          window.calls.push({method,args});
          if(method.endsWith('.respond')) {
            window.testState.attendees=JSON.parse(args.people).map((p,i)=>({...p,name:'person-'+i,functions:p.functions.map(f=>({...f,allocation:f.attendance==='Attending'?'Confirmed':'Cancelled'}))}));
            window.testState.invitation.response_status=args.response;
          }
          return {message:structuredClone(window.testState)};
        }};
      },fixture);
      await page.addScriptTag({content:fs.readFileSync(path.join(root,'av_rsvp/www/rsvp.js'),'utf8')});
      await page.getByRole('heading',{name:'Annual Reception'}).waitFor();
      assert.equal(await page.locator('[data-person]').count(),1);
      await page.getByRole('button',{name:'+ Add guest'}).click();
      assert.equal(await page.locator('[data-person]').count(),2);
      assert.equal(await page.getByRole('button',{name:'+ Add guest'}).isDisabled(),true);
      await page.locator('#name-1').fill('<img src=x onerror=alert(1)>');
      await page.locator('[data-meal]').first().selectOption('Vegetarian');
      await page.locator('[data-meal]').nth(1).selectOption('Standard');
      await page.getByRole('button',{name:'Save response',exact:true}).click();
      await page.getByRole('status').waitFor();
      assert.equal(await page.locator('img[src="x"]').count(),0);
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
      await page.locator('#overall').selectOption('Declined');
      await page.getByRole('button',{name:'Save response',exact:true}).click();
      const calls=await page.evaluate(()=>window.calls.filter(c=>c.method.endsWith('.respond')));
      assert.equal(calls.length,2);
      assert.equal(JSON.parse(calls[1].args.people)[0].functions[0].attendance,'Declined');
      assert.deepEqual(errors,[]);
      await page.screenshot({path:`/tmp/rsvp-portal-${viewport.width}.png`,fullPage:true});
      await page.close();
    }
    console.log('Portal browser checks passed at phone and desktop widths.');
  } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
