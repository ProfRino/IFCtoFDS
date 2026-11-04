// Exercise source/domain transitions and controller guards without WebGL.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.resolve(__dirname, '..');
class Element {
    constructor() { this.value=''; this.checked=false; this.files=[]; this.options=[]; this.children=[]; this.style={}; this.listeners={}; }
    appendChild(child) { this.children.push(child); return child; }
    replaceChildren() { this.children=[]; }
    addEventListener(name, callback) { (this.listeners[name] ||= []).push(callback); }
    dispatch(name) { for (const callback of this.listeners[name] || []) callback({target:this}); }
}
const elements = {};
const doc = {getElementById(id) { return elements[id] ||= new Element(); }, createElement() { return new Element(); }};
const get = id => doc.getElementById('verified-' + id);
const ns = {}, requests=[];
let inventoryResponse;
const context = vm.createContext({window:{IfcFds:ns}, document:doc, location:{protocol:'http:'},
    FormData:class {constructor(){this.values={};}append(key,value){this.values[key]=value;}},
    fetch:async(url,options) => ({ok:true,json:async()=>{
        if (url === '/api/reference-cases') return {cases:[]};
        if (url === '/api/inventory') return new Promise(resolve => { inventoryResponse=resolve; });
        if (url === '/api/jobs') { requests.push(JSON.parse(options.body.values.configuration)); return {id:'job'}; }
        if (url.endsWith('/result')) return {status:'INCONCLUSIVE',artifacts:{}};
        return {state:'COMPLETED'};
    }})});
