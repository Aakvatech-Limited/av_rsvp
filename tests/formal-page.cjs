const {chromium}=require('playwright');
const fs=require('node:fs');
const assert=require('node:assert/strict');
const dir=require('node:path').resolve(__dirname,'../av_rsvp/templates/formal');
const html=fs.readFileSync(dir+'/invitation.html','utf8');
const css=fs.readFileSync(dir+'/invitation.css','utf8');
const script=fs.readFileSync(dir+'/invitation.js','utf8');
const event={event_title:'Annual Installation',host_name:'Event Host',description:'<p>Our personal invitation.</p><p>Entering the Chair is a special occasion.</p>',footer_text:'<p>With warm regards,</p><p>Event Host</p>',banner:'/files/emblem.png',starts_on:'2027-01-10 18:00:00',ends_on:'2027-01-10 21:00:00',rsvp_deadline:'2027-01-05 18:00:00',timezone:'Africa/Dar_es_Salaam',venue:'Event Hall',allow_maybe:1,hide_first_guest_details:1,allow_additional_guests:0,show_dietary_preferences:0,additional_questions:[{question_key:'meal',question_label:'Meal preference',question_type:'Select',options:'Vegetarian\nVegan\nNot dining'}]};
const fixture={event,invitation:{guest_name:'Preview Guest',max_attendees:1,response_status:'Pending'},functions:[{name:'function-1',function_title:'Installation',starts_on:event.starts_on,venue:event.venue,meal_options:''}],attendees:[],editable:true};
(async()=>{
 const browser=await chromium.launch({headless:true,...(process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH?{executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH}:{})});
 try {
  for(const width of [736,390,320]){
   const page=await browser.newPage({viewport:{width,height:900}});
   const errors=[];page.on('pageerror',e=>errors.push(e.message));
   await page.route('https://rsvp.test/**',route=>route.request().resourceType()==='document'?route.fulfill({contentType:'text/html; charset=utf-8',body:'<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><style>*{box-sizing:border-box}body{margin:0}</style>'+html.replace('__EVENT_ID__','EVT-TEST')}):route.request().resourceType()==='image'?route.fulfill({contentType:'image/png',body:Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aXZkAAAAASUVORK5CYII=','base64')}):route.abort());
   await page.goto('https://rsvp.test/events/rsvp-evt-2026-00001#'+'a'.repeat(64));
   await page.addStyleTag({content:css});
   await page.evaluate(data=>{
    window.testState=structuredClone(data);window.calls=[];
    window.frappe={ready:fn=>fn(),utils:{escape_html:v=>String(v).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))},call:async({method,args})=>{
     window.calls.push({method,args});
     if(method.endsWith('.respond')){
      window.testState.invitation.response_status=args.response;
      window.testState.additional_answers=JSON.parse(args.additional_answers);
      window.testState.notes=args.notes;
      window.testState.attendees=JSON.parse(args.people).map(p=>({...p,name:'attendee-1',functions:p.functions.map(f=>({...f,allocation:args.response==='Attending'?'Confirmed':'Cancelled'}))}));
     }
     return {message:structuredClone(window.testState)};
    }};
   },fixture);
   await page.addScriptTag({content:script});
   await page.getByRole('heading',{name:'Will you be joining us?'}).waitFor();
   assert.equal(await page.locator('[name="overall-response"]:checked').count(),0);
   assert.equal(await page.locator('details,summary').count(),0);
   assert.ok((await page.locator('.lodge-description').innerText()).includes('Entering the Chair'));
   assert.equal(await page.locator('.lodge-signature').count(),1);
   assert.equal(await page.locator('[data-question]').count(),event.additional_questions.length);
   assert.equal(await page.locator('[data-question] option').allTextContents().then(v=>v.slice(1).join('\n')),event.additional_questions[0].options);
   await page.getByRole('button',{name:'Confirm my RSVP',exact:true}).click();
   assert.equal(await page.evaluate(()=>window.calls.filter(c=>c.method.endsWith('.respond')).length),0);
   if(width===736){const boxes=await page.locator('.lodge-choice').evaluateAll(nodes=>nodes.map(n=>n.getBoundingClientRect().top));assert.ok(boxes.every(y=>y===boxes[0]));}
   for(const [label,value] of [['Attending','Attending'],['Not attending','Declined'],['May be','Maybe']]){
    await page.getByRole('radio',{name:label,exact:true}).check();
    await page.locator('[data-question]').selectOption('Vegan');
    await page.locator('#notes').fill('Preview note');
    await page.getByRole('button',{name:'Confirm my RSVP',exact:true}).click();
    await page.getByRole('status').waitFor();
    assert.equal(await page.getByRole('radio',{name:label,exact:true}).isChecked(),true);
    const last=await page.evaluate(()=>window.calls.filter(c=>c.method.endsWith('.respond')).at(-1));
    assert.equal(last.args.response,value);assert.equal(last.args.notes,'Preview note');
    assert.equal(JSON.parse(last.args.additional_answers)[event.additional_questions[0].question_key],'Vegan');
   }
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
   assert.deepEqual(errors,[]);
   if(width===736)await page.screenshot({path:'/tmp/rsvp-formal-desktop.png',fullPage:true});
   if(width===390)await page.screenshot({path:'/tmp/rsvp-formal-mobile.png',fullPage:true});
   // Verify a reload restores the existing response and saved answers.
   await page.addScriptTag({content:script});
   assert.equal(await page.getByRole('radio',{name:'May be',exact:true}).isChecked(),true);
   assert.equal(await page.locator('[data-question]').inputValue(),'Vegan');
   await page.evaluate(()=>window.testState.editable=false);
   await page.addScriptTag({content:script});
   assert.equal(await page.locator('[name="overall-response"]:disabled').count(),3);
   assert.equal(await page.locator('#save-response').count(),0);
   console.log('Passed: '+width+'px, all response mappings, questionnaire, restore, closed state, no overflow.');
   await page.close();
  }
 } finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
