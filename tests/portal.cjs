// Browser interaction checks against a mocked HTTP boundary; no installed-site claims.
const {chromium} = require('playwright');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const root = path.resolve(__dirname, '..');
const fixture = {
  event:{description:'Welcome to our event.\r\nPlease arrive at 6 pm.\r\n\r\nDinner follows.',event_title:'Annual Reception',host_name:'Aakvatech',starts_on:'2027-01-10 18:00:00',ends_on:'2027-01-10 21:00:00',rsvp_deadline:'2027-01-05 18:00:00',timezone:'Africa/Dar_es_Salaam',venue:'Dar es Salaam',allow_maybe:1,privacy_notice:'Your details are used for this event.'},
  invitation:{guest_name:'Asha',max_attendees:2,response_status:'Pending'},
  functions:[{name:'dinner',function_title:'Dinner',starts_on:'2027-01-10 18:00:00',venue:'Dar es Salaam',meal_options:'Vegetarian\nStandard'}],attendees:[],editable:true
};
(async()=>{
  const browser=await chromium.launch({headless:true});
  try {
    for(const publicMode of [false,true]) {
    for(const viewport of [{width:390,height:844},{width:1280,height:900}]) {
      const page=await browser.newPage({viewport}); const errors=[];page.on('pageerror',e=>errors.push(e.message));
      await page.route('https://rsvp.test/**',route=>route.fulfill({contentType:'text/html',body:'<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"></head><body><main class="rsvp-shell"><a class="rsvp-brand">AV RSVP</a><div id="rsvp-root"></div></main></body></html>'}));
      await page.goto(publicMode ? 'https://rsvp.test/rsvp?event=public-event' : 'https://rsvp.test/rsvp#'+'a'.repeat(64));
      await page.addStyleTag({content:'*{box-sizing:border-box}body{margin:0;font-family:Arial,sans-serif}'+fs.readFileSync(path.join(root,'av_rsvp/www/rsvp.css'),'utf8')});
      await page.evaluate(({data, publicMode})=>{
        window.calls=[];window.testState=structuredClone(data); if(publicMode) window.testState.invitation.guest_name="";
        window.frappe={ready:fn=>fn(),utils:{escape_html:v=>String(v).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))},call:async({method,args})=>{
          window.calls.push({method,args});
          if(method.endsWith('.respond') || method.endsWith('.register')) {
            window.testState.attendees=JSON.parse(args.people).map((p,i)=>({...p,name:'person-'+i,functions:p.functions.map(f=>({...f,allocation:f.attendance==='Attending'?'Confirmed':'Cancelled'}))}));
            window.testState.invitation.response_status=args.response;
            window.testState.additional_answers=JSON.parse(args.additional_answers || "{}");
          }
          if(method.endsWith('.register')) return {message:{token:'b'.repeat(64),registration:structuredClone(window.testState)}};
          return {message:structuredClone(window.testState)};
        }};
      },{data:fixture,publicMode});
      await page.addScriptTag({content:fs.readFileSync(path.join(root,'av_rsvp/www/rsvp.js'),'utf8')});
      await page.getByRole('heading',{name:'Annual Reception'}).waitFor();
      const description=page.locator('.rsvp-multiline').first();
      assert.equal(await description.evaluate(el=>getComputedStyle(el).whiteSpace),'pre-line');
      assert.equal((await description.innerText()).replace(/\r\n/g,'\n'),fixture.event.description.replace(/\r\n/g,'\n'));
      assert.equal(await page.locator('[data-person]').count(),1);
      await page.getByRole('button',{name:'+ Add guest'}).click();
      assert.equal(await page.locator('[data-person]').count(),2);
      assert.equal(await page.getByRole('button',{name:'+ Add guest'}).isDisabled(),true);
      await page.locator('#name-1').fill('<img src=x onerror=alert(1)>');
      await page.locator('[data-meal]').first().selectOption('Vegetarian');
      await page.locator('[data-meal]').nth(1).selectOption('Standard');
      if(publicMode) {await page.locator('#contact-guest_name').fill('New Guest');await page.locator('#contact-email').fill('new@example.com');await page.locator('#name-0').fill('New Guest');}
      await page.getByRole('button',{name:publicMode?'Register and save RSVP':'Save response',exact:true}).click();
      await page.getByRole('status').waitFor();
      if(publicMode) assert.equal(new URL(page.url()).hash,'#'+'b'.repeat(64));
      assert.equal(await page.locator('img[src="x"]').count(),0);
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
      await page.locator('#overall').selectOption('Declined');
      await page.getByRole('button',{name:'Save response',exact:true}).click();
      const calls=await page.evaluate(()=>window.calls.filter(c=>c.method.endsWith('.respond') || c.method.endsWith('.register')));
      assert.equal(calls.length,2);
      if(publicMode) {assert.equal(calls[0].method,'av_rsvp.api.register');assert.match(calls[0].args.registration_key,/^[a-f0-9]{64}$/);assert.equal(calls[0].args.email,'new@example.com');assert.equal(calls[1].args.token,'b'.repeat(64));}
      assert.equal(JSON.parse(calls[1].args.people)[0].functions[0].attendance,'Declined');
      await page.evaluate(()=>{
        Object.assign(window.testState.event,{show_dietary_preferences:0,allow_additional_guests:0,additional_questions:[
          {question_key:'transport',question_label:'Transport',question_type:'Select',options:'Bus\nCar'},
          {question_key:'comments',question_label:'Comments <img src=x onerror=alert(1)>',question_type:'Long Text'},
          {question_key:'contact',question_label:'Contact me',question_type:'Check'}
        ]});
      });
      await page.addScriptTag({content:fs.readFileSync(path.join(root,'av_rsvp/www/rsvp.js'),'utf8')});
      await page.getByRole('heading',{name:'Additional questions (optional)',exact:true}).waitFor();
      assert.equal(await page.locator('#add-person').count(),0);
      assert.equal(await page.locator('[data-field="dietary_requirements"]').count(),0);
      assert.equal(await page.locator('img[src="x"]').count(),0);
      assert.deepEqual(await page.locator('[data-question]').evaluateAll(nodes=>nodes.map(n=>n.dataset.question)),['transport','comments','contact']);
      await page.locator('#question-transport').selectOption('Bus');
      await page.locator('#question-comments').fill('Window seat please');
      await page.locator('#question-contact').check();
      await page.locator('[data-remove="1"]').click();
      assert.equal(await page.locator('#question-transport').inputValue(),'Bus');
      assert.equal(await page.locator('#question-comments').inputValue(),'Window seat please');
      assert.equal(await page.locator('#question-contact').isChecked(),true);
      await page.getByRole('button',{name:'Save response',exact:true}).click();
      await page.getByRole('status').waitFor();
      assert.equal(await page.locator('#question-comments').inputValue(),'Window seat please');
      const last=await page.evaluate(()=>window.calls.at(-1));
      assert.deepEqual(JSON.parse(last.args.additional_answers),{transport:'Bus',comments:'Window seat please',contact:'1'});
      await page.evaluate(()=>{window.testState.event.show_dietary_preferences=1;window.testState.event.dietary_options='Vegetarian\nStandard';});
      await page.addScriptTag({content:fs.readFileSync(path.join(root,'av_rsvp/www/rsvp.js'),'utf8')});
      const diet=page.locator('select[data-field="dietary_requirements"]');
      await diet.waitFor();
      assert.equal(await diet.getAttribute('required'),null);
      assert.equal(await diet.locator('option').first().getAttribute('value'),'');
      await page.evaluate(()=>{window.testState.event.hide_first_guest_details=1;});
      await page.addScriptTag({content:fs.readFileSync(path.join(root,'av_rsvp/www/rsvp.js'),'utf8')});
      await page.getByRole('heading',{name:'Your attendance',exact:true}).waitFor();
      assert.equal(await page.locator('#name-0').count(),0);
      assert.equal(await page.locator('#age-0').count(),0);
      assert.equal(await page.locator('#diet-0').count(),0);
      assert.equal(await page.locator('#add-person').count(),0);
      assert.equal(await page.locator('[data-meal]').count(),1);
      await page.evaluate(()=>{window.testState.functions[0].meal_options='';});
      await page.addScriptTag({content:fs.readFileSync(path.join(root,'av_rsvp/www/rsvp.js'),'utf8')});
      assert.equal(await page.locator('[data-person]').count(),0);
      await page.locator('#overall').selectOption('Attending');
      await page.getByRole('button',{name:'Save response',exact:true}).click();
      await page.getByRole('status').waitFor();
      const hidden=await page.evaluate(()=>JSON.parse(window.calls.at(-1).args.people));
      assert.equal(hidden[0].functions[0].attendance,'Attending');
      assert.ok(hidden[0].attendee_name);
      assert.deepEqual(errors,[]);
      await page.screenshot({path:`/tmp/rsvp-portal-${publicMode?"public":"private"}-${viewport.width}.png`,fullPage:true});
      await page.close();
    }
    }
    console.log('Portal browser checks passed at phone and desktop widths.');
  } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