vm.runInContext(fs.readFileSync(path.join(root,'js/verified-workflow.js'),'utf8'),context);
const all={name:'ALL_FDS_2027.ifc'}, tang={name:'Tang7.ifc'}, other={name:'other.ifc'};
const oldBounds={xmin:-11.12,xmax:88.79,ymin:-.15239290419950555,ymax:17.66,zmin:-8.91,zmax:38.46};
const newBounds={xmin:.719917502021417,xmax:39.2264255451737,ymin:.011711638886481524,ymax:29.047096841037273,zmin:19.600000000002062,zmax:23.70000000000214};
function fillDomain(bounds) { for (const axis in bounds) get('domain-'+axis).value=String(bounds[axis]); }
function select(files) { get('sources').files=files; get('sources').dispatch('change'); }
function extractControllerFunction(name) {
    const source=fs.readFileSync(path.join(root,'js/app-controller.js'),'utf8');
    const start=source.indexOf('    function '+name+'(');
    assert.notEqual(start,-1,'Missing controller function '+name);
    const end=source.indexOf('\n    function ',start+1);
    return source.slice(start,end<0?source.lastIndexOf('})(window.IfcFds)'):end);
}
(async()=>{
    ns.verified.init();
    ns.verified.setFallback(all);
    assert.equal(ns.verified.suggestDomainFromSource(all,oldBounds),true);
    assert.equal(Number(get('domain-ymin').value),oldBounds.ymin,'Domain suggestion shrank its source bounds');
    get('use-domain').checked=true; get('use-domain').dispatch('change');
    get('domain-xmin').value='-20'; get('domain-xmin').dispatch('input');
    ns.verified.setFallback(all);
    assert.equal(ns.verified.suggestDomainFromSource(all,oldBounds),false,'Late preview overwrote a manual same-source domain');
    await ns.verified.run(all,{});
    assert.equal(requests.at(-1).simulation_domain.xmin,-20);

    select([tang]);
    assert.equal(get('use-domain').checked,false);
    for (const axis in oldBounds) assert.equal(get('domain-'+axis).value,'');
    await ns.verified.run(all,{simulation_domain:oldBounds});
    assert.equal('simulation_domain' in requests.at(-1),false,'Unchecked or stale domain escaped into request');
    assert.equal(ns.verified.suggestDomainFromSource(all,oldBounds),false,'Mismatched viewer changed selected source domain');
    assert.equal(ns.verified.suggestDomainFromSource(tang,newBounds),true);
    assert.equal(Number(get('domain-ymax').value),newBounds.ymax);

    get('use-domain').checked=true; fillDomain(newBounds);
    // Valid declared domains may be intentionally smaller; preserve the reviewed input.
    get('domain-ymax').value='25'; get('domain-ymax').dispatch('input');
    assert.equal(ns.verified.suggestDomainFromSource(tang,newBounds),false);
    await ns.verified.run(all,{});
    assert.equal(requests.at(-1).simulation_domain.ymax,25);
    for (const [axis,value] of [['xmin',''],['xmin',' '],['xmin','NaN'],['xmin','Infinity'],['xmin','40'],['ymax',newBounds.ymin]]) {
        fillDomain(newBounds); get('domain-'+axis).value=String(value);
        const before=requests.length;
        await assert.rejects(ns.verified.run(all,{}),/finite coordinates|minimum must be less/);
        assert.equal(requests.length,before,'Invalid declared domain was uploaded');
    }

    // An old inventory response must not mutate the replacement source's storeys/domain.
    get('use-domain').checked=false;
    get('inventory').dispatch('click');
    while (!inventoryResponse) await new Promise(setImmediate);
    select([other]);
    const staleInventory={total_elements:1,sources:[{source_id:'old'}],storey_references:[{storey_id:'old:1',source_id:'old',name:'OLD'}]};
    inventoryResponse(staleInventory);
    await new Promise(setImmediate); await new Promise(setImmediate);
    assert.equal(get('storeys').children.length,0);
    assert.equal(ns.verified.suggestDomainFromSource(tang,newBounds),false);
    select([tang,other]);
    assert.equal(ns.verified.suggestDomainFromSource(tang,newBounds),false,'Single viewer supplied federated domain');
    // Explicit selection owns the domain; changing an unrelated fallback does not clear it.
    get('use-domain').checked=true; fillDomain(newBounds);
    ns.verified.setFallback(other);
    assert.equal(get('use-domain').checked,true);

    const state={ifcModel:{backendPreview:true,elements:[{stepId:6967}]},fullModel:{elements:[]},exportBusy:false,exportEnabled:true,selection:[]};
    const els={convertIfc:new Element(),convertVerified:new Element(),convertSelectedObst:new Element(),auditBody:new Element()};
    const controller=vm.createContext({state,els,document:doc,ns:{verified:{hasFiles:()=>true}},
        selectedGeneratedGeomStepIds:()=>[],splitSelectionForDelete:()=>({stepIds:[],itemIds:[]}),
        updateGlobalStatusBadge(){},renderAuditDrawer(){}});
    for (const name of ['setExportEnabled','supportsQuickExport','refreshConversionActions','ensureFullModel','renderAuditReport']) {
        vm.runInContext(extractControllerFunction(name),controller);
    }
    // Every toggle/delete/undo route eventually goes through these real controller guards.
    for (let i=0;i<3;i++) { controller.setExportEnabled(true); assert.equal(els.convertIfc.disabled,true); }
    state.exportEnabled=true; controller.refreshConversionActions(); assert.equal(els.convertIfc.disabled,true);
    await assert.rejects(controller.ensureFullModel(),error=>error.name==='PreviewOnlyModelError' && /Verified Conversion/.test(error.message));
    state.ifcModel={elements:[{stepId:1}]}; controller.setExportEnabled(true);
    assert.equal(els.convertIfc.disabled,false,'Complete-model route was disabled');
    assert.equal(await controller.ensureFullModel(),state.fullModel);

    const exported={entities:3,primitives:3,obst:1,geom:2,verified_entities:1,comparison_mode:'PARTIAL',
        attempted_entities:2,compared_entities:1,deviated_entities:0,failed_comparison_entities:0,inconclusive_comparison_entities:1,
        not_compared_entities:2,source_invalid_entities:1,comparisons_skipped_for_source_errors:false,skipped_for_source_errors:0};
    controller.renderAuditReport({status:'REJECTED',mapping_status:'REJECTED',simulation_status:'REJECTED',coverage:{fds_export:exported}});
    const text=els.auditBody.children.map(node=>node.textContent).join('\n');
    assert.match(text,/1 completed, 2 attempted, 1 verified/);
    assert.match(text,/2 written entities not compared/);
    assert.match(text,/Only independent local comparisons were collected/);
    assert.match(text,/dependent global checks/);
    assert.doesNotMatch(text,/undefined|remaining solid comparisons/);
    console.log('Conversion contracts: source ownership, precise bounds, invalid-input rejection, stale inventory, Quick guards and partial-audit rendering passed.');
})().catch(error=>{console.error(error);process.exitCode=1;});
