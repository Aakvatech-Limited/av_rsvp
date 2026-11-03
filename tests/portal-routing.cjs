// Exercise initial public/private routing without a browser installation.
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const {webcrypto} = require('node:crypto');
const source = fs.readFileSync(path.join(__dirname, '../av_rsvp/www/rsvp.js'), 'utf8');
(async () => {
  for (const [search, hash, method, registration] of [
    ['?event=public-event', '', 'get_registration', true],
    ['?event=public-event', '#private-token', 'get_invitation', false],
    ['?invitation=staff-invite', '', 'staff_invitation', false],
    ['', '#private-token', 'get_invitation', false],
    ['', '', null, false],
  ]) {
    const calls = [];
    const root = {innerHTML:'', querySelector:()=>null, querySelectorAll:()=>[]};
    let ready;
    vm.runInNewContext(source, {
      URLSearchParams, structuredClone, crypto:webcrypto,
      window:{location:{search, hash}},
      document:{getElementById:()=>root},
      frappe:{utils:{escape_html:String}, ready:fn=>{ready=fn();}, call:async args=>{
        calls.push(args);
        return {message:{event:{event_title:'Test',allow_maybe:1}, invitation:{guest_name:'Guest', max_attendees:2, response_status:'Pending'}, functions:[], attendees:[], editable:true}};
      }},
    });
    await ready;
    assert.equal(calls.length, method ? 1 : 0);
    if (method) assert.equal(calls[0].method, `av_rsvp.api.${method}`);
    assert.equal(root.innerHTML.includes('Your contact details'), registration);
    if (registration) {
      assert.equal(calls[0].args.event, 'public-event');
      assert.ok(root.innerHTML.includes('Register and save RSVP'));
    }
  }
  console.log('Public, private and staff portal routing checks passed.');
})().catch(error=>{console.error(error);process.exit(1);});
