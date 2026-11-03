// Verify the event form actions and exported clipboard/download payloads.
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const source = fs.readFileSync(path.join(__dirname, '../av_rsvp/rsvp/doctype/rsvp_event/rsvp_event.js'), 'utf8');
(async () => {
  const handlers = {}, alerts = [], messages = [], writes = [];
  let controller, copiedLink, downloaded, calls = 0;
  const image = 'data:image/png;base64,' + Buffer.from('test-png-payload').toString('base64');
  const url = 'https://events.example/rsvp?event=RSVP-EVT-2026-00001';
  const context = {
    __:v=>v, Uint8Array, Blob, atob,
    window:{isSecureContext:true, ClipboardItem:class {}},
    ClipboardItem:class {constructor(data){this.data=data;}},
    navigator:{clipboard:{write:async items=>writes.push(items)}},
    document:{body:{appendChild:()=>{}},createElement:()=>({click(){downloaded={href:this.href,download:this.download};},remove(){}})},
    frappe:{
      ui:{form:{on:(_name,config)=>{controller=config;}},Dialog:class {
        constructor(){this.fields_dict={preview:{$wrapper:{html:()=>{}}}};this.$wrapper={find:selector=>({on:(_event,fn)=>{handlers[selector]=fn;}})};}
        show(){}
      }},
      utils:{escape_html:String,copy_to_clipboard:link=>{copiedLink=link;}},
      call:async()=>{calls++;return {message:{event_title:'Reception',image,url,filename:'registration.png'}};},
      msgprint:message=>messages.push(message),show_alert:alert=>alerts.push(alert),
      model:{can_create:()=>false},
    },
  };
  vm.createContext(context);vm.runInContext(source,context);
  const buttons=[];
  const frm={doc:{name:'event',allow_public_registration:1,status:'Published'},is_new:()=>false,is_dirty:()=>false,add_custom_button:(label,action)=>buttons.push({label,action})};
  controller.refresh(frm);
  await buttons.find(button=>button.label==='Registration QR Code').action();
  await handlers['[data-copy-qr]']();
  assert.equal(writes.length,1);
  assert.equal(await writes[0][0].data['image/png'].text(),'test-png-payload');
  assert.equal(alerts.length,1);
  handlers['[data-download-qr]']();
  assert.deepEqual(downloaded,{href:image,download:'registration.png'});
  handlers['[data-copy-link]']();assert.equal(copiedLink,url);
  context.window.isSecureContext=false;
  await handlers['[data-copy-qr]']();
  assert.equal(writes.length,1);assert.ok(messages.at(-1).includes('Download PNG'));
  frm.is_dirty=()=>true;
  await context.av_rsvp_show_registration_qr(frm);
  assert.equal(calls,1);assert.ok(messages.at(-1).includes('Save the event'));
  buttons.length=0;frm.doc.allow_public_registration=0;controller.refresh(frm);
  assert.ok(!buttons.some(button=>button.label==='Registration QR Code'));
  console.log('Event QR copy, download, link and fallback checks passed.');
})().catch(error=>{console.error(error);process.exit(1);});
