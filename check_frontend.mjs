// Headless DOM smoke of the delivered HTML, without an installed browser runtime.
import fs from 'fs';
import assert from 'node:assert/strict';
import vm from 'node:vm';
const catalog=JSON.parse(fs.readFileSync(new URL('../data/demo_catalog.json',import.meta.url),'utf8'));
const html=fs.readFileSync(new URL('../web/index.html',import.meta.url),'utf8').replace('__HUB_CATALOG_JSON__',JSON.stringify(catalog));
const scripts=[...html.matchAll(/<script[^>]*>([\s\S]*?)<\/script>/g)].map(m=>m[1]);
assert(scripts.length>=2,'expected embedded data and client app');
const body={innerHTML:''};
const handlers={};
let cookie='';
const location={hash:'#home',search:'',href:'http://localhost:8753/'};
const browserWindow={location,scrollTo(){},addEventListener(name,callback){handlers['w-'+name]=callback}};
const doc={title:'',body:{appendChild(){}},getElementById(id){if(id==='app')return body;return null;},querySelectorAll(){return[];},addEventListener(name,cb){handlers['d-'+name]=cb;},createElement(){return {click(){},remove(){},style:{}}}};
async function apiFetch(path,params={}){
 const headers={...(params.headers||{})};if(cookie)headers.Cookie=cookie;
 const res=await fetch('http://127.0.0.1:8753'+path,{...params,headers});
 const set=res.headers.get('set-cookie');if(set)cookie=set.split(';')[0];
 return res;
}
const ctx=vm.createContext({window:browserWindow,document:doc,location,localStorage:{removeItem(){}},fetch:apiFetch,URL,URLSearchParams,console,setTimeout,clearTimeout,Intl,Math,Number,JSON,Date,Error,Array,Object,Set,Blob});
vm.runInContext(scripts[0],ctx);
vm.runInContext(scripts[1],ctx);
await new Promise(resolve=>setTimeout(resolve,500));
assert(body.innerHTML.includes('Supplier capability'), 'Homepage not rendered');
const pages=['home','solutions','approach','technology','workspace/overview','workspace/assessment','workspace/compare','workspace/interventions','workspace/economics','workspace/workflow','workspace/questionnaire','workspace/data','workspace/copilot'];
for (let page of pages) {
 location.hash='#'+page;
 vm.runInContext('render()',ctx);
 assert(body.innerHTML.length>1000,'Empty page '+page);
 assert(!body.innerHTML.includes('Cannot reach the supplier backend'),'API connection error '+page);
}
const before=await (await apiFetch('/api/suppliers/DEMO-EX-001')).json();
vm.runInContext("state.cases[0].ratings.A2=1.7;save()",ctx);
await vm.runInContext('saveQueue',ctx);
const after=await (await apiFetch('/api/suppliers/DEMO-EX-001')).json();
assert.equal(after.supplier.ratings.A2,1.7,'Browser edit did not persist to server');
vm.runInContext('askBackend("What interventions would you recommend?")',ctx);
await new Promise(resolve=>setTimeout(resolve,600));
const chatCount=vm.runInContext('state.chat.length',ctx);
assert(chatCount>=2,'Assistant preview did not append response');
console.log('PASS: 13 HTML pages rendered; Python API saved edits; backend assistant answered.');
