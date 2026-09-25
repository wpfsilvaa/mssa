// Real-browser smoke test. Start the dashboard first; CHROME may override the executable.
import assert from "node:assert/strict";
import {spawn} from "node:child_process";
import {mkdtemp, mkdir, readdir, writeFile} from "node:fs/promises";
import {tmpdir} from "node:os";
import {join} from "node:path";

const base = process.env.MSSA_URL || "http://127.0.0.1:8765";
const profile = await mkdtemp(join(tmpdir(),"mssa-browser-"));
const downloads = join(profile,"downloads");
await mkdir(downloads);
const browser = spawn(process.env.CHROME || "/opt/google/chrome/chrome",[
  "--headless=new","--no-sandbox","--disable-dev-shm-usage","--no-first-run",
  "--no-default-browser-check","--remote-debugging-port=0",`--user-data-dir=${profile}`,"about:blank",
],{stdio:["ignore","ignore","pipe"]});
let socket, sequence = 0;
const pending = new Map(), errors = [];
const pause = (ms) => new Promise((resolve)=>setTimeout(resolve,ms));
const debuggerURL = await new Promise((resolve,reject)=>{
  const timeout=setTimeout(()=>reject(new Error("Browser did not start")),15000);
  let output="";
  browser.stderr.on("data",(chunk)=>{output+=chunk;const match=output.match(/DevTools listening on (ws:\/\/[^\s]+)/);if(match){clearTimeout(timeout);resolve(match[1]);}});
  browser.on("error",reject);
});
try {
  const address = new URL(debuggerURL);
  const pages = await (await fetch(`http://${address.host}/json/list`)).json();
  socket = new WebSocket(pages.find((p)=>p.type==="page").webSocketDebuggerUrl);
  await new Promise((resolve,reject)=>{socket.onopen=resolve;socket.onerror=reject;});
  socket.onmessage=(event)=>{
    const data=JSON.parse(event.data);
    if(data.id){const waiter=pending.get(data.id);pending.delete(data.id);if(data.error)waiter.reject(new Error(JSON.stringify(data.error)));else waiter.resolve(data.result);}
    if(data.method==="Runtime.exceptionThrown")errors.push(data.params.exceptionDetails);
    if(data.method==="Runtime.consoleAPICalled"&&data.params.type==="error")errors.push(data.params.args);
  };
  const call = (method,params={})=>new Promise((resolve,reject)=>{const id=++sequence;pending.set(id,{resolve,reject});socket.send(JSON.stringify({id,method,params}));});
  const evaluate = async(expression)=>{
    const result=await call("Runtime.evaluate",{expression,returnByValue:true,awaitPromise:true});
    if(result.exceptionDetails)throw new Error(JSON.stringify(result.exceptionDetails));
    return result.result.value;
  };
  const waitFor = async(expression)=>{
    for(let i=0;i<150;i++){if(await evaluate(expression))return;await pause(50);}
    throw new Error(`Timed out: ${expression}`);
  };
  const click = (selector)=>evaluate(`document.querySelector(${JSON.stringify(selector)}).click()`);
  const change = (selector,value)=>evaluate(`(()=>{const node=document.querySelector(${JSON.stringify(selector)});node.value=${JSON.stringify(value)};node.dispatchEvent(new Event('change',{bubbles:true}));})()`);
  await call("Runtime.enable");
  await call("Page.enable");
  await call("Emulation.setDeviceMetricsOverride",{width:1440,height:1050,deviceScaleFactor:1,mobile:false});
  await call("Browser.setDownloadBehavior",{behavior:"allow",downloadPath:downloads});
  await call("Page.navigate",{url:base});
  await waitFor("document.querySelector('#status-label')?.textContent === 'Simulação pausada'");
  assert.equal(await evaluate("document.querySelectorAll('.agent-item').length"),3);
  await click("#step");
  await waitFor("document.querySelector('#time').textContent.includes('0.25')");
  await change("#speed","8");await click("#play");
  await waitFor("parseFloat(document.querySelector('#time').textContent) >= 8");
  await click("#play");
  await waitFor("!document.querySelector('#step').disabled");
  assert.ok(await evaluate("document.querySelectorAll('.event-row').length > 0"));
  const screenshot=await call("Page.captureScreenshot",{format:"png"});
  await writeFile("/tmp/mssa-dashboard.png",Buffer.from(screenshot.data,"base64"));

  await click('.agent-item[data-index="1"]');
  await change("#reaction","avoid");
  assert.equal(await evaluate("document.querySelector('#play').disabled"),true);
  await click("#apply");await waitFor("!document.querySelector('#step').disabled");
  assert.equal(await evaluate("document.querySelector('#reaction').value"),"avoid");
  await change("#policy-kind","patrol");await click("#plot-route");
  const rect=await evaluate("(()=>{const r=document.querySelector('#map').getBoundingClientRect();return{x:r.x+r.width/2,y:r.y+r.height/2};})()");
  await call("Input.dispatchMouseEvent",{type:"mousePressed",x:rect.x,y:rect.y,button:"left",clickCount:1});
  await call("Input.dispatchMouseEvent",{type:"mouseReleased",x:rect.x,y:rect.y,button:"left",clickCount:1});
  assert.equal(await evaluate("document.querySelector('#waypoints').value.split('\\n').length"),3);
  await evaluate("document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape'}))");
  await click("#apply");await waitFor("!document.querySelector('#step').disabled");
  await click("#local-view");
  assert.equal(await evaluate("document.querySelector('#map-title').textContent"),"Percepção do agente");
  await click("#local-view");

  await click("#new");await click("#add-agent");await click("#add-sensor");
  await change("#policy-kind","patrol");
  await click("#add-agent");await click('[data-tab="links"]');await click("#add-link");
  await change('[data-endpoint="sender_id"]',"agent-1");
  await change('[data-endpoint="recipient_id"]',"agent-2");
  await click("#apply");await waitFor("!document.querySelector('#step').disabled");
  await click("#play");await waitFor("parseFloat(document.querySelector('#delivered').textContent) >= 1");await click("#play");
  await waitFor("!document.querySelector('#step').disabled");
  await click("#export");
  for(let i=0;i<100;i++){if((await readdir(downloads)).some((f)=>f.endsWith('.yaml')))break;await pause(50);}
  assert.ok((await readdir(downloads)).some((f)=>f.endsWith('.yaml')));
  const exported=(await readdir(downloads)).find((f)=>f.endsWith('.yaml'));
  await click("#new");
  const documentNode=await call("DOM.getDocument");
  const fileNode=await call("DOM.querySelector",{nodeId:documentNode.root.nodeId,selector:"#file"});
  await call("DOM.setFileInputFiles",{nodeId:fileNode.nodeId,files:[join(downloads,exported)]});
  await waitFor("document.querySelector('#notice').textContent.includes('Cenário importado')");
  assert.equal(await evaluate("document.querySelectorAll('.agent-item').length"),2);
  await click("#apply");await waitFor("!document.querySelector('#step').disabled");

  await click('[data-tab="scenario"]');
  await evaluate("document.querySelector('#raw-scenario').value='environment: {width: 0, height: 100}'");
  await click("#load-text");await waitFor("!document.querySelector('#notice').hidden");
  assert.ok(await evaluate("document.querySelector('#notice').textContent.includes('environment')"));
  await call("Page.reload");await waitFor("document.querySelector('#status-label')?.textContent === 'Simulação pausada'");
  assert.equal(await evaluate("document.querySelectorAll('.agent-item').length"),2);
  await call("Emulation.setDeviceMetricsOverride",{width:390,height:844,deviceScaleFactor:1,mobile:true});
  await pause(200);
  assert.ok(await evaluate("document.documentElement.scrollWidth <= 390"));
  const mobile=await call("Page.captureScreenshot",{format:"png"});
  await writeFile("/tmp/mssa-dashboard-mobile.png",Buffer.from(mobile.data,"base64"));
  assert.deepEqual(errors,[]);
  console.log(JSON.stringify({passed:true,checks:["play/pause/step","traffic","reaction editor","route on map","local perception","create agents and link","delivery","YAML export/import","invalid YAML","draft persistence","mobile layout"],screenshots:["/tmp/mssa-dashboard.png","/tmp/mssa-dashboard-mobile.png"]}));
} finally {
  if(socket)socket.close();
  browser.kill("SIGTERM");
}
